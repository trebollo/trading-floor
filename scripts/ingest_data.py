"""Ingesta de datos reales: descarga diarias de Yahoo Finance y las deja en data/.

Ejecuta: uv run python scripts/ingest_data.py AAPL ^GSPC --start 20150101
El pipeline consume los ficheros resultantes con: uv run python scripts/run_pipeline.py --csv data/aapl.csv
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from tf.datafeed import fetch_yahoo, ingest_yahoo


def main() -> None:
    parser = argparse.ArgumentParser(description="Descarga diarias de Yahoo Finance a data/")
    parser.add_argument("symbols", nargs="+", help='símbolos de Yahoo (p. ej. AAPL, ^GSPC)')
    parser.add_argument("--start", help="fecha inicial YYYYMMDD")
    parser.add_argument("--end", help="fecha final YYYYMMDD")
    parser.add_argument("--out", default="data", help="directorio de salida (data/)")
    args = parser.parse_args()

    out_dir = Path(__file__).parent.parent / args.out
    for symbol in args.symbols:
        try:
            raw = fetch_yahoo(symbol, start=args.start, end=args.end)
            path = ingest_yahoo(symbol, raw, out_dir=out_dir)
            n_rows = len(path.read_text().strip().splitlines()) - 1
            print(f"OK  {symbol}: {n_rows} barras → {path}")
        except Exception as e:
            print(f"ERROR {symbol}: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()
