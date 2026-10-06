from datetime import datetime, timezone

from tf.pipeline_schedule import due


def test_scheduler_runs_only_after_configured_utc_time_and_once_per_day():
    before = datetime(2026, 10, 6, 21, 59, tzinfo=timezone.utc)
    scheduled = datetime(2026, 10, 6, 22, 0, tzinfo=timezone.utc)

    assert not due(before, "22:00", {}, retry_minutes=30)
    assert due(scheduled, "22:00", {}, retry_minutes=30)
    assert not due(
        scheduled, "22:00", {"last_success_date": "2026-10-06"}, retry_minutes=30
    )


def test_scheduler_backs_off_after_failed_attempt():
    now = datetime(2026, 10, 6, 22, 0, tzinfo=timezone.utc)
    state = {"last_attempt_at": "2026-10-06T21:50:00+00:00"}

    assert not due(now, "22:00", state, retry_minutes=30)
    assert due(datetime(2026, 10, 6, 22, 20, tzinfo=timezone.utc), "22:00", state, retry_minutes=30)
