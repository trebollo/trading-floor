"""Tests del DSL (lista blanca) y del motor (anti-look-ahead, costes, métricas)."""

import dataclasses

import numpy as np
import pytest

from tf.dsl import SpecError, generate_target_position, validate_spec, MAX_PARAMS
from tf.engine import CostModel, DEFAULT_COSTS, run_backtest
from tf.marketdata import synthetic_market


# ---------------------------------------------------------------------------
# DSL
# ---------------------------------------------------------------------------


def test_whitelisted_types_accepted():
    for spec in [
        {"type": "sma_cross", "params": {"fast_window": 10, "slow_window": 30}},
        {"type": "breakout", "params": {"lookback": 20, "exit_buffer": 0.05}},
        {"type": "momentum", "params": {"lookback": 20, "threshold": 0.01}},
    ]:
        validate_spec(spec)


def test_unknown_type_rejected():
    with pytest.raises(SpecError, match="lista blanca"):
        validate_spec({"type": "martingala_infinita", "params": {"x": 1}})


def test_too_many_params_rejected():
    params = {f"p{i}": 1.0 for i in range(MAX_PARAMS + 1)}
    with pytest.raises(SpecError, match="sobreajuste"):
        validate_spec({"type": "sma_cross", "params": params})


def test_non_numeric_params_rejected():
    with pytest.raises(SpecError, match="numérico"):
        validate_spec({"type": "momentum", "params": {"lookback": "20", "threshold": 0.01}})


def test_signals_are_binary_and_valid():
    data = synthetic_market(n=500)
    pos = generate_target_position({"type": "sma_cross", "params": {"fast_window": 10, "slow_window": 30}}, data.close)
    assert set(np.unique(pos)) <= {0.0, 1.0}


# ---------------------------------------------------------------------------
# Motor
# ---------------------------------------------------------------------------


def test_no_lookahead_perturbing_future_does_not_change_past():
    """Si cambio los precios futuros, el equity pasado no puede cambiar (R-2)."""
    data = synthetic_market(n=500, seed=1)
    spec = {"type": "sma_cross", "params": {"fast_window": 10, "slow_window": 30}}
    base = run_backtest(data, spec)

    tampered_close = data.close.copy()
    tampered_close[450:] *= 3.0  # futuro alterado (coherente en OHLC)
    tampered = dataclasses.replace(
        data, close=tampered_close, high=data.high * np.where(np.arange(len(data)) >= 450, 3.0, 1.0),
        low=data.low * np.where(np.arange(len(data)) >= 450, 3.0, 1.0),
    )
    after = run_backtest(tampered, spec)

    np.testing.assert_allclose(base.equity[:440], after.equity[:440], rtol=1e-12)


def test_costs_reduce_returns():
    data = synthetic_market(n=1000)
    spec = {"type": "sma_cross", "params": {"fast_window": 20, "slow_window": 60}}
    free = run_backtest(data, spec, CostModel(commission_rate=0.0, slippage_rate=0.0))
    costly = run_backtest(data, spec, DEFAULT_COSTS)
    assert costly.equity[-1] <= free.equity[-1]


def test_metrics_sane_on_trending_market():
    data = synthetic_market(n=2000, drift=0.002, vol=0.005, adverse_prob=0.0, seed=3)
    spec = {"type": "sma_cross", "params": {"fast_window": 20, "slow_window": 60}}
    res = run_backtest(data, spec).compute_metrics()
    assert res.metrics["total_return"] > 0
    assert 0 <= res.metrics["max_drawdown"] < 1
    assert res.metrics["n_trades"] > 0


def test_flat_market_gives_no_trades_for_breakout():
    data = synthetic_market(n=300, drift=0.0, vol=0.0001, adverse_prob=0.0, seed=5)
    spec = {"type": "breakout", "params": {"lookback": 20, "exit_buffer": 0.05}}
    res = run_backtest(data, spec).compute_metrics()
    assert res.metrics["n_trades"] < 10
