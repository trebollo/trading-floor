"""Tests de integración con infraestructura real (NATS y Postgres).

Los tests de infra se saltan solos si los servicios no están disponibles. En local:

```bash
uv run pytest -q                # todo (los de infra corren con Docker levantado)
uv run pytest -q -m infra       # solo la integración con NATS/Postgres
```
"""

import socket

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

    def test_invalid_payload_never_reaches_nats(self):
        from tf.bus_nats import NatsBus
        from tf.contracts import MessageValidationError

        bus = NatsBus().start()
        try:
            with pytest.raises(MessageValidationError):
                bus.publish_raw("backtest.report.v1", {"verdict": "IMPOSIBLE"}, actor=Actor(agent="a", role="r", department="d"))
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


def PostgresAuditLog_DDL(table: str) -> str:
    from tf.audit_pg import DDL

    return DDL.format(table=table)
