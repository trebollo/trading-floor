"""Ciclo diario del sistema vivo.

Ejecuta: uv run python scripts/run_daily_cycle.py            (ciclo completo, con comité si toca)
         uv run python scripts/run_daily_cycle.py --force-weekly   (fuerza el comité)

Infraestructura: usa NATS (4222) y Postgres (5432) si están disponibles — tu Docker
local — y si no, bus en memoria y audit log SQLite, con el mismo contrato. La
diferencia se anuncia en la salida para que nunca haya ambigüedad sobre qué persiste.
"""

import argparse
import json
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def port_open(host: str, port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(1.0)
        return s.connect_ex((host, port)) == 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Ciclo diario: ingesta → research → paper day → memoria → comité")
    parser.add_argument("--root", default=".", help="raíz del estado (data/, state/)")
    parser.add_argument("--force-weekly", action="store_true", help="fuerza el comité semanal")
    args = parser.parse_args()

    from tf.audit import SqliteAuditLog
    from tf.bus import InMemoryBus
    from tf.gateway import ModelGateway
    from tf.scheduler import CycleConfig, DailyCycle

    if port_open("localhost", 4222):
        from tf.bus_nats import NatsBus

        bus, transport = NatsBus().start(), "NATS JetStream"
    else:
        bus, transport = InMemoryBus(), "memoria (NATS no disponible)"
    if port_open("localhost", 5432):
        from tf.audit_pg import PostgresAuditLog

        audit, audit_where = PostgresAuditLog(), "Postgres (apéndice-only)"
    else:
        audit, audit_where = SqliteAuditLog(), "SQLite (Postgres no disponible)"
    gateway = ModelGateway.from_yaml(Path(__file__).parent.parent / "config" / "models.yaml")
    config = CycleConfig.under(args.root)
    print(f"Ciclo diario — bus: {transport} · audit: {audit_where}\n" + "=" * 74)
    try:
        report = DailyCycle(bus, audit, gateway=gateway, config=config).run(force_weekly=args.force_weekly)
    finally:
        if transport.startswith("NATS"):
            bus.close()

    print(json.dumps(report["phases"], indent=2, ensure_ascii=False, default=str))
    print(f"\nPortfolio en papel: {report['phases'].get('paper_day') and len(report['phases']['paper_day']) or 0} estrategias")
    print(f"Audit log íntegro: {report['audit_verificado']} · duración: {report['duracion_s']}s")


if __name__ == "__main__":
    main()
