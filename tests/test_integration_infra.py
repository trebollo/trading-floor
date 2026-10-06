"""Tests de integración con infraestructura real (NATS y Postgres).

Los tests de infra se saltan solos si los servicios no están disponibles. En local:

```bash
uv run pytest -q                # todo (los de infra corren con Docker levantado)
uv run pytest -q -m infra       # solo la integración con NATS/Postgres
```
"""

import socket
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from tf.contracts import Actor


def _port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


NATS_UP = _port_open("localhost", 4222)
PG_UP = _port_open("localhost", 5432)

requires_nats = pytest.mark.skipif(not NATS_UP, reason="NATS no disponible (docker compose up -d en local)")
requires_pg = pytest.mark.skipif(not PG_UP, reason="Postgres no disponible (docker compose up -d en local)")


# ---------------------------------------------------------------------------
# NatsBus
# ---------------------------------------------------------------------------


@requires_nats
@pytest.mark.infra
class TestNatsBus:
    def test_roundtrip_with_handler(self):
        from tf.bus_nats import NatsBus

        bus = NatsBus().start()
        try:
            received = []
            bus.subscribe("agent.heartbeat.v1", lambda env: received.append(env))
            import time

            deadline = time.time() + 5
            sent = 0
            while not received and time.time() < deadline:
                sent += 1
                bus.publish_raw(
                    "agent.heartbeat.v1",
                    {"agent": "nats-test", "department": "platform", "status": "up"},
                    actor=Actor(agent="nats-test", role="test", department="platform"),
                )
                time.sleep(0.2)
            assert received, "el mensaje no llegó por JetStream"
            assert received[0].payload["agent"] == "nats-test"
            assert received[0].actor.role == "test"
        finally:
            bus.close()

    def test_ephemeral_subscription_does_not_replay_old_cycle_messages(self):
        from tf.bus_nats import NatsBus

        bus = NatsBus().start()
        actor = Actor(agent="ephemeral-test", role="test", department="platform")
        received = []
        try:
            bus.publish_raw(
                "agent.heartbeat.v1",
                {"agent": "old-cycle", "department": "platform", "status": "up"},
                actor=actor,
            )
            bus.subscribe("agent.heartbeat.v1", received.append)
            import time

            time.sleep(0.2)
            assert not any(env.payload.get("agent") == "old-cycle" for env in received)
            sent = bus.publish_raw(
                "agent.heartbeat.v1",
                {"agent": "new-cycle", "department": "platform", "status": "up"},
                actor=actor,
            )
            deadline = time.time() + 5
            while not any(env.id == sent.id for env in received) and time.time() < deadline:
                time.sleep(0.02)
            assert sum(env.id == sent.id for env in received) == 1
        finally:
            bus.close()

    def test_invalid_payload_never_reaches_nats(self):
        from tf.bus_nats import NatsBus
        from tf.contracts import MessageValidationError

        bus = NatsBus().start()
        try:
            with pytest.raises(MessageValidationError):
                bus.publish_raw("backtest.report.v1", {"verdict": "IMPOSIBLE"}, actor=Actor(agent="a", role="r", department="d"))
        finally:
            bus.close()

    def test_durable_consumer_requires_explicit_ack(self):
        from tf.bus_nats import NatsBus

        bus = NatsBus().start()
        durable = f"infra-test-{uuid.uuid4().hex[:10]}"
        try:
            bus.subscribe_durable("agent.heartbeat.v1", durable, ack_wait=5, max_deliver=2)
            sent = bus.publish_raw(
                "agent.heartbeat.v1",
                {"agent": "durable-test", "department": "platform", "status": "up"},
                actor=Actor(agent="durable-test", role="test", department="platform"),
            )
            delivery = bus.next_delivery(timeout=5)
            assert delivery.envelope.id == sent.id
            assert delivery.num_delivered == 1
            bus.ack(delivery)
        finally:
            bus.close()

    def test_queue_consumer_shares_one_durable_across_subjects(self):
        from tf.bus_nats import NatsBus

        bus = NatsBus().start()
        durable = f"infra-queue-{uuid.uuid4().hex[:10]}"
        actor = Actor(agent="queue-test", role="test", department="platform")
        subjects = ["agent.heartbeat.v1", "cycle.trigger.v1"]
        payloads = [
            {"agent": "queue-test", "department": "platform", "status": "up"},
            {"cycle_id": "queue-test", "cycle_date": "2026-10-06",
             "market_data_uri": "/tmp/data.csv", "market_data_sha256": "0" * 64},
        ]
        try:
            bus.subscribe_durable_many(subjects, durable, ack_wait=5, max_deliver=2)
            sent = [bus.publish_raw(subject, payload, actor=actor) for subject, payload in zip(subjects, payloads)]
            received = {}
            deadline = time.time() + 5
            while len(received) < len(subjects) and time.time() < deadline:
                delivery = bus.next_delivery(timeout=1)
                received[delivery.envelope.type] = delivery
                bus.ack(delivery)
            assert set(received) == set(subjects)
            assert {delivery.envelope.id for delivery in received.values()} == {env.id for env in sent}
        finally:
            bus.close()

    def test_dead_letter_contract_is_validated_by_jetstream(self):
        from tf.bus_nats import NatsBus

        bus = NatsBus().start()
        try:
            env = bus.publish_raw(
                "ops.dead_letter.v1",
                {
                    "department": "research",
                    "original_type": "agent.heartbeat.v1",
                    "original_id": "event-1",
                    "original_envelope": {"id": "event-1"},
                    "delivery_count": 3,
                    "error": "RuntimeError: failed",
                },
                actor=Actor(agent="research-runner", role="platform", department="research"),
            )
            assert env.type == "ops.dead_letter.v1"
        finally:
            bus.close()


# ---------------------------------------------------------------------------
# PostgresAuditLog
# ---------------------------------------------------------------------------


@requires_pg
@pytest.mark.infra
class TestPostgresAuditLog:
    TEST_TABLE = "audit_log_test"

    def test_chain_append_verify_and_tamper_detection(self):
        from tf.audit_pg import PostgresAuditLog

        log = PostgresAuditLog(table=self.TEST_TABLE)
        try:
            log.drop()  # empezar limpio
            log._conn.execute(PostgresAuditLog_DDL(self.TEST_TABLE))
            a1 = log.append(actor="test", event_type="e1", payload={"n": 1})
            a2 = log.append(actor="test", event_type="e2", payload={"n": 2})
            assert a2.seq == a1.seq + 1 and a2.prev_hash == a1.hash
            assert log.verify()

            # Manipulación: editar un payload rompe la cadena.
            log._conn.execute(
                f"UPDATE {self.TEST_TABLE} SET payload = payload || '{{\"n\": 999}}' WHERE seq = %s",
                (a1.seq,),
            )
            assert not log.verify()
        finally:
            log.drop()
            log._conn.close()

    def test_concurrent_writers_keep_a_single_hash_chain(self):
        from tf.audit_pg import PostgresAuditLog

        table = "audit_log_concurrent_test"
        setup = PostgresAuditLog(table=table)
        setup.drop()
        setup._conn.execute(PostgresAuditLog_DDL(table))
        setup._conn.close()

        def append(index: int) -> None:
            log = PostgresAuditLog(table=table)
            try:
                log.append("parallel-test", "parallel.append", {"index": index})
            finally:
                log._conn.close()

        try:
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(append, range(32)))
            verify = PostgresAuditLog(table=table)
            try:
                assert len(verify.entries()) == 32
                assert verify.verify()
            finally:
                verify.drop()
                verify._conn.close()
        finally:
            cleanup = PostgresAuditLog(table=table)
            cleanup.drop()
            cleanup._conn.close()


@requires_pg
@pytest.mark.infra
class TestPostgresStateStore:
    def test_state_survives_new_store_and_mutations_are_atomic(self):
        from concurrent.futures import ThreadPoolExecutor

        from tf.state_pg import PostgresStateStore

        key = f"infra-test/{uuid.uuid4().hex}"
        store = PostgresStateStore()
        try:
            store.set(key, {"count": 0})

            def increment(_: int) -> None:
                connection = PostgresStateStore()
                try:
                    connection.mutate(key, lambda value: {"count": value["count"] + 1})
                finally:
                    connection.close()

            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(increment, range(40)))
            restarted = PostgresStateStore()
            try:
                assert restarted.get(key) == {"count": 40}
            finally:
                restarted.close()
        finally:
            store.delete(key)
            store.close()

    def test_postgres_governor_shares_call_reservations_and_token_usage(self):
        from tf.audit import SqliteAuditLog
        from tf.budget import BudgetExceeded, BudgetLimits, CostGovernor
        from tf.state_pg import PostgresStateStore

        key = f"infra-test/budget/{uuid.uuid4().hex}"
        store = PostgresStateStore()
        limits = BudgetLimits(default_tokens_per_day=100, calls_per_hour=2, global_eur_per_day=10.0)
        try:
            first = CostGovernor(limits, state_store=store, state_key=key, audit=SqliteAuditLog(), now=1_800_000_000)
            first.check("agent-a")
            first.record("agent-a", 10, 5, cost_usd=0.25)

            second = CostGovernor(limits, state_store=store, state_key=key, audit=SqliteAuditLog(), now=1_800_000_000)
            assert second.usage()["agents"]["agent-a"]["tokens"] == 15
            second.check("agent-a")
            second.record("agent-a", 5, 0, cost_usd=0.10)
            with pytest.raises(BudgetExceeded):
                CostGovernor(limits, state_store=store, state_key=key, now=1_800_000_000).check("agent-a")
        finally:
            store.delete(key)
            store.close()

    def test_runner_inbox_survives_process_restart(self):
        from tf.state_pg import PostgresStateStore

        department, envelope_id = f"test-{uuid.uuid4().hex}", str(uuid.uuid4())
        first = PostgresStateStore()
        try:
            inbox = first.inbox()
            assert not inbox.completed(department, envelope_id)
            inbox.mark_completed(department, envelope_id)
        finally:
            first.close()

        second = PostgresStateStore()
        try:
            assert second.inbox().completed(department, envelope_id)
            second._conn.execute(
                "DELETE FROM tf_inbox WHERE department = %s AND envelope_id = %s",
                (department, envelope_id),
            )
        finally:
            second.close()

    def test_postgres_memory_replay_is_idempotent_for_same_event(self):
        from tf.memory import PostgresMemoryStore
        from tf.state_pg import PostgresStateStore

        key = f"infra-test/memory/{uuid.uuid4().hex}"
        store = PostgresStateStore()
        memory = PostgresMemoryStore(store, key=key)
        spec = {"type": "sma_cross", "params": {"fast_window": 10, "slow_window": 30}}
        try:
            first = memory.add_evaluation(
                "spec-1", "backtest", "RECHAZAR", "falló", spec=spec,
                record_id="event-backtest-1",
            )
            replay = memory.add_evaluation(
                "spec-1", "backtest", "RECHAZAR", "falló", spec=spec,
                record_id="event-backtest-1",
            )
            memory.add_lesson("sma_cross falla en régimen adverso", source_evaluation_id=first.id)
            memory.add_lesson("sma_cross falla en régimen adverso", source_evaluation_id=first.id)

            assert replay.id == first.id
            assert len(memory.evaluations) == 1
            assert len(memory.lessons) == 1
            assert memory.lessons[0].times_referenced == 0
        finally:
            store.delete(key)
            store.close()


def PostgresAuditLog_DDL(table: str) -> str:
    from tf.audit_pg import DDL

    return DDL.format(table=table)
