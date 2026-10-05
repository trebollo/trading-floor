"""Batería canónica de validación (spec 03) — 100 % determinista.

Los 6 puntos canónicos: monte_carlo, walk_forward, regimen_stress, param_sensitivity,
cost_robustness, portfolio_correlation. Los umbrales vienen de configuración (política
del CEO), nunca de decisiones de los agentes (V-1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from tf.dsl import SpecError, generate_target_position
from tf.engine import CostModel, DEFAULT_COSTS, run_backtest
from tf.marketdata import MarketData


@dataclass(frozen=True)
class ValidationPolicy:
    """Umbrales de la batería. Solo el CEO los cambia (K-5)."""

    mc_iterations: int = 10_000
    mc_p5_final_return: float = 0.0        # el P5 del retorno total debe ser > 0
    mc_p5_max_drawdown: float = 0.35       # y el P5 (peor) del drawdown debe caber aquí
    wf_folds: int = 4
    wf_min_degradation: float = 0.5        # oos/in-sample >= 0.5
    sensitivity_delta: float = 0.2         # ±20 %
    min_trades: int = 100                  # B-4
    adverse_regime_p25_return: float = 0.0 # P25 del retorno en régimen adverso
    max_portfolio_correlation: float = 0.7


BATTERY_POINTS = (
    "monte_carlo",
    "walk_forward",
    "regimen_stress",
    "param_sensitivity",
    "cost_robustness",
    "portfolio_correlation",
)


@dataclass
class BatteryResult:
    checks: dict[str, bool] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def all_passed(self) -> bool:
        return all(self.checks.values())


# ---------------------------------------------------------------------------
# Punto 1: Monte Carlo — permutación de operaciones + bootstrap de bloques
# ---------------------------------------------------------------------------


def monte_carlo(
    trade_returns: np.ndarray,
    policy: ValidationPolicy,
    seed: int = 7,
) -> tuple[bool, dict[str, Any]]:
    rng = np.random.default_rng(seed)
    trades = np.asarray(trade_returns, dtype=float)
    n = len(trades)
    finals = np.empty(policy.mc_iterations)
    drawdowns = np.empty(policy.mc_iterations)
    block = max(5, n // 20)
    for it in range(policy.mc_iterations):
        if it % 2 == 0:  # permutación
            sample = rng.permutation(trades)
        else:            # bootstrap de bloques
            starts = rng.integers(0, max(n - block, 1), size=max(n // block, 1))
            sample = np.concatenate([trades[s : s + block] for s in starts])[:n]
        equity = np.cumprod(1.0 + sample)
        peak = np.maximum.accumulate(equity)
        finals[it] = equity[-1] - 1.0
        drawdowns[it] = float(np.max(1.0 - equity / peak)) if len(equity) else 1.0
    p5_final = float(np.percentile(finals, 5))
    p5_dd = float(np.percentile(drawdowns, 95))  # el 95 % de los escenarios tiene dd mejor
    passed = p5_final > policy.mc_p5_final_return and p5_dd <= policy.mc_p5_max_drawdown
    details = {"p5_final_return": p5_final, "p95_max_drawdown": p5_dd}
    return passed, details


# ---------------------------------------------------------------------------
# Punto 2: Walk-forward — degradación in-sample vs out-of-sample
# ---------------------------------------------------------------------------


def walk_forward(
    data: MarketData,
    spec: dict,
    param_grid: dict[str, list[float]],
    policy: ValidationPolicy,
    costs: CostModel = DEFAULT_COSTS,
) -> tuple[bool, dict[str, Any]]:
    """Divide en K folds: optimiza por Sharpe en train, evalúa en test, compara."""
    n = len(data)
    fold_len = n // (policy.wf_folds + 1)
    ratios: list[float] = []
    for k in range(policy.wf_folds):
        train_end = fold_len * (k + 1)
        train = _slice(data, 0, train_end)
        test = _slice(data, train_end, min(train_end + fold_len, n))
        best_sharpe, best_params = -np.inf, spec["params"]
        for combo in _grid(param_grid):
            try:
                res = run_backtest(train, {**spec, "params": combo}, costs)
                sharpe = res.metrics.get("sharpe", -np.inf) if res.metrics else -np.inf
            except SpecError:
                continue
            if sharpe > best_sharpe:
                best_sharpe, best_params = sharpe, combo
        oos = run_backtest(test, {**spec, "params": best_params}, costs)
        oos_sharpe = oos.metrics.get("sharpe", 0.0)
        ratios.append(min(oos_sharpe / best_sharpe, 1.0) if best_sharpe > 0 else 0.0)
    degradation = float(np.mean(ratios))
    passed = degradation >= policy.wf_min_degradation
    return passed, {"folds": len(ratios), "fold_ratios": ratios, "degradation_ratio": degradation}


def _slice(data: MarketData, start: int, end: int) -> MarketData:
    regime = data.regime[start:end] if data.regime is not None else None
    return MarketData(
        symbol=data.symbol, ts=data.ts[start:end], open=data.open[start:end],
        high=data.high[start:end], low=data.low[start:end], close=data.close[start:end],
        regime=regime,
    )


def _grid(param_grid: dict[str, list[float]]) -> list[dict[str, float]]:
    keys = list(param_grid)
    combos: list[dict[str, float]] = [{}]
    for key in keys:
        combos = [c | {key: v} for c in combos for v in param_grid[key]]
    return combos


# ---------------------------------------------------------------------------
# Punto 3: estrés de régimen
# ---------------------------------------------------------------------------


def regime_stress(
    data: MarketData,
    spec: dict,
    policy: ValidationPolicy,
    costs: CostModel = DEFAULT_COSTS,
) -> tuple[bool, dict[str, Any]]:
    if data.regime is None:
        return False, {"reason": "sin etiquetas de régimen (V-8: veredicto máximo provisional)"}
    res = run_backtest(data, spec, costs)
    adverse_mask = (data.regime == 1) & (res.position != 0)
    if adverse_mask.sum() < 5:
        return True, {"adverse_bars": int(adverse_mask.sum()), "note": "exposición adversa mínima"}
    # Retornos por barra en barras adversas con posición abierta
    bar_ret = np.concatenate(([0.0], data.open[1:] / data.open[:-1] - 1.0))
    adverse_returns = res.position * bar_ret
    sel = adverse_returns[(data.regime == 1) & (res.position != 0)]
    p25 = float(np.percentile(sel, 25))
    cum_adverse = float(np.prod(1.0 + sel) - 1.0) if len(sel) else 0.0
    passed = cum_adverse >= policy.adverse_regime_p25_return
    return passed, {"p25_adverse_bar_return": p25, "cum_adverse_return": cum_adverse, "adverse_bars": int(sel.size)}


# ---------------------------------------------------------------------------
# Punto 4: sensibilidad de parámetros (± delta)
# ---------------------------------------------------------------------------


def param_sensitivity(
    data: MarketData,
    spec: dict,
    policy: ValidationPolicy,
    costs: CostModel = DEFAULT_COSTS,
) -> tuple[bool, dict[str, Any]]:
    try:
        base = run_backtest(data, spec, costs)
        if base.metrics["total_return"] <= 0:
            return False, {"reason": "la base ya no es rentable"}
        inverted = []
        for key, value in spec["params"].items():
            for factor in (1 - policy.sensitivity_delta, 1 + policy.sensitivity_delta):
                perturbed = {**spec["params"], key: value * factor}
                try:
                    res = run_backtest(data, {**spec, "params": perturbed}, costs)
                except SpecError:
                    continue  # combinación inválida (p. ej. fast>=slow): no cuenta como inversión
                if res.metrics["total_return"] < 0:
                    inverted.append(f"{key}×{factor:.2f}")
    except SpecError as exc:
        return False, {"reason": f"spec inválido: {exc}"}
    passed = not inverted
    return passed, {"inverted_params": inverted}


# ---------------------------------------------------------------------------
# Punto 5: robustez de costes (slippage ×2)
# ---------------------------------------------------------------------------


def cost_robustness(
    data: MarketData,
    spec: dict,
    policy: ValidationPolicy,
    costs: CostModel = DEFAULT_COSTS,
) -> tuple[bool, dict[str, Any]]:
    res = run_backtest(data, spec, costs.doubled())
    total = res.metrics["total_return"]
    return total > 0, {"total_return_x2_costs": total}


# ---------------------------------------------------------------------------
# Punto 6: correlación con el portfolio vivo
# ---------------------------------------------------------------------------


def portfolio_correlation(
    strategy_bar_returns: np.ndarray,
    portfolio_bar_returns: np.ndarray | None,
    policy: ValidationPolicy,
) -> tuple[bool, dict[str, Any]]:
    if portfolio_bar_returns is None or len(portfolio_bar_returns) == 0:
        return True, {"note": "portfolio vacío: sin correlación que penalizar"}
    n = min(len(strategy_bar_returns), len(portfolio_bar_returns))
    corr = float(np.corrcoef(strategy_bar_returns[-n:], portfolio_bar_returns[-n:])[0, 1])
    return abs(corr) <= policy.max_portfolio_correlation, {"correlation": corr}


# ---------------------------------------------------------------------------
# Batería completa
# ---------------------------------------------------------------------------


def run_battery(
    data: MarketData,
    spec: dict,
    policy: ValidationPolicy = ValidationPolicy(),
    portfolio_returns: np.ndarray | None = None,
    seed: int = 7,
) -> BatteryResult:
    """Ejecuta la batería canónica completa. Invariable: no se salta ningún punto (V-1)."""
    result = BatteryResult()
    base = run_backtest(data, spec)

    result.details["minimum_stats"] = {
        "n_trades": base.metrics["n_trades"],
        "required": policy.min_trades,
    }
    if base.metrics["n_trades"] < policy.min_trades:
        result.checks = {point: False for point in BATTERY_POINTS}
        result.details["reason"] = "B-4: mínimo estadístico no alcanzado"
        return result

    mc_ok, mc_details = monte_carlo(base.trade_returns, policy, seed=seed)
    result.checks["monte_carlo"] = mc_ok
    result.details["monte_carlo"] = mc_details

    wf_ok, wf_details = walk_forward(
        data, spec, _default_grid(spec), policy
    )
    result.checks["walk_forward"] = wf_ok
    result.details["walk_forward"] = wf_details

    rs_ok, rs_details = regime_stress(data, spec, policy)
    result.checks["regimen_stress"] = rs_ok
    result.details["regimen_stress"] = rs_details

    ps_ok, ps_details = param_sensitivity(data, spec, policy)
    result.checks["param_sensitivity"] = ps_ok
    result.details["param_sensitivity"] = ps_details

    cr_ok, cr_details = cost_robustness(data, spec, policy)
    result.checks["cost_robustness"] = cr_ok
    result.details["cost_robustness"] = cr_details

    pc_ok, pc_details = portfolio_correlation(base.trade_returns, portfolio_returns, policy)
    result.checks["portfolio_correlation"] = pc_ok
    result.details["portfolio_correlation"] = pc_details

    assert set(result.checks) == set(BATTERY_POINTS), "batería incompleta (V-1)"
    return result


def _default_grid(spec: dict) -> dict[str, list[float]]:
    return {
        key: [value * f for f in (0.6, 0.8, 1.0, 1.2, 1.4)]
        for key, value in spec["params"].items()
        if isinstance(value, (int, float))
    }
