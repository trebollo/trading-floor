"""Lanza y espera el pipeline research → backtest → validation en runners Compose."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Pipeline distribuido de investigación (solo paper)")
    parser.add_argument("--market-data", default=os.getenv("TF_MARKET_DATA", "/var/lib/trading-floor/data/aapl.csv"))
    parser.add_argument("--dataset-dir", default=os.getenv("TF_DATASET_DIR", "/var/lib/trading-floor/datasets"))
    parser.add_argument("--proposals", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--skip-if-completed-today", action="store_true")
    args = parser.parse_args()
    if args.proposals < 1 or args.proposals > 100:
        parser.error("--proposals debe estar entre 1 y 100")

    from tf.audit_pg import PostgresAuditLog
    from tf.budget import BudgetLimits, CostGovernor
    from tf.bus_nats import NatsBus
    from tf.contracts import Actor
    from tf.datasets import prepare_market_snapshot
    from tf.state_pg import PostgresStateStore

    dsn = os.getenv("TF_DATABASE_URL")
    if not dsn:
        raise SystemExit("TF_DATABASE_URL es obligatorio para pipeline distribuido")
    servers = [v.strip() for v in os.getenv("TF_NATS_URL", "nats://nats:4222").split(",") if v.strip()]
    audit = PostgresAuditLog(dsn=dsn)
    if not audit.verify():
        audit._conn.close()
        raise SystemExit("la cadena de auditoría no verifica; no se publica el trigger")
    state_store = PostgresStateStore(dsn=dsn)
    governor = CostGovernor(
        BudgetLimits.from_yaml(Path(__file__).resolve().parents[1] / "config" / "guardrails.yaml"),
        audit=audit,
        state_store=state_store,
    )
    cycle_lock = state_store.lock("scheduler/distributed-cycle")
    cycle_lock.__enter__()
    today = datetime.now(timezone.utc).date().isoformat()
    scheduler_state = state_store.get("scheduler/distributed-pipeline", {})
    if args.skip_if_completed_today and scheduler_state.get("last_success_date") == today:
        print(json.dumps({"skipped": True, "reason": "ya hay ciclo exitoso hoy", "date": today}))
        cycle_lock.__exit__(None, None, None)
        state_store.close()
        audit._conn.close()
        return
    bus = NatsBus(servers=servers).start()
    cycle_id = f"cyc-{uuid.uuid4().hex}"
    batch_events: list[Any] = []
    verdicts: list[Any] = []
    macro_completions: list[Any] = []
    executive_reports: list[Any] = []
    ready_departments: set[str] = set()
    bus.subscribe("cycle.research_batch.v1", batch_events.append)
    bus.subscribe("validation.verdict.v1", verdicts.append)
    bus.subscribe("cycle.macro_news_completed.v1", macro_completions.append)
    bus.subscribe("executive.daily_report.v1", executive_reports.append)
    bus.subscribe(
        "runner.ready.v1",
        lambda env: ready_departments.add(env.payload["department"])
        if env.payload["status"] == "up" else None,
    )
    try:
        ready_deadline = time.monotonic() + args.timeout
        required = {"research", "backtest", "validation", "macro", "executive"}
        probe_id = f"probe-{uuid.uuid4().hex}"
        probe_attempt = 0
        while not required.issubset(ready_departments):
            if time.monotonic() >= ready_deadline:
                missing = sorted(required - ready_departments)
                raise TimeoutError(f"runners sin readiness probe: {', '.join(missing)}")
            probe_attempt += 1
            bus.publish_raw(
                "runner.probe.v1",
                {"probe_id": probe_id},
                actor=Actor(agent="pipeline-trigger", role="scheduler", department="executive"),
                id=f"{probe_id}-{probe_attempt}",
                correlation_id=probe_id,
            )
            time.sleep(1.0)

        dataset_path, digest = prepare_market_snapshot(args.market_data, args.dataset_dir)
        audit.append(
            actor="pipeline-trigger",
            event_type="pipeline.distributed_started",
            payload={"cycle_id": cycle_id, "dataset_sha256": digest,
                     "proposal_count": args.proposals},
        )
        bus.publish_raw(
            "cycle.trigger.v1",
            {
                "cycle_id": cycle_id,
                "cycle_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "market_data_uri": str(dataset_path),
                "market_data_sha256": digest,
                "proposal_count": args.proposals,
            },
            actor=Actor(agent="pipeline-trigger", role="scheduler", department="executive"),
            id=f"cycle-trigger-{cycle_id}",
            correlation_id=cycle_id,
        )

        deadline = time.monotonic() + args.timeout
        batch = None
        while batch is None:
            batch = next((e for e in batch_events if e.payload["cycle_id"] == cycle_id), None)
            if batch is None:
                if time.monotonic() >= deadline:
                    raise TimeoutError("no llegó cycle.research_batch.v1")
                time.sleep(0.05)

        expected = set(batch.payload["proposal_ids"])
        results: dict[str, dict] = {}
        while not expected.issubset(results):
            for event in verdicts:
                if event.payload.get("cycle_id") == cycle_id:
                    proposal_id = event.payload.get("proposal_id")
                    if proposal_id in expected:
                        results[proposal_id] = event.payload
            if expected.issubset(results):
                break
            if time.monotonic() >= deadline:
                missing = sorted(expected - set(results))
                raise TimeoutError(f"sin veredicto terminal para: {', '.join(missing)}")
            time.sleep(0.05)

        macro_completion = None
        while macro_completion is None:
            macro_completion = next(
                (e for e in macro_completions if e.payload["cycle_id"] == cycle_id), None
            )
            if macro_completion is None:
                if time.monotonic() >= deadline:
                    raise TimeoutError("no llegó cycle.macro_news_completed.v1")
                time.sleep(0.05)

        bus.publish_raw(
            "cycle.completed.v1",
            {
                "cycle_id": cycle_id,
                "cycle_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "dataset_sha256": digest,
                "validation_count": len(expected),
                "budget": governor.usage(),
                "macro_news": macro_completion.payload,
            },
            actor=Actor(agent="pipeline-trigger", role="scheduler", department="executive"),
            id=f"cycle-completed-{cycle_id}",
            correlation_id=cycle_id,
        )
        executive_report = None
        while executive_report is None:
            executive_report = next(
                (e for e in executive_reports if e.payload.get("cycle_id") == cycle_id), None
            )
            if executive_report is None:
                if time.monotonic() >= deadline:
                    raise TimeoutError("no llegó executive.daily_report.v1")
                time.sleep(0.05)

        audit.append(
            actor="pipeline-trigger",
            event_type="pipeline.distributed_completed",
            payload={"cycle_id": cycle_id, "proposal_count": len(expected),
                     "verdicts": {key: results[key]["verdict"] for key in sorted(results)},
                     "macro_news": macro_completion.payload,
                     "executive_report_id": executive_report.payload["report_id"]},
        )
        state_store.set("scheduler/distributed-pipeline", {
            "last_success_date": datetime.now(timezone.utc).date().isoformat(),
            "last_attempt_at": datetime.now(timezone.utc).isoformat(),
            "last_error": None,
        })

        print(json.dumps({
            "cycle_id": cycle_id,
            "dataset_sha256": digest,
            "proposals": len(expected),
            "skipped": batch.payload["skipped_count"],
            "macro_news": macro_completion.payload,
            "verdicts": [results[key] for key in sorted(results)],
            "executive_report": executive_report.payload,
            "audit_verified": audit.verify(),
        }, ensure_ascii=False, indent=2))
    except Exception as exc:
        scheduler_state = state_store.get("scheduler/distributed-pipeline", {})
        state_store.set("scheduler/distributed-pipeline", {
            **scheduler_state,
            "last_attempt_at": datetime.now(timezone.utc).isoformat(),
            "last_error": f"{type(exc).__name__}: {exc}",
        })
        audit.append(
            actor="pipeline-trigger",
            event_type="pipeline.distributed_failed",
            payload={"cycle_id": cycle_id, "error": f"{type(exc).__name__}: {exc}"},
        )
        raise
    finally:
        bus.close()
        cycle_lock.__exit__(None, None, None)
        state_store.close()
        audit._conn.close()


if __name__ == "__main__":
    main()
