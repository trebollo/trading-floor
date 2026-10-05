"""Día de trading en papel sobre datos reales (Fase 4).

Ejecuta: uv run python scripts/run_paper_day.py --csv data/aapl.csv
         uv run python scripts/run_paper_day.py --csv data/aapl.csv --bars 750

Toma las estrategias VALIDADA / VALIDADA_PROVISIONAL del catálogo del pipeline
(.amp/in/artifacts/fase1-catalogo.json, lo produce run_pipeline.py) y simula una
sesión de paper trading sobre la ventana final del histórico con todos los
guardarraíles activos. La lógica vive en `tf.paper` para que el planificador
diario la reutilice sin duplicación.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from tf.marketdata import load_csv
from tf.paper import run_paper_session

CATALOG = Path(".amp/in/artifacts/fase1-catalogo.json")


def main() -> None:
    parser = argparse.ArgumentParser(description="Paper trading sobre datos reales con guardarraíles completos")
    parser.add_argument("--csv", required=True, help="CSV de datos reales (ts,open,high,low,close)")
    parser.add_argument("--bars", type=int, default=500, help="barras de la ventana de simulación")
    parser.add_argument("--catalog", default=str(CATALOG), help="catálogo JSON del pipeline")
    args = parser.parse_args()

    data = load_csv(Path(args.csv))
    catalog = json.loads(Path(args.catalog).read_text())
    validated = [e for e in catalog if e["final"] in ("VALIDADA", "VALIDADA_PROVISIONAL") and e.get("spec")]
    if not validated:
        print("Sin estrategias validadas en el catálogo: ejecuta antes run_pipeline.py")
        sys.exit(1)

    print(
        f"Paper trading sobre {data.symbol}: {len(validated)} estrategia(s) validada(s), "
        f"ventana de {args.bars} barras\n" + "=" * 74
    )
    for entry in validated:
        result = run_paper_session(entry, data.close, data.open, data.ts.astype(float), args.bars)
        print(f"\n▸ {result['strategy_id']} ({'PROVISIONAL' if result['provisional'] else 'VALIDADA'})")
        for step, msg in result["events"]:
            print(f"  {step}: {msg}")
        print(
            f"  → órdenes={result['n_orders']} rechazadas={result['n_rejected']} "
            f"retorno={result['retorno']:+.2%} equity={result['equity_final']:,.0f}"
        )
        print(f"  reconciliación: {'íntegra' if not result['reconcile'] else result['reconcile']}")


if __name__ == "__main__":
    main()
