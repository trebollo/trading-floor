from __future__ import annotations

import pytest

from tf.audit import SqliteAuditLog
from tf.bus import InMemoryBus
from tf.bus_nats import NatsDelivery
from tf.contracts import Actor, Envelope
from tf.host import AgentHost
from tf.runner import DepartmentRunner


class _Message:
    def __init__(self, num_delivered: int = 1) -> None:
        self.metadata = type("Metadata", (), {"num_delivered": num_delivered})()
        self.acked = False
        self.nak_delay = None
        self.termed = False

    async def ack(self) -> None:
        self.acked = True

    async def nak(self, delay: float = 0) -> None:
        self.nak_delay = delay

    async def term(self) -> None:
        self.termed = True


class _FakeNatsBus:
    def __init__(self) -> None:
        self.published = InMemoryBus()
        self.acks: list[NatsDelivery] = []
        self.naks: list[tuple[NatsDelivery, float]] = []
        self.subscriptions: list[tuple[str, str]] = []
        self.multi_subscriptions: list[tuple[list[str], str]] = []

    def subscribe_durable(self, msg_type: str, durable: str, **kwargs) -> None:
        self.subscriptions.append((msg_type, durable))

    def subscribe_durable_many(self, msg_types: list[str], durable: str, **kwargs) -> None:
        self.multi_subscriptions.append((msg_types, durable))

    def ack(self, delivery: NatsDelivery) -> None:
        self.acks.append(delivery)

    def nak(self, delivery: NatsDelivery, delay: float = 1) -> None:
        self.naks.append((delivery, delay))

    def publish_raw(self, *args, **kwargs):
        return self.published.publish_raw(*args, **kwargs)


def _delivery(num_delivered: int = 1, msg_type: str = "agent.heartbeat.v1", payload: dict | None = None) -> NatsDelivery:
    return NatsDelivery(
        Envelope(
            type=msg_type,
            payload=payload or {"agent": "test", "department": "research", "status": "up"},
            actor=Actor(agent="test", role="test", department="research"),
        ),
        _Message(num_delivered),
    )


def test_runner_registers_durable_and_acks_after_success() -> None:
    audit = SqliteAuditLog()
    transport = _FakeNatsBus()
    host = AgentHost(InMemoryBus(), audit)
    received = []
    host.register("research", {"worker": lambda env: received.append(env)},
                  {"worker": ["agent.heartbeat.v1"]}, subscribe=False)
    runner = DepartmentRunner("research", host, transport, ["agent.heartbeat.v1"])

    runner.start()
    delivery = _delivery()
    runner.process_one(delivery)

    assert transport.subscriptions == [
        ("agent.heartbeat.v1", "tf-research-agent-heartbeat-v1"),
        ("runner.probe.v1", "tf-research-runner-probe-v1"),
    ]
    assert received == [delivery.envelope]
    assert transport.acks == [delivery]
    assert runner.stats["processed"] == 1


def test_runner_probe_returns_readiness_without_dispatching_to_worker() -> None:
    audit = SqliteAuditLog()
    transport = _FakeNatsBus()
    host = AgentHost(InMemoryBus(), audit)
    runner = DepartmentRunner("research", host, transport, ["agent.heartbeat.v1"])
    runner.start()
    delivery = _delivery(msg_type="runner.probe.v1", payload={"probe_id": "probe-1"})

    runner.process_one(delivery)

    ready = transport.published.published[-1]
    assert ready.type == "runner.ready.v1"
    assert ready.payload["department"] == "research"
    assert ready.payload["probe_id"] == "probe-1"
    assert transport.acks == [delivery]


def test_runner_uses_one_multisubject_durable_for_department_replicas() -> None:
    audit = SqliteAuditLog()
    transport = _FakeNatsBus()
    host = AgentHost(InMemoryBus(), audit)
    host.register("backtest", {"worker": lambda env: None},
                  {"worker": ["strategy.spec.v1"]}, subscribe=False)
    runner = DepartmentRunner(
        "backtest", host, transport, ["strategy.spec.v1"], queue_group="batch"
    )

    runner.start()

    assert transport.multi_subscriptions == [(
        ["runner.probe.v1", "strategy.spec.v1"], "tf-backtest-batch"
    )]
    assert transport.subscriptions == []


def test_runner_naks_failed_delivery_until_retry_limit() -> None:
    audit = SqliteAuditLog()
    transport = _FakeNatsBus()
    host = AgentHost(InMemoryBus(), audit)

    def broken(_env):
        raise RuntimeError("fallo de prueba")

    host.register("research", {"worker": broken},
                  {"worker": ["agent.heartbeat.v1"]}, subscribe=False)
    runner = DepartmentRunner("research", host, transport, ["agent.heartbeat.v1"], max_deliver=3)
    runner.start()

    first = _delivery(1)
    runner.process_one(first)
    assert transport.naks == [(first, 1)]
    assert transport.acks == []


def test_runner_publishes_dead_letter_before_ack_on_final_failure() -> None:
    audit = SqliteAuditLog()
    transport = _FakeNatsBus()
    host = AgentHost(InMemoryBus(), audit)
    host.register("research", {"worker": lambda _env: (_ for _ in ()).throw(ValueError("poison"))},
                  {"worker": ["agent.heartbeat.v1"]}, subscribe=False)
    runner = DepartmentRunner("research", host, transport, ["agent.heartbeat.v1"], max_deliver=3)
    runner.start()
    delivery = _delivery(3)

    runner.process_one(delivery)

    assert transport.published.published[-1].type == "ops.dead_letter.v1"
    assert transport.published.published[-1].payload["original_id"] == delivery.envelope.id
    assert transport.acks == [delivery]
    assert runner.stats["dead_lettered"] == 1
