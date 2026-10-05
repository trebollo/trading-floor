"""Tests de la batería canónica de validación."""

import numpy as np
import pytest

from tf.engine import DEFAULT_COSTS, run_backtest
from tf.marketdata import synthetic_market
from tf.validation import (
    BatteryResult,
    ValidationPolicy,
    cost_robustness,
    monte_carlo,
    param_sensitivity,
    portfolio_correlation,
    regime_stress,
    run_battery,
    walk_forward,
)


def trending_data(n=2000, seed=11, **kwargs):
    return synthetic_market(n=n, drift=0.0012, vol=0.008, adverse_prob=0.002, recovery_prob=0.02, seed=seed, **kwargs)


GOOD_SPEC = {"type": "sma_cross", "params": {"fast_window": 20, "slow_window": 60}}


def test_monte_carlo_deterministic_with_seed():
    rng_trades = np.array([0.01, -0.005, 0.02, 0.001, -0.002, 0.015] * 30)
    ok1, d1 = monte_carlo(rng_trades, ValidationPolicy(), seed=7)
    ok2, d2 = monte_carlo(rng_trades, ValidationPolicy(), seed=7)
    assert ok1 == ok2 and d1 == d2


def test_monte_carlo_rejects_negative_edge():
    losses = np.array([-0.01, -0.012, -0.008, 0.003, -0.011] * 40)  # esperanza negativa
    ok, details = monte_carlo(losses, ValidationPolicy(), seed=7)
    assert not ok
    assert details["p5_final_return"] < 0


def test_walk_forward_trend_strategy_passes():
    data = trending_data()
    grid = {"fast_window": [12.0, 20.0, 30.0], "slow_window": [40.0, 60.0, 90.0]}
    ok, details = walk_forward(data, GOOD_SPEC, grid, ValidationPolicy())
    assert ok, f"degradación {details}"


def test_param_sensitivity_detects_cliff():
    data = trending_data()
    ok, details = param_sensitivity(data, GOOD_SPEC, ValidationPolicy())
    assert ok, f"invertidos: {details}"


def test_param_sensitivity_rejects_inverted_base():
    data = trending_data()
    bad = {"type": "sma_cross", "params": {"fast_window": 60, "slow_window": 20}}  # invertido
    ok, _ = param_sensitivity(data, bad, ValidationPolicy())
    assert not ok


def test_cost_robustness_flags_thin_edge():
    data = trending_data(n=1200)
    ok, details = cost_robustness(data, GOOD_SPEC, ValidationPolicy())
    assert isinstance(ok, bool) and "total_return_x2_costs" in details


def test_regime_stress_needs_labels():
    data = trending_data()
    data_noregime = dataclasses_replace(data, regime=None)
    ok, details = regime_stress(data_noregime, GOOD_SPEC, ValidationPolicy())
    assert not ok and "provisional" in details["reason"]


def dataclasses_replace(data, **kw):
    import dataclasses

    return dataclasses.replace(data, **kw)


def test_portfolio_correlation():
    policy = ValidationPolicy()
    ok, d = portfolio_correlation(np.zeros(10), None, policy)
    assert ok  # portfolio vacío
    x = np.random.default_rng(1).standard_normal(100)
    ok, d = portfolio_correlation(x, x * 1.0, policy)
    assert not ok and d["correlation"] > 0.99


def test_battery_rejects_insufficient_trades():
    data = synthetic_market(n=200, seed=2)  # mercado corto: pocas operaciones
    battery = run_battery(data, GOOD_SPEC, ValidationPolicy())
    assert not battery.all_passed
    assert battery.details["reason"].startswith("B-4")


def test_battery_covers_all_six_points():
    data = trending_data()
    battery = run_battery(data, GOOD_SPEC, ValidationPolicy(), seed=42)
    assert set(battery.checks) == {
        "monte_carlo", "walk_forward", "regimen_stress",
        "param_sensitivity", "cost_robustness", "portfolio_correlation",
    }
