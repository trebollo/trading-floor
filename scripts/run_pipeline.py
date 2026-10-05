"""Demo Fase 1: pipeline Research → Backtest → Validation end-to-end.

Ejecuta: uv run python scripts/run_pipeline.py                (datos sintéticos)
         uv run python scripts/run_pipeline.py --csv data/aapl.csv   (datos reales)
Salida: catálogo de estrategias evaluadas (JSON) y eventos del audit log.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from tf.audit import SqliteAuditLog
from tf.bus import InMemoryBus
from tf.gateway import ModelGateway
from tf.marketdata import load_csv, synthetic_market
from tf.permissions import PermissionBroker
from tf.pipeline import PipelineRunner
from tf.validation import ValidationPolicy


def main() -> None:
    parser = argparse.ArgumentParser(description="Pipeline Research → Backtest → Validation")
    parser.add_argument(
        "--csv", help="CSV de datos reales (ts,open,high,low,close); por defecto, sintético"
    )
    parser.add_argument(
        "--llm",
        action="store_true",
        help="usa agentes LLM reales vía Model Gateway (requiere AI_GATEWAY_API_KEY y OPENCODE_API_KEY); "
        "sin credenciales degrada a plantilla determinista, auditado",
    )
    args = parser.parse_args()

    gateway = ModelGateway.from_yaml(Path(__file__).parent.parent / "config" / "models.yaml") if args.llm else None
    if args.csv:
        data = load_csv(Path(args.csv))
        print(f"Datos reales: {data.symbol}, {len(data)} barras")
    else:
        data = synthetic_market(n=2000, seed=42)
    bus = InMemoryBus()
    audit = SqliteAuditLog()
    broker = PermissionBroker.from_yaml(Path(__file__).parent.parent / "config" / "guardrails.yaml", audit=audit)

    runner = PipelineRunner(bus, broker, audit, policy=ValidationPolicy(min_trades=30), gateway=gateway)
    catalog = runner.run(data)

    print(f"\nCatálogo: {len(catalog)} estrategias evaluadas\n" + "=" * 72)
    for entry in catalog:
        spec = entry.spec
        metrics = entry.metrics
        print(f"\n{spec['type']} {spec['params']}")
        if metrics:
            print(
                f"  backtest: retorno={metrics['total_return']:+.2%} sharpe={metrics['sharpe']:.2f} "
                f"maxDD={metrics['max_drawdown']:.2%} trades={metrics['n_trades']:.0f}"
            )
        if entry.battery:
            checks = " ".join(f"{k}={'OK' if v else 'X'}" for k, v in entry.battery.items())
            print(f"  batería:  {checks}")
        print(f"  → {entry.final}")

    out = Path(".amp/in/artifacts")
    out.mkdir(parents=True, exist_ok=True)
    path = out / "fase1-catalogo.json"
    path.write_text(json.dumps([e.__dict__ | {"spec": e.spec} for e in catalog], indent=2, default=str))
    print(f"\nCatálogo guardado en {path}")
    print(f"Audit log: {len(audit.entries())} entradas, cadena íntegra: {audit.verify()}")


if __name__ == "__main__":
    main()
