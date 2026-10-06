"""Scheduler residente diario para el pipeline distribuido de investigación."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tf.pipeline_schedule import due


def main() -> None:
    parser = argparse.ArgumentParser(description="Scheduler UTC para workers distribuidos")
    parser.add_argument("--once", action="store_true", help="ejecuta ahora un ciclo y termina")
    args = parser.parse_args()

    dsn = os.getenv("TF_DATABASE_URL")
    if not dsn:
        raise SystemExit("TF_DATABASE_URL es obligatorio para el scheduler")
    schedule = os.getenv("TF_SCHEDULE_UTC", "22:00")
    retry_minutes = int(os.getenv("TF_SCHEDULER_RETRY_MINUTES", "30"))
    poll_seconds = int(os.getenv("TF_SCHEDULER_POLL_SECONDS", "15"))
    data_path = Path(os.getenv("TF_MARKET_DATA", "/var/lib/trading-floor/data/aapl.csv"))
    data_start = os.getenv("TF_DATA_START", "20150101")
    dataset_dir = os.getenv("TF_DATASET_DIR", "/var/lib/trading-floor/datasets")
    proposal_count = os.getenv("TF_PROPOSALS", "5")
    timeout_seconds = os.getenv("TF_PIPELINE_TIMEOUT", "300")
    root = Path(__file__).resolve().parents[1]
    state_key = "scheduler/distributed-pipeline"
    stop = False

    from tf.audit_pg import PostgresAuditLog
    from tf.state_pg import PostgresStateStore

    audit = PostgresAuditLog(dsn=dsn)
    state_store = PostgresStateStore(dsn=dsn)
    if not audit.verify():
        state_store.close()
        audit._conn.close()
        raise SystemExit("cadena audit inválida; scheduler no inicia")
    def request_stop(*_args) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    pipeline = root / "scripts" / "run_distributed_pipeline.py"

    def run_cycle() -> bool:
        attempted_at = datetime.now(timezone.utc)
        state = state_store.get(state_key, {})
        try:
            from tf.datafeed import fetch_yahoo, ingest_yahoo

            raw = fetch_yahoo("AAPL", start=data_start)
            ingest_yahoo("AAPL", raw, out_dir=data_path.parent)
            result = subprocess.run(
                [sys.executable, str(pipeline), "--market-data", str(data_path),
                 "--dataset-dir", dataset_dir, "--proposals", proposal_count,
                 "--timeout", timeout_seconds, "--skip-if-completed-today"],
                cwd=root,
                check=False,
            )
            if result.returncode != 0:
                raise RuntimeError(f"pipeline terminó con código {result.returncode}")
            state_store.set(state_key, {
                "last_success_date": attempted_at.date().isoformat(),
                "last_attempt_at": attempted_at.isoformat(),
                "last_error": None,
            })
            audit.append(
                actor="pipeline-scheduler", event_type="pipeline.scheduler_completed",
                payload={"date": attempted_at.date().isoformat()},
            )
            return True
        except Exception as exc:
            state_store.set(state_key, {
                **state,
                "last_attempt_at": attempted_at.isoformat(),
                "last_error": f"{type(exc).__name__}: {exc}",
            })
            audit.append(
                actor="pipeline-scheduler", event_type="pipeline.scheduler_failed",
                payload={"date": attempted_at.date().isoformat(),
                         "error": f"{type(exc).__name__}: {exc}"},
            )
            return False

    try:
        if args.once:
            with state_store.lock(state_key):
                return_code = 0 if run_cycle() else 1
            if return_code:
                raise SystemExit(return_code)
            return

        while not stop:
            now = datetime.now(timezone.utc)
            if due(now, schedule, state_store.get(state_key, {}), retry_minutes):
                with state_store.lock(state_key):
                    # Recheck under the leadership lock in case another instance won.
                    now = datetime.now(timezone.utc)
                    if due(now, schedule, state_store.get(state_key, {}), retry_minutes):
                        run_cycle()
            time.sleep(poll_seconds)
    finally:
        state_store.close()
        audit._conn.close()


if __name__ == "__main__":
    main()
