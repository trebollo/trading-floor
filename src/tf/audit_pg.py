"""Audit log inmutable sobre Postgres (misma cadena de hash que la SQLite).

La tabla `audit_log` es apéndice-only por reglas SQL (migraciones 0001). Esta
implementación es de un solo escritor: para Fase 4 bastará un servicio de plataforma
que centralice los appends; el hash encadenado hace detetable cualquier manipulación.
"""

from __future__ import annotations

from typing import Any

from tf.audit import AuditEntry, AuditLog, entry_hash

DDL = """
CREATE TABLE IF NOT EXISTS {table} (
    seq BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL,
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL
)
"""


class PostgresAuditLog(AuditLog):
    def __init__(self, dsn: str = "postgresql://trading:trading@localhost:5432/trading_floor", table: str = "audit_log") -> None:
        import psycopg  # import diferido

        self._table = table
        self._conn = psycopg.connect(dsn)
        self._conn.autocommit = True
        self._conn.execute(DDL.format(table=table))

    def append(self, actor: str, event_type: str, payload: dict[str, Any]) -> AuditEntry:
        row = self._conn.execute(
            f"SELECT COALESCE(MAX(seq), 0), COALESCE((SELECT hash FROM {self._table} ORDER BY seq DESC LIMIT 1), '') FROM {self._table}"
        ).fetchone()
        last_seq, prev_hash = int(row[0]), row[1]
        from datetime import datetime, timezone

        ts = datetime.now(timezone.utc).isoformat()
        h = entry_hash(prev_hash, ts, actor, event_type, payload)
        self._conn.execute(
            f"INSERT INTO {self._table} (ts, actor, event_type, payload, prev_hash, hash) VALUES (%s, %s, %s, %s, %s, %s)",
            (ts, actor, event_type, json_dumps(payload), prev_hash, h),
        )
        return AuditEntry(
            seq=last_seq + 1, ts=ts, actor=actor, event_type=event_type,
            payload=payload, prev_hash=prev_hash, hash=h,
        )

    def entries(self) -> list[AuditEntry]:
        rows = self._conn.execute(
            f"SELECT seq, ts, actor, event_type, payload, prev_hash, hash FROM {self._table} ORDER BY seq"
        ).fetchall()
        return [
            AuditEntry(
                seq=r[0], ts=r[1].isoformat() if hasattr(r[1], "isoformat") else str(r[1]),
                actor=r[2], event_type=r[3], payload=r[4] if isinstance(r[4], dict) else json_loads(r[4]),
                prev_hash=r[5], hash=r[6],
            )
            for r in rows
        ]

    def verify(self) -> bool:
        prev = ""
        for entry in self.entries():
            expected = entry_hash(prev, entry["ts"], entry["actor"], entry["event_type"], entry["payload"])
            if entry["prev_hash"] != prev or entry["hash"] != expected:
                return False
            prev = entry["hash"]
        return True

    def drop(self) -> None:
        """Solo para tablas de prueba."""
        self._conn.execute(f"DROP TABLE IF EXISTS {self._table}")


def json_dumps(value: Any) -> str:
    import json

    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def json_loads(value: str) -> Any:
    import json

    return json.loads(value)
