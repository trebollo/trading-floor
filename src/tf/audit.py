"""Audit log inmutable con hash encadenado (apéndice-only).

Implementación SQLite (stdlib) para Fase 0 y tests; la firma se traslada tal cual a
Postgres. Toda violación de guardarraíl y toda decisión relevante se registran aquí.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def entry_hash(prev_hash: str, ts: str, actor: str, event_type: str, payload: Any) -> str:
    material = canonical_json(
        {"prev_hash": prev_hash, "ts": ts, "actor": actor, "event_type": event_type, "payload": payload}
    )
    return hashlib.sha256(material.encode()).hexdigest()


class AuditEntry(dict):
    """Entrada de auditoría: acceso dict y por atributo."""

    def __getattr__(self, name: str):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name) from None


class AuditLog:
    """Interfaz mínima: append y verificación de la cadena."""

    def append(self, actor: str, event_type: str, payload: dict[str, Any]) -> AuditEntry: ...
    def verify(self) -> bool: ...
    def entries(self) -> list[AuditEntry]: ...


class SqliteAuditLog(AuditLog):
    def __init__(self, path: str | Path = ":memory:") -> None:
        self._conn = sqlite3.connect(str(path))
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                seq INTEGER PRIMARY KEY,
                ts TEXT NOT NULL,
                actor TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                prev_hash TEXT NOT NULL,
                hash TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def append(self, actor: str, event_type: str, payload: dict[str, Any]) -> AuditEntry:
        cur = self._conn.execute("SELECT COALESCE(MAX(seq), 0), (SELECT hash FROM audit_log ORDER BY seq DESC LIMIT 1) FROM audit_log")
        last_seq, prev_hash = cur.fetchone()
        ts = datetime.now(timezone.utc).isoformat()
        h = entry_hash(prev_hash or "", ts, actor, event_type, payload)
        self._conn.execute(
            "INSERT INTO audit_log (seq, ts, actor, event_type, payload, prev_hash, hash) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (last_seq + 1, ts, actor, event_type, canonical_json(payload), prev_hash or "", h),
        )
        self._conn.commit()
        return AuditEntry(
            seq=last_seq + 1, ts=ts, actor=actor, event_type=event_type,
            payload=payload, prev_hash=prev_hash or "", hash=h,
        )

    def entries(self) -> list[AuditEntry]:
        rows = self._conn.execute("SELECT seq, ts, actor, event_type, payload, prev_hash, hash FROM audit_log ORDER BY seq").fetchall()
        return [AuditEntry(seq=r[0], ts=r[1], actor=r[2], event_type=r[3], payload=json.loads(r[4]), prev_hash=r[5], hash=r[6]) for r in rows]

    def verify(self) -> bool:
        prev = ""
        for entry in self.entries():
            expected = entry_hash(prev, entry["ts"], entry["actor"], entry["event_type"], entry["payload"])
            if entry["prev_hash"] != prev or entry["hash"] != expected:
                return False
            prev = entry["hash"]
        return True
