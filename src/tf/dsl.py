"""DSL restringido de estrategias (contraparte en código de `strategy.spec.v1`).

Solo bloques de construcción de la lista blanca: el código candidato no es Python
arbitrario (R-2/B-1). Cada bloque es determinista y verificable.
"""

from __future__ import annotations

from typing import Any, Literal

import numpy as np

StrategyType = Literal["sma_cross", "breakout", "rsi_reversion", "momentum"]

ALLOWED_TYPES: tuple[str, ...] = ("sma_cross", "breakout", "rsi_reversion", "momentum")

MAX_PARAMS = 6  # más parámetros ⇒ sobreajuste estructural (B-4/V)


class SpecError(ValueError):
    """Especificación inválida o fuera de la lista blanca."""


def validate_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Valida la forma del spec contra la lista blanca. Lanza SpecError si no cumple."""
    if spec.get("type") not in ALLOWED_TYPES:
        raise SpecError(f"tipo de estrategia fuera de la lista blanca: {spec.get('type')!r}")
    params = spec.get("params")
    if not isinstance(params, dict) or not params:
        raise SpecError("params debe ser un dict no vacío")
    if len(params) > MAX_PARAMS:
        raise SpecError(f"demasiados parámetros ({len(params)} > {MAX_PARAMS}): sospecha de sobreajuste")
    for key, value in params.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SpecError(f"parámetro '{key}' debe ser numérico")
        if not np.isfinite(value):
            raise SpecError(f"parámetro '{key}' no finito")
    return spec


def sma(close: np.ndarray, window: int) -> np.ndarray:
    """Media móvil simple; NaN hasta tener ventana completa (sin inventar datos)."""
    if window < 2:
        raise SpecError("la ventana de SMA debe ser >= 2")
    out = np.full_like(close, np.nan, dtype=float)
    if window <= len(close):
        cums = np.concatenate(([0.0], np.cumsum(close)))
        out[window - 1 :] = (cums[window:] - cums[:-window]) / window
    return out


def _sma_cross_signals(close: np.ndarray, params: dict[str, float]) -> np.ndarray:
    fast = sma(close, int(params["fast_window"]))
    slow = sma(close, int(params["slow_window"]))
    if int(params["fast_window"]) >= int(params["slow_window"]):
        raise SpecError("fast_window debe ser menor que slow_window")
    position = np.where(np.isnan(fast) | np.isnan(slow), 0.0, np.where(fast > slow, 1.0, 0.0))
    return position


def _breakout_signals(close: np.ndarray, params: dict[str, float]) -> np.ndarray:
    window = int(params["lookback"])
    if window < 5:
        raise SpecError("lookback debe ser >= 5")
    n = len(close)
    position = np.zeros(n, dtype=float)
    highest = close[0]
    for i in range(1, n):
        start = max(0, i - window)
        prev_high = close[start:i].max()
        position[i] = 1.0 if close[i] > prev_high else (0.0 if close[i] < prev_high * (1 - params["exit_buffer"]) else position[i - 1])
    return position


def _rsi(close: np.ndarray, window: int) -> np.ndarray:
    delta = np.diff(close, prepend=close[0])
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    avg_gain = np.convolve(gain, np.ones(window) / window, mode="full")[: len(gain)]
    avg_loss = np.convolve(loss, np.ones(window) / window, mode="full")[: len(loss)]
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = avg_gain / avg_loss
        rsi = 100.0 - 100.0 / (1.0 + rs)
    rsi[np.isnan(rsi)] = 50.0
    return rsi


def _rsi_reversion_signals(close: np.ndarray, params: dict[str, float]) -> np.ndarray:
    window = int(params["rsi_window"])
    lower, upper = params["lower"], params["upper"]
    if not (0 < lower < upper < 100):
        raise SpecError("se requiere 0 < lower < upper < 100")
    rsi = _rsi(close, window)
    position = np.zeros(len(close), dtype=float)
    position[rsi < lower] = 1.0
    position[rsi > upper] = 0.0
    # hold: mantener la posición mientras el RSI esté entre umbrales
    for i in range(1, len(position)):
        if lower <= rsi[i] <= upper:
            position[i] = position[i - 1]
    return position


def _momentum_signals(close: np.ndarray, params: dict[str, float]) -> np.ndarray:
    window = int(params["lookback"])
    threshold = params["threshold"]
    if window < 2:
        raise SpecError("lookback debe ser >= 2")
    ret = np.zeros_like(close)
    ret[window:] = close[window:] / close[:-window] - 1.0
    return np.where(ret > threshold, 1.0, 0.0)


_SIGNALS: dict[str, Any] = {
    "sma_cross": _sma_cross_signals,
    "breakout": _breakout_signals,
    "rsi_reversion": _rsi_reversion_signals,
    "momentum": _momentum_signals,
}


def generate_target_position(spec: dict[str, Any], close: np.ndarray) -> np.ndarray:
    """Posición objetivo por barra (0..1). Determinista y sin look-ahead interno."""
    validate_spec(spec)
    close = np.asarray(close, dtype=float)
    return _SIGNALS[spec["type"]](close, spec["params"])
