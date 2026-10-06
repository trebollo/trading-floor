"""Adaptador NATS JetStream del bus de eventos.

Misma interfaz que `InMemoryBus` y la misma política: **validación de contrato en el
borde** (G2) — nada entra a NATS sin cumplir su esquema. Los subjects son los propios
tipos de mensaje (`strategy.proposal.v1`), y un stream `TF` los captura todos.

nats-py es async; este adaptador gestiona un event loop en un hilo propio para ofrecer
la interfaz síncrona de `BaseBus` a los agentes.
"""

from __future__ import annotations

import asyncio
import json
import queue
import threading
from collections import defaultdict
from dataclasses import dataclass, replace
from typing import Any

from tf.bus import BaseBus, Handler
from tf.contracts import REGISTRY, Envelope, validate_payload


@dataclass(frozen=True)
class NatsDelivery:
    """Mensaje JetStream pendiente de ack, entregado al hilo consumidor."""

    envelope: Envelope
    message: Any

    @property
    def num_delivered(self) -> int:
        return int(self.message.metadata.num_delivered)


def envelope_to_json(envelope: Envelope) -> bytes:
    return json.dumps(envelope.model_dump(mode="json"), default=str).encode()


def envelope_from_json(raw: bytes) -> Envelope:
    envelope = Envelope.model_validate_json(raw)
    validate_payload(envelope.type, envelope.payload)
    return envelope


class NatsBus(BaseBus):
    def __init__(
        self,
        servers: list[str] | None = None,
        stream: str = "TF",
        timeout: float = 10.0,
        max_reconnect: int = -1,
    ) -> None:
        self._servers = servers or ["nats://localhost:4222"]
        self._stream = stream
        self._timeout = timeout
        self._max_reconnect = max_reconnect
        self._handlers: dict[str, list[Handler]] = defaultdict(list)
        self._loop = asyncio.new_event_loop()
        self._thread: threading.Thread | None = None
        self._nc = None
        self._js = None
        self._deliveries: queue.Queue[NatsDelivery] = queue.Queue()
        self._subscriptions: list[Any] = []

    # -- ciclo de vida ------------------------------------------------------------

    def start(self) -> "NatsBus":
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        self._run_coro(self._connect())
        return self

    async def _connect(self) -> None:
        import nats  # import diferido: solo requiere el paquete si se usa

        self._nc = await nats.connect(
            servers=self._servers,
            connect_timeout=self._timeout,
            max_reconnect_attempts=self._max_reconnect,
        )
        self._js = self._nc.jetstream()
        from nats.js.api import StreamConfig

        # El subject global ">" exige no_ack=True en JetStream (err 10052); en su lugar
        # declaramos los subjects concretos del registro de contratos.
        try:
            await self._js.add_stream(
                StreamConfig(
                    name=self._stream,
                    subjects=sorted(REGISTRY.keys()),
                    max_age=7 * 24 * 60 * 60,
                    duplicate_window=24 * 60 * 60,
                )
            )
        except Exception as first_error:
            try:
                info = await self._js.stream_info(self._stream)
            except Exception:
                raise RuntimeError(
                    f"No se pudo crear el stream JetStream '{self._stream}': {first_error}"
                ) from first_error
            current_subjects = set(info.config.subjects or [])
            required_subjects = set(REGISTRY)
            desired_window = 24 * 60 * 60
            if not required_subjects.issubset(current_subjects) or info.config.duplicate_window < desired_window:
                await self._js.update_stream(
                    replace(
                        info.config,
                        subjects=sorted(current_subjects | required_subjects),
                        duplicate_window=max(info.config.duplicate_window, desired_window),
                    )
                )

    def close(self) -> None:
        if self._nc is not None:
            for subscription in self._subscriptions:
                try:
                    self._run_coro(subscription.unsubscribe())
                except Exception:
                    pass
            self._run_coro(self._nc.close())
        self._loop.call_soon_threadsafe(self._loop.stop)

    # -- BaseBus --------------------------------------------------------------------

    def publish(self, envelope: Envelope) -> None:
        # G2: la misma validación en el borde que el bus en memoria.
        validate_payload(envelope.type, envelope.payload)
        # stream explícito: sin búsqueda por subject que pueda fallar.
        self._run_coro(
            self._js.publish(
                envelope.type,
                envelope_to_json(envelope),
                stream=self._stream,
                headers={"Nats-Msg-Id": envelope.id},
            )
        )

    def subscribe(self, msg_type: str, handler: Handler) -> None:
        self._handlers[msg_type].append(handler)
        from nats.js.api import DeliverPolicy

        async def _subscribe() -> None:
            async def cb(msg: Any) -> None:
                envelope = envelope_from_json(msg.data)
                for h in self._handlers.get(envelope.type, []):
                    h(envelope)

            # Suscripción efímera = eventos nuevos; el replay histórico es para
            # consumers durables explícitos, no para cada ciclo batch.
            await self._js.subscribe(
                msg_type,
                cb=cb,
                stream=self._stream,
                deliver_policy=DeliverPolicy.NEW,
            )

        self._run_coro(_subscribe())

    def subscribe_durable(
        self,
        msg_type: str,
        durable: str,
        *,
        queue_group: str | None = None,
        ack_wait: float = 30.0,
        max_deliver: int = 3,
        max_ack_pending: int = 100,
    ) -> None:
        """Registra un consumer durable con ack manual tras el procesamiento.

        Los callbacks de nats-py corren en el event loop del transporte. Solo
        encolan aquí: los workers se ejecutan en el hilo del runner para que
        puedan publicar en el mismo bus sin bloquear su event loop.
        """
        if msg_type not in REGISTRY:
            raise ValueError(f"tipo de mensaje sin contrato: {msg_type}")
        if not durable or any(ch.isspace() for ch in durable):
            raise ValueError("durable debe ser un nombre NATS no vacío y sin espacios")
        from nats.js.api import AckPolicy, ConsumerConfig, DeliverPolicy

        async def _subscribe() -> None:
            async def cb(msg: Any) -> None:
                self._deliveries.put(NatsDelivery(envelope_from_json(msg.data), msg))

            config = ConsumerConfig(
                durable_name=durable,
                filter_subject=msg_type,
                ack_policy=AckPolicy.EXPLICIT,
                deliver_policy=DeliverPolicy.NEW,
                ack_wait=ack_wait,
                max_deliver=max_deliver,
                max_ack_pending=max_ack_pending,
                deliver_group=queue_group,
            )
            subscription = await self._js.subscribe(
                msg_type,
                queue=queue_group,
                cb=cb,
                durable=durable,
                stream=self._stream,
                config=config,
                manual_ack=True,
            )
            self._subscriptions.append(subscription)

        self._run_coro(_subscribe())

    def subscribe_durable_many(
        self,
        msg_types: list[str],
        durable: str,
        *,
        ack_wait: float = 30.0,
        max_deliver: int = 3,
        max_ack_pending: int = 100,
    ) -> None:
        """Consumer queue compartido con un durable y varios filtros de subject."""
        subjects = sorted(set(msg_types))
        if not subjects or any(msg_type not in REGISTRY for msg_type in subjects):
            raise ValueError("todos los subjects requieren contrato registrado")
        if not durable or any(ch.isspace() for ch in durable):
            raise ValueError("durable debe ser un nombre NATS no vacío y sin espacios")
        from nats.js.api import AckPolicy, ConsumerConfig, DeliverPolicy

        async def _subscribe() -> None:
            async def cb(msg: Any) -> None:
                self._deliveries.put(NatsDelivery(envelope_from_json(msg.data), msg))

            config = ConsumerConfig(
                durable_name=durable,
                filter_subjects=subjects,
                ack_policy=AckPolicy.EXPLICIT,
                deliver_policy=DeliverPolicy.NEW,
                ack_wait=ack_wait,
                max_deliver=max_deliver,
                max_ack_pending=max_ack_pending,
                deliver_group=durable,
            )
            subscription = await self._js.subscribe(
                subjects[0],
                queue=durable,
                cb=cb,
                durable=durable,
                stream=self._stream,
                config=config,
                manual_ack=True,
            )
            self._subscriptions.append(subscription)

        self._run_coro(_subscribe())

    def next_delivery(self, timeout: float | None = None) -> NatsDelivery:
        """Espera una entrega durable; el ack/nak queda bajo control del runner."""
        try:
            return self._deliveries.get(timeout=timeout)
        except queue.Empty as exc:
            raise TimeoutError("no hay entregas disponibles") from exc

    def ack(self, delivery: NatsDelivery) -> None:
        self._run_coro(delivery.message.ack())

    def in_progress(self, delivery: NatsDelivery) -> None:
        self._run_coro(delivery.message.in_progress())

    def nak(self, delivery: NatsDelivery, delay: float = 1.0) -> None:
        self._run_coro(delivery.message.nak(delay=delay))

    def term(self, delivery: NatsDelivery) -> None:
        self._run_coro(delivery.message.term())

    # -- utilidades -------------------------------------------------------------------

    def _run_coro(self, coro: Any) -> Any:
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result(timeout=self._timeout)
