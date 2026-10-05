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
import threading
from collections import defaultdict
from typing import Any

from tf.bus import BaseBus, Handler
from tf.contracts import REGISTRY, Envelope, validate_payload


def envelope_to_json(envelope: Envelope) -> bytes:
    return json.dumps(envelope.model_dump(mode="json"), default=str).encode()


def envelope_from_json(raw: bytes) -> Envelope:
    return Envelope.model_validate_json(raw)


class NatsBus(BaseBus):
    def __init__(self, servers: list[str] | None = None, stream: str = "TF", timeout: float = 10.0) -> None:
        self._servers = servers or ["nats://localhost:4222"]
        self._stream = stream
        self._timeout = timeout
        self._handlers: dict[str, list[Handler]] = defaultdict(list)
        self._loop = asyncio.new_event_loop()
        self._thread: threading.Thread | None = None
        self._nc = None
        self._js = None

    # -- ciclo de vida ------------------------------------------------------------

    def start(self) -> "NatsBus":
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        self._run_coro(self._connect())
        return self

    async def _connect(self) -> None:
        import nats  # import diferido: solo requiere el paquete si se usa

        self._nc = await nats.connect(servers=self._servers, connect_timeout=self._timeout)
        self._js = self._nc.jetstream()
        from nats.js.api import StreamConfig

        # El subject global ">" exige no_ack=True en JetStream (err 10052); en su lugar
        # declaramos los subjects concretos del registro de contratos.
        try:
            await self._js.add_stream(
                StreamConfig(name=self._stream, subjects=sorted(REGISTRY.keys()))
            )
        except Exception as first_error:
            if not await self._stream_exists():
                raise RuntimeError(
                    f"No se pudo crear el stream JetStream '{self._stream}': {first_error}"
                ) from first_error

    async def _stream_exists(self) -> bool:
        try:
            await self._js.stream_info(self._stream)
            return True
        except Exception:
            return False

    def close(self) -> None:
        if self._nc is not None:
            self._run_coro(self._nc.close())
        self._loop.call_soon_threadsafe(self._loop.stop)

    # -- BaseBus --------------------------------------------------------------------

    def publish(self, envelope: Envelope) -> None:
        # G2: la misma validación en el borde que el bus en memoria.
        validate_payload(envelope.type, envelope.payload)
        # stream explícito: sin búsqueda por subject que pueda fallar.
        self._run_coro(self._js.publish(envelope.type, envelope_to_json(envelope), stream=self._stream))

    def subscribe(self, msg_type: str, handler: Handler) -> None:
        self._handlers[msg_type].append(handler)

        async def _subscribe() -> None:
            async def cb(msg: Any) -> None:
                envelope = envelope_from_json(msg.data)
                for h in self._handlers.get(envelope.type, []):
                    h(envelope)

            await self._js.subscribe(msg_type, cb=cb, stream=self._stream)

        self._run_coro(_subscribe())

    # -- utilidades -------------------------------------------------------------------

    def _run_coro(self, coro: Any) -> Any:
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result(timeout=self._timeout)
