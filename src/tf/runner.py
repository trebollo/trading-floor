"""Ejecución residente de un departamento sobre consumers durables de JetStream.

El runner no crea agentes ni añade lógica de negocio: recibe un ``AgentHost``
configurado por el composition root del departamento. Sus handlers se ejecutan
fuera del event loop de nats-py y la entrega solo se ackea tras procesar y
publicar sus salidas.
"""

from __future__ import annotations

import threading
import time
from importlib import import_module
from typing import Any, Callable

from tf.bus_nats import NatsBus, NatsDelivery
from tf.contracts import Actor
from tf.host import AgentHost
from tf.outbox import OutboxPublishingBus, PostgresOutbox


class DepartmentRunner:
    """Consume mensajes tipados para un departamento hasta solicitar parada."""

    def __init__(
        self,
        department: str,
        host: AgentHost,
        bus: NatsBus,
        subscriptions: list[str],
        *,
        max_deliver: int = 3,
        ack_wait: float = 30.0,
        max_ack_pending: int = 100,
        queue_group: str | None = None,
        heartbeat_seconds: float = 10.0,
        inbox: Any | None = None,
        outbox: PostgresOutbox | None = None,
    ) -> None:
        if not department or not subscriptions:
            raise ValueError("department y al menos una suscripción son obligatorios")
        if max_deliver < 1:
            raise ValueError("max_deliver debe ser ≥ 1")
        self.department = department
        self.host = host
        self.bus = bus
        self.subscriptions = sorted(set(subscriptions))
        self.max_deliver = max_deliver
        self.ack_wait = ack_wait
        self.max_ack_pending = max_ack_pending
        self.queue_group = queue_group
        self.heartbeat_seconds = heartbeat_seconds
        self.inbox = inbox
        self.outbox = outbox
        self._started = False
        self.stats = {"processed": 0, "duplicates": 0, "retried": 0, "dead_lettered": 0}

    def start(self) -> None:
        """Crea un durable filtrado por cada contrato que consume el departamento."""
        msg_types = sorted(set(self.subscriptions) | {"runner.probe.v1"})
        if self.queue_group:
            # One JetStream durable serves all subjects from the department's
            # replicas through the same queue group.
            durable = f"tf-{self.department}-{self.queue_group}"
            self.bus.subscribe_durable_many(
                msg_types,
                durable,
                ack_wait=self.ack_wait,
                max_deliver=self.max_deliver,
                max_ack_pending=self.max_ack_pending,
            )
        else:
            for msg_type in msg_types:
                durable = f"tf-{self.department}-{msg_type}".replace(".", "-")
                self.bus.subscribe_durable(
                    msg_type,
                    durable,
                    ack_wait=self.ack_wait,
                    max_deliver=self.max_deliver,
                    max_ack_pending=self.max_ack_pending,
                )
        self._started = True

    def run_forever(self, stop: threading.Event | None = None) -> dict[str, int]:
        """Arranca consumers y sirve entregas; ``stop`` habilita SIGTERM limpio."""
        stop = stop or threading.Event()
        if not self._started:
            self.start()
        next_heartbeat = 0.0
        actor = Actor(agent=f"{self.department}-runner", role="platform", department=self.department)
        while not stop.is_set():
            if self.outbox is not None:
                self.outbox.publish_pending(self.bus)
            now = time.monotonic()
            if now >= next_heartbeat:
                self.bus.publish_raw(
                    "agent.heartbeat.v1",
                    {
                        "agent": actor.agent,
                        "department": self.department,
                        "status": "up",
                        "subscriptions": self.subscriptions,
                    },
                    actor=actor,
                )
                next_heartbeat = now + self.heartbeat_seconds
            try:
                delivery = self.bus.next_delivery(timeout=min(1.0, max(0.01, next_heartbeat - time.monotonic())))
            except TimeoutError:
                continue
            self._process(delivery)
        return dict(self.stats)

    def process_one(self, delivery: NatsDelivery) -> None:
        """Procesa una entrega; público para pruebas y ejecución supervisada."""
        if not self._started:
            raise RuntimeError("el runner debe iniciarse antes de procesar entregas")
        self._process(delivery)

    def _process(self, delivery: NatsDelivery) -> None:
        if delivery.envelope.type == "runner.probe.v1":
            self._answer_probe(delivery)
            return
        if self.inbox is not None:
            lock_key = f"runner-inbox/{self.department}/{delivery.envelope.id}"
            with self.inbox.lock(lock_key):
                self._process_with_inbox(delivery)
            return
        self._process_delivery(delivery)

    def _answer_probe(self, delivery: NatsDelivery) -> None:
        probe_id = delivery.envelope.payload["probe_id"]
        self.bus.publish_raw(
            "runner.ready.v1",
            {"probe_id": probe_id, "department": self.department,
             "status": "up", "subscriptions": self.subscriptions},
            actor=Actor(agent=f"{self.department}-runner", role="platform", department=self.department),
            id=f"runner-ready-{self.department}-{probe_id}",
            causation_id=delivery.envelope.id,
            correlation_id=probe_id,
        )
        self.bus.ack(delivery)

    def _process_with_inbox(self, delivery: NatsDelivery) -> None:
        if self.inbox.completed(self.department, delivery.envelope.id):
            self.bus.ack(delivery)
            self.stats["duplicates"] += 1
            return
        self._process_delivery(delivery)

    def _process_delivery(self, delivery: NatsDelivery) -> None:
        try:
            result = self._process_with_ack_extensions(delivery)
        except Exception as exc:
            if delivery.num_delivered >= self.max_deliver:
                self._publish_dead_letter(delivery, exc)
                if self.inbox is not None:
                    self.inbox.mark_completed(self.department, delivery.envelope.id)
                self.bus.ack(delivery)
                self.stats["dead_lettered"] += 1
            else:
                self.bus.nak(delivery, delay=min(2 ** (delivery.num_delivered - 1), 30))
                self.stats["retried"] += 1
            return
        if self.inbox is not None:
            self.inbox.mark_completed(self.department, delivery.envelope.id)
        self.bus.ack(delivery)
        if result["duplicate"]:
            self.stats["duplicates"] += 1
        else:
            self.stats["processed"] += 1

    def _process_with_ack_extensions(self, delivery: NatsDelivery) -> dict[str, Any]:
        """Renueva el ack wait de JetStream durante trabajos largos de backtest."""
        progress = getattr(self.bus, "in_progress", None)
        if progress is None or self.ack_wait < 3:
            return self.host.process(delivery.envelope)
        stop = threading.Event()

        def extend() -> None:
            while not stop.wait(max(1.0, self.ack_wait / 3)):
                try:
                    progress(delivery)
                except Exception as exc:
                    self.host.audit.append(
                        actor=f"{self.department}-runner",
                        event_type="bus.ack_extension_failed",
                        payload={"envelope_id": delivery.envelope.id,
                                 "error": f"{type(exc).__name__}: {exc}"},
                    )

        thread = threading.Thread(target=extend, name=f"{self.department}-ack", daemon=True)
        thread.start()
        try:
            return self.host.process(delivery.envelope)
        finally:
            stop.set()
            thread.join(timeout=1.0)

    def _publish_dead_letter(self, delivery: NatsDelivery, error: Exception) -> None:
        """Persiste el mensaje fallido en el stream antes de ackear el original."""
        envelope = delivery.envelope
        self.bus.publish_raw(
            "ops.dead_letter.v1",
            {
                "department": self.department,
                "original_type": envelope.type,
                "original_id": envelope.id,
                "original_envelope": envelope.model_dump(mode="json"),
                "delivery_count": delivery.num_delivered,
                "error": f"{type(error).__name__}: {error}",
            },
            actor=Actor(agent=f"{self.department}-runner", role="platform", department=self.department),
            id=f"dlq-{envelope.id}",
            causation_id=envelope.id,
            correlation_id=envelope.correlation_id,
        )
        self.host.audit.append(
            actor=f"{self.department}-runner",
            event_type="bus.dead_lettered",
            payload={"type": envelope.type, "envelope_id": envelope.id,
                     "delivery_count": delivery.num_delivered, "error": f"{type(error).__name__}: {error}"},
        )


def _load_factory(path: str) -> Callable[..., Any]:
    module_name, separator, attribute = path.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError("factory debe tener formato 'paquete.modulo:funcion'")
    factory = getattr(import_module(module_name), attribute)
    if not callable(factory):
        raise TypeError(f"{path} no es invocable")
    return factory


def main() -> None:
    """Arranque de contenedor: ``python -m tf.runner --department ...``.

    Cada departamento aporta una factory ``(bus, audit, department, state_store)``
    que devuelve ``(workers, msg_types)``. No hay fallback a SQLite ni a InMemoryBus.
    """
    import argparse
    import os
    import signal
    from datetime import datetime, timedelta, timezone

    parser = argparse.ArgumentParser(description="Worker residente de un departamento")
    parser.add_argument("--department", required=True)
    parser.add_argument("--factory", default=os.getenv("TF_RUNNER_FACTORY"), required=os.getenv("TF_RUNNER_FACTORY") is None)
    parser.add_argument("--queue-group", default=os.getenv("TF_QUEUE_GROUP"))
    args = parser.parse_args()

    dsn = os.getenv("TF_DATABASE_URL")
    if not dsn:
        raise SystemExit("TF_DATABASE_URL es obligatorio para un runner durable")
    servers = [part.strip() for part in os.getenv("TF_NATS_URL", "nats://nats:4222").split(",") if part.strip()]

    from tf.audit_pg import PostgresAuditLog
    from tf.state_pg import PostgresStateStore

    audit = PostgresAuditLog(dsn=dsn)
    if not audit.verify():
        audit._conn.close()
        raise SystemExit("la cadena de auditoría PostgreSQL no verifica; runner no inicia")

    bus = NatsBus(servers=servers).start()
    state_store = PostgresStateStore(dsn=dsn)
    inbox = state_store.inbox()
    inbox.purge_before((datetime.now(timezone.utc) - timedelta(days=30)).isoformat())
    outbox = PostgresOutbox(state_store._conn, args.department)
    agent_bus = OutboxPublishingBus(bus, outbox)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    try:
        definition = _load_factory(args.factory)(agent_bus, audit, args.department, state_store)
        if not isinstance(definition, tuple) or len(definition) != 2:
            raise TypeError("la factory debe devolver (workers, msg_types)")
        workers, msg_types = definition
        if not isinstance(workers, dict) or not isinstance(msg_types, dict):
            raise TypeError("workers y msg_types deben ser diccionarios")
        subscriptions = sorted({msg for types in msg_types.values() for msg in types})
        host = AgentHost(agent_bus, audit, actor=f"{args.department}-host")
        host.register(args.department, workers, msg_types, subscribe=False)
        runner = DepartmentRunner(
            args.department,
            host,
            bus,
            subscriptions,
            max_deliver=int(os.getenv("TF_MAX_DELIVER", "3")),
            ack_wait=float(os.getenv("TF_ACK_WAIT_SECONDS", "30")),
            max_ack_pending=int(os.getenv("TF_MAX_ACK_PENDING", "100")),
            queue_group=args.queue_group,
            inbox=inbox,
            outbox=outbox,
        )
        print(f"runner {args.department} listo; suscripciones: {', '.join(subscriptions)}", flush=True)
        runner.run_forever(stop)
    finally:
        bus.close()
        state_store.close()
        audit._conn.close()


if __name__ == "__main__":
    main()
