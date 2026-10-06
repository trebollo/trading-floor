"""Outbox Postgres→JetStream para publicar salidas de workers de forma durable."""

from __future__ import annotations

import json
from typing import Any

from tf.bus import BaseBus, Handler
from tf.contracts import Envelope, validate_payload

OUTBOX_DDL = """
CREATE TABLE IF NOT EXISTS tf_outbox (
    event_id TEXT PRIMARY KEY,
    department TEXT NOT NULL,
    subject TEXT NOT NULL,
    envelope JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at TIMESTAMPTZ,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT
)
"""


class PostgresOutbox:
    """Registro append-only de envelopes pendientes con deduplicación por id."""

    def __init__(self, connection: Any, department: str) -> None:
        self._conn = connection
        self.department = department
        self._conn.execute(OUTBOX_DDL)

    def enqueue(self, envelope: Envelope) -> None:
        validate_payload(envelope.type, envelope.payload)
        encoded = json.dumps(envelope.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        self._conn.execute(
            "INSERT INTO tf_outbox (event_id, department, subject, envelope) "
            "VALUES (%s, %s, %s, %s::jsonb) ON CONFLICT (event_id) DO NOTHING",
            (envelope.id, self.department, envelope.type, encoded),
        )

    def pending(self, limit: int = 100) -> list[Envelope]:
        rows = self._conn.execute(
            "SELECT envelope FROM tf_outbox WHERE department = %s AND published_at IS NULL "
            "ORDER BY created_at, event_id LIMIT %s",
            (self.department, limit),
        ).fetchall()
        return [Envelope.model_validate(row[0]) for row in rows]

    def mark_published(self, event_id: str) -> None:
        self._conn.execute(
            "UPDATE tf_outbox SET published_at = now(), last_error = NULL WHERE event_id = %s",
            (event_id,),
        )

    def note_failure(self, event_id: str, error: Exception) -> None:
        self._conn.execute(
            "UPDATE tf_outbox SET attempts = attempts + 1, last_error = %s WHERE event_id = %s",
            (f"{type(error).__name__}: {error}"[:1000], event_id),
        )

    def publish_pending(self, bus: Any, limit: int = 100) -> int:
        """Publica en orden; el ack del outbox ocurre solo tras el PubAck de JetStream."""
        published = 0
        for envelope in self.pending(limit):
            try:
                bus.publish(envelope)
                self.mark_published(envelope.id)
                published += 1
            except Exception as exc:
                self.note_failure(envelope.id, exc)
                break
        return published


class OutboxPublishingBus(BaseBus):
    """Bus para agentes: publica primero a Postgres; el runner hace relay a NATS."""

    def __init__(self, subscriber_bus: BaseBus, outbox: PostgresOutbox) -> None:
        self.subscriber_bus = subscriber_bus
        self.outbox = outbox

    def publish(self, envelope: Envelope) -> None:
        self.outbox.enqueue(envelope)

    def subscribe(self, msg_type: str, handler: Handler) -> None:
        self.subscriber_bus.subscribe(msg_type, handler)
