"""Fuente de datos real: descarga de diarias desde Yahoo Finance (chart API, sin API key).

Normaliza al formato que ya consume `tf.marketdata.load_csv`. La separación entre
`fetch_yahoo` (red) e `ingest_yahoo` (normalización + escritura + validación) permite
probar la ingesta completa sin red. Los datos escritos bajo `data/` son de solo lectura
para el resto del sistema (G4/B-6): aquí solo se crean o actualizan ficheros crudos.
"""

from __future__ import annotations

import calendar
import csv
import io
import json
import time
import urllib.request
from pathlib import Path

from tf.marketdata import load_csv

YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"


def fetch_yahoo(symbol: str, start: str | None = None, end: str | None = None) -> str:
    """Descarga diarias de Yahoo. start/end en formato YYYYMMDD (por defecto, todo el histórico)."""
    params = [f"interval=1d", f"period2={_yyyymmdd_to_epoch(end) if end else int(time.time())}"]
    if start:
        params.insert(1, f"period1={_yyyymmdd_to_epoch(start)}")
    url = f"{YAHOO_URL.format(symbol=symbol)}?{'&'.join(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "trading-floor/0.1"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _yyyymmdd_to_epoch(date: str) -> int:
    # Yahoo espera epochs absolutos; mktime interpreta la fecha en la TZ local
    # y hacía variar period1/period2 entre máquina de desarrollo y contenedor.
    return calendar.timegm(time.strptime(date, "%Y%m%d"))


def normalize_yahoo(raw: str, symbol: str) -> str:
    """Convierte la respuesta JSON de Yahoo al CSV interno (ts,open,high,low,close).

    `ts` es el epoch (segundos) de la barra; se descartan barras con OHLC incompleto.
    """
    data = json.loads(raw)
    result = (data.get("chart") or {}).get("result") or []
    if not result:
        error = (data.get("chart") or {}).get("error") or {}
        raise ValueError(
            f"Yahoo no devolvió datos para '{symbol}': "
            f"{error.get('code') or 'respuesta vacía'} — {error.get('description') or ''}".strip(" —")
        )
    result = result[0]
    ts = result.get("timestamp") or []
    quote = (result.get("indicators") or {}).get("quote") or [{}]
    o, h, l, c = (quote[0].get(k) or [] for k in ("open", "high", "low", "close"))

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["ts", "open", "high", "low", "close"])
    n_rows = 0
    for i, t in enumerate(ts):
        row = (o[i], h[i], l[i], c[i]) if i < len(o) else (None, None, None, None)
        if any(v is None for v in row):
            continue
        writer.writerow([int(t), row[0], row[1], row[2], row[3]])
        n_rows += 1
    if n_rows == 0:
        raise ValueError(f"Yahoo no devolvió filas para '{symbol}'")
    return out.getvalue()


def ingest_yahoo(symbol: str, raw: str, out_dir: str | Path = "data") -> Path:
    """Normaliza, valida (OHLC coherente, barras suficientes) y escribe data/{symbol}.csv."""
    normalized = normalize_yahoo(raw, symbol)
    tmp = Path(out_dir) / f"{symbol.lower()}.csv.tmp"
    final = Path(out_dir) / f"{symbol.lower()}.csv"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(normalized)
    try:
        load_csv(tmp, symbol=symbol.upper())  # valida antes de publicar el fichero
        tmp.replace(final)
    finally:
        tmp.unlink(missing_ok=True)
    return final
