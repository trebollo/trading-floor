"""Almacén JSON compartido en Postgres para estado operacional del sistema."""

from __future__ import annotations

import json
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Iterator

DEFAULT_DSN = "postgresql://trading:trading@localhost:5432/trading_floor"

DDL = """
CREATE TABLE IF NOT EXISTS tf_state (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    version BIGINT NOT NULL DEFAULT 1,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

INBOX_DDL = """
CREATE TABLE IF NOT EXISTS tf_inbox (
    department TEXT NOT NULL,
    envelope_id TEXT NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (department, envelope_id)
)
"""


def import_legacy_json_once(store: "PostgresStateStore", key: str, path: str | Path) -> bool:
    """Importa el JSON local solo si la clave aún no existe en Postgres."""
    path = Path(path)
    if not path.exists() or store.get(key) is not None:
        return False
    store.set(key, json.loads(path.read_text()))
    return True


class PostgresStateStore:
    """Operaciones de estado versionadas y mutaciones serializadas por clave.

    ``mutate`` ejecuta read-modify-write en una transacción; no usar ``set`` con
    un snapshot viejo cuando varios procesos puedan actualizar la misma clave.
    """

    def __init__(self, dsn: str = DEFAULT_DSN) -> None:
        import psycopg

        self._conn = psycopg.connect(dsn)
        self._conn.autocommit = True
        self._conn.execute(DDL)

    def get(self, key: str, default: Any = None) -> Any:
        row = self._conn.execute("SELECT value FROM tf_state WHERE key = %s", (key,)).fetchone()
        return deepcopy(row[0]) if row else deepcopy(default)

    def set(self, key: str, value: Any) -> None:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        with self._conn.transaction():
            self._lock_key(key)
            self._conn.execute(
                "INSERT INTO tf_state (key, value) VALUES (%s, %s::jsonb) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, "
                "version = tf_state.version + 1, updated_at = now()",
                (key, encoded),
            )

    def mutate(self, key: str, update: Callable[[Any], Any], default: Any = None) -> Any:
        """Bloquea la clave, llama ``update(value)`` y persiste el resultado atómicamente."""
        with self._conn.transaction():
            self._lock_key(key)
            row = self._conn.execute("SELECT value FROM tf_state WHERE key = %s FOR UPDATE", (key,)).fetchone()
            value = row[0] if row else deepcopy(default)
            changed = update(value)
            if changed is not None:
                value = changed
            encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
            self._conn.execute(
                "INSERT INTO tf_state (key, value) VALUES (%s, %s::jsonb) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, "
                "version = tf_state.version + 1, updated_at = now()",
                (key, encoded),
            )
            return deepcopy(value)

    def delete(self, key: str) -> None:
        with self._conn.transaction():
            self._lock_key(key)
            self._conn.execute("DELETE FROM tf_state WHERE key = %s", (key,))

    def inbox(self) -> "PostgresInbox":
        return PostgresInbox(self._conn)

    @contextmanager
    def lock(self, key: str) -> Iterator[None]:
        """Lock de sesión para exclusión mutua que abarca una operación larga."""
        self._conn.execute("SELECT pg_advisory_lock(hashtextextended(%s, 1))", (key,))
        try:
            yield
        finally:
            self._conn.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 1))", (key,))

    def _lock_key(self, key: str) -> None:
        self._conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (key,))

    def close(self) -> None:
        self._conn.close()


class PostgresInbox:
    """Deduplicación durable por departamento y envelope id."""

    def __init__(self, connection: Any) -> None:
        self._conn = connection
        self._conn.execute(INBOX_DDL)

    def completed(self, department: str, envelope_id: str) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM tf_inbox WHERE department = %s AND envelope_id = %s",
            (department, envelope_id),
        ).fetchone() is not None

    @contextmanager
    def lock(self, key: str) -> Iterator[None]:
        self._conn.execute("SELECT pg_advisory_lock(hashtextextended(%s, 2))", (key,))
        try:
            yield
        finally:
            self._conn.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 2))", (key,))

    def mark_completed(self, department: str, envelope_id: str) -> None:
        self._conn.execute(
            "INSERT INTO tf_inbox (department, envelope_id) VALUES (%s, %s) "
            "ON CONFLICT (department, envelope_id) DO NOTHING",
            (department, envelope_id),
        )

    def purge_before(self, timestamp: str) -> int:
        """Retención operacional: purga recibos antiguos tras superar ventana de replay."""
        cursor = self._conn.execute("DELETE FROM tf_inbox WHERE processed_at < %s", (timestamp,))
        return cursor.rowcount
