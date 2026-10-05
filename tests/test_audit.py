"""Tests del audit log: cadena de hash a prueba de manipulación."""

import json

import pytest

from tf.audit import SqliteAuditLog, entry_hash


def test_chain_verifies_after_multiple_appends():
    log = SqliteAuditLog()
    for i in range(10):
        log.append(actor=f"agent-{i % 3}", event_type="test.event", payload={"i": i})
    assert log.verify()
    assert len(log.entries()) == 10


def test_tampering_with_payload_breaks_chain():
    log = SqliteAuditLog(":memory:")
    log.append(actor="a", event_type="t", payload={"x": 1})
    log.append(actor="a", event_type="t", payload={"x": 2})
    assert log.verify()

    # Manipulación directa de la base: cambiar un payload registrado.
    log._conn.execute(
        "UPDATE audit_log SET payload = ? WHERE seq = 1", (json.dumps({"x": 999}),)
    )
    assert not log.verify()


def test_tampering_with_deletion_breaks_chain():
    log = SqliteAuditLog()
    log.append(actor="a", event_type="t", payload={})
    log.append(actor="b", event_type="t", payload={})
    log._conn.execute("DELETE FROM audit_log WHERE seq = 1")
    entries = log.entries()
    assert len(entries) == 1
    # El hash previo guardado ya no coincide con la cadena reconstruida.
    assert not log.verify()


def test_hash_is_deterministic_and_order_sensitive():
    h1 = entry_hash("", "2026-01-01", "a", "t", {"x": 1})
    h2 = entry_hash("", "2026-01-01", "a", "t", {"x": 1})
    h3 = entry_hash("", "2026-01-01", "a", "t", {"x": 2})
    assert h1 == h2
    assert h1 != h3
