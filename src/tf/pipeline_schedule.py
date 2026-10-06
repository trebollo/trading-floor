"""Reglas puras de calendario UTC del pipeline distribuido."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def due(now: datetime, scheduled_hhmm: str, state: dict, retry_minutes: int) -> bool:
    """Evita ciclos duplicados el mismo día y respeta backoff tras fallo."""
    now = now.astimezone(timezone.utc)
    today = now.date().isoformat()
    if state.get("last_success_date") == today:
        return False
    hour, minute = (int(part) for part in scheduled_hhmm.split(":"))
    if (now.hour, now.minute) < (hour, minute):
        return False
    failed_at = state.get("last_attempt_at")
    if failed_at:
        last_attempt = datetime.fromisoformat(failed_at)
        if now - last_attempt < timedelta(minutes=retry_minutes):
            return False
    return True
