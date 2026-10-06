"""Ciclo diario del sistema vivo.

Ejecuta: uv run python scripts/run_daily_cycle.py            (ciclo completo, con comité si toca)
         uv run python scripts/run_daily_cycle.py --force-weekly   (fuerza el comité)

Infraestructura: usa NATS (4222) y Postgres (5432) si están disponibles — tu Docker
local — y si no, bus en memoria y audit log SQLite, con el mismo contrato. La
diferencia se anuncia en la salida para que nunca haya ambigüedad sobre qué persiste.
"""

import argparse
import json
import os
import socket
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def port_open(host: str, port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(1.0)
        return s.connect_ex((host, port)) == 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Ciclo diario: ingesta → research → paper day → memoria → comité")
    parser.add_argument("--root", default=".", help="raíz del estado (data/, state/)")
    parser.add_argument("--force-weekly", action="store_true", help="fuerza el comité semanal")
    parser.add_argument("--require-infra", action="store_true", help="fallar si NATS o Postgres no están disponibles")
    args = parser.parse_args()

    from tf.audit import SqliteAuditLog
    from tf.budget import BudgetLimits, CostGovernor
    from tf.bus import InMemoryBus
    from tf.directives import DirectivesBoard
    from tf.gateway import ModelGateway
    from tf.scheduler import CycleConfig, DailyCycle

    gateway = ModelGateway.from_yaml(Path(__file__).parent.parent / "config" / "models.yaml")
    config = CycleConfig.under(args.root)

    nats_servers = [s.strip() for s in os.getenv("TF_NATS_URL", "nats://localhost:4222").split(",") if s.strip()]
    nats_endpoint = urlparse(nats_servers[0])
    nats_up = port_open(nats_endpoint.hostname or "localhost", nats_endpoint.port or 4222)
    database_url = os.getenv("TF_DATABASE_URL") or os.getenv("DATABASE_URL")
    database_endpoint = urlparse(database_url or "postgresql://localhost:5432")
    pg_up = port_open(database_endpoint.hostname or "localhost", database_endpoint.port or 5432)

    if args.require_infra and (not nats_up or not pg_up):
        missing = ", ".join(name for name, ready in (("NATS", nats_up), ("Postgres", pg_up)) if not ready)
        raise SystemExit(f"infra requerida pero no disponible: {missing}")

    if nats_up:
        from tf.bus_nats import NatsBus

        bus, transport = NatsBus(servers=nats_servers).start(), "NATS JetStream"
    else:
        bus, transport = InMemoryBus(), "memoria (NATS no disponible)"
    if pg_up:
        from tf.audit_pg import PostgresAuditLog
        from tf.state_pg import PostgresStateStore, import_legacy_json_once

        audit, audit_where = PostgresAuditLog(dsn=database_url or "postgresql://trading:trading@localhost:5432/trading_floor"), "Postgres (apéndice-only)"
        state_store = PostgresStateStore(dsn=database_url or "postgresql://trading:trading@localhost:5432/trading_floor")
    else:
        from tf.audit import SqliteAuditLog

        audit_path = config.state_path.parent / "audit.db"
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit, audit_where = SqliteAuditLog(audit_path), f"SQLite {audit_path} (Postgres no disponible)"
        state_store = None
    directives = DirectivesBoard.load(Path(__file__).parent.parent / "config" / "directivas.yaml")
    guardrails = Path(__file__).parent.parent / "config" / "guardrails.yaml"
    governor = CostGovernor(
        limits=BudgetLimits.from_yaml(guardrails),
        state_path=config.state_path.parent / "budget_state.json",
        audit=audit,
        state_store=state_store,
    )
    if state_store is not None:
        import_legacy_json_once(state_store, "scheduler/cycle-state", config.state_path)
        import_legacy_json_once(state_store, "collective/memory", config.memory_path)
        import_legacy_json_once(state_store, "g3/budget", config.state_path.parent / "budget_state.json")
    print(f"Ciclo diario — bus: {transport} · audit: {audit_where}\n" + "=" * 74)
    try:
        report = DailyCycle(
            bus, audit, gateway=gateway, config=config,
            governor=governor, directives=directives,
            state_store=state_store,
        ).run(force_weekly=args.force_weekly)
    finally:
        if transport.startswith("NATS"):
            bus.close()
        if state_store is not None:
            state_store.close()
        if hasattr(audit, "_conn"):
            audit._conn.close()

    print(json.dumps(report["phases"], indent=2, ensure_ascii=False, default=str))
    if report.get("informe_diario"):
        print(f"\nInforme diario (chief-of-staff): {json.dumps(report['informe_diario'], ensure_ascii=False, default=str)}")
    if report.get("presupuesto"):
        print(f"Presupuesto G3 hoy: {json.dumps(report['presupuesto'], ensure_ascii=False)}")
    print(f"\nPortfolio en papel: {report['phases'].get('paper_day') and len(report['phases']['paper_day']) or 0} estrategias")
    print(f"Audit log íntegro: {report['audit_verificado']} · duración: {report['duracion_s']}s")


if __name__ == "__main__":
    main()
