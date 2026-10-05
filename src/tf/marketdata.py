"""Datos de mercado para Fase 1.

Sin red: generador sintético determinista (geometric Brownian motion con regímenes)
y un cargador CSV para datos reales cuando estén disponibles. El motor consume
arrays numpy; los loaders son la única fuente de datos y son de solo lectura (G4/B-6).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class MarketData:
    symbol: str
    ts: np.ndarray  # int64: índices de barra (o timestamps)
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    regime: np.ndarray | None = None  # etiquetas de régimen por barra (0..n-1)

    def __len__(self) -> int:
        return len(self.close)

    def validate(self) -> None:
        n = len(self.close)
        assert len(self.open) == len(self.high) == len(self.low) == n, "arrays de longitud distinta"
        if len(self.ts) != n:
            raise ValueError("ts debe tener la misma longitud que close")
        if n < 2:
            raise ValueError("se necesitan al menos 2 barras")
        if not (np.all(self.high >= self.low) and np.all(self.high >= self.close) and np.all(self.low <= self.close)):
            raise ValueError("OHLC incoherente")


def synthetic_market(
    symbol: str = "SYNTH",
    n: int = 2000,
    seed: int = 42,
    drift: float = 0.0004,
    vol: float = 0.012,
    adverse_prob: float = 0.002,     # P(normal → adverso)
    recovery_prob: float = 0.02,     # P(adverso → normal); fases adversas ~9 % del tiempo
    adverse_drift: float = -0.002,
) -> MarketData:
    """Serie sintética con dos regímenes: normal (0) y adverso (1), determinista.

    Las fases adversas son cortas (crisis), como en mercados reales.
    """
    rng = np.random.default_rng(seed)
    regimes = np.zeros(n, dtype=np.int8)
    for i in range(1, n):
        if regimes[i - 1] == 0:
            regimes[i] = 1 if rng.random() < adverse_prob else 0
        else:
            regimes[i] = 0 if rng.random() < recovery_prob else 1
    daily_drift = np.where(regimes == 1, adverse_drift, drift)
    returns = daily_drift + vol * rng.standard_normal(n)
    close = 100.0 * np.exp(np.cumsum(returns))
    open_ = np.empty_like(close)
    open_[0] = close[0]
    open_[1:] = close[:-1]  # el open de la barra i es el close de i-1
    spread = vol * close * 0.25
    high = np.maximum(open_, close) + spread * rng.random(n)
    low = np.minimum(open_, close) - spread * rng.random(n)
    return MarketData(
        symbol=symbol,
        ts=np.arange(n, dtype=np.int64),
        open=open_,
        high=high,
        low=low,
        close=close,
        regime=regimes,
    )


def load_csv(path: str | Path, symbol: str | None = None) -> MarketData:
    """Carga un CSV con columnas ts,open,high,low,close[,regime]."""
    import csv

    rows = list(csv.DictReader(Path(path).open()))
    if not rows:
        raise ValueError(f"CSV vacío: {path}")
    cols = rows[0].keys()
    for required in ("ts", "open", "high", "low", "close"):
        if required not in cols:
            raise ValueError(f"al CSV le falta la columna {required}")
    def col(name: str) -> np.ndarray:
        return np.array([float(r[name]) for r in rows])

    md = MarketData(
        symbol=symbol or Path(path).stem,
        ts=col("ts").astype(np.int64),
        open=col("open"),
        high=col("high"),
        low=col("low"),
        close=col("close"),
        regime=col("regime").astype(np.int8) if "regime" in cols else None,
    )
    md.validate()
    return md
