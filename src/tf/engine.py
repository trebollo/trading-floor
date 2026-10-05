"""Motor de backtest vectorizado, determinista y sin look-ahead por construcción.

Reglas del motor (B-1, B-5): la señal de la barra i se ejecuta en la apertura de la
barra i+1 (shift), y los costes se aplican sobre cada cambio de posición. Ningún
agente puede modificar estas reglas por corrida.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from tf.dsl import SpecError, generate_target_position
from tf.marketdata import MarketData


@dataclass(frozen=True)
class CostModel:
    commission_rate: float = 0.0002   # 2 bps por lado
    slippage_rate: float = 0.0005     # 5 bps por cambio de posición (conservador)

    def doubled(self) -> "CostModel":
        return CostModel(commission_rate=self.commission_rate, slippage_rate=self.slippage_rate * 2)


DEFAULT_COSTS = CostModel()


@dataclass
class BacktestResult:
    equity: np.ndarray            # curva de capital (base 1.0)
    position: np.ndarray          # posición efectiva por barra (tras shift)
    trade_returns: np.ndarray     # retorno por operación cerrada
    metrics: dict[str, float] = field(default_factory=dict)

    def compute_metrics(self, periods_per_year: int = 252) -> "BacktestResult":
        eq = self.equity
        n = len(eq)
        total_return = float(eq[-1] / eq[0] - 1.0)
        years = max(n / periods_per_year, 1e-9)
        cagr = float((eq[-1] / eq[0]) ** (1 / years) - 1.0) if eq[-1] > 0 else -1.0
        bar_returns = np.diff(eq) / eq[:-1]
        std = float(np.std(bar_returns, ddof=1)) if len(bar_returns) > 1 else 0.0
        mean = float(np.mean(bar_returns))
        sharpe = float(mean / std * np.sqrt(periods_per_year)) if std > 0 else 0.0
        peak = np.maximum.accumulate(eq)
        max_dd = float(np.max(1.0 - eq / peak)) if len(eq) else 0.0
        wins = self.trade_returns[self.trade_returns > 0]
        losses = self.trade_returns[self.trade_returns <= 0]
        gross_win = float(wins.sum()) if len(wins) else 0.0
        gross_loss = float(-losses.sum()) if len(losses) else 0.0
        profit_factor = float(gross_win / gross_loss) if gross_loss > 0 else float("inf") if gross_win > 0 else 0.0
        self.metrics = {
            "total_return": total_return,
            "cagr": cagr,
            "sharpe": sharpe,
            "max_drawdown": max_dd,
            "profit_factor": min(profit_factor, 99.0),
            "n_trades": float(len(self.trade_returns)),
            "exposure": float(np.mean(self.position != 0)),
        }
        return self


def run_backtest(
    data: MarketData,
    spec: dict,
    costs: CostModel = DEFAULT_COSTS,
    initial_capital: float = 1.0,
) -> BacktestResult:
    """Corrida vectorizada. Ejecución en la barra siguiente (sin look-ahead)."""
    data.validate()
    try:
        target = generate_target_position(spec, data.close)
    except SpecError:
        raise
    # Anti look-ahead: la decisión tomada con datos de la barra i solo afecta a i+1.
    effective = np.concatenate(([0.0], target[:-1]))

    # La posición efectiva i se mantiene desde open[i] y cobra el retorno open i→i+1.
    n = len(effective)
    bar_return = np.zeros(n)
    bar_return[1:] = data.open[1:] / data.open[:-1] - 1.0
    position_change = np.abs(np.diff(effective, prepend=0.0))
    # Coste fraccional por barra: solo cuando cambia la posición (entrada/salida/reajuste).
    cost_per_bar = position_change * (costs.commission_rate + costs.slippage_rate)
    strategy_return = effective * bar_return - cost_per_bar
    strategy_return[0] = 0.0

    equity = initial_capital * np.cumprod(1.0 + strategy_return)
    trade_returns = _closed_trades(effective, strategy_return)
    return BacktestResult(equity=equity, position=effective, trade_returns=trade_returns).compute_metrics()


def _closed_trades(position: np.ndarray, strategy_return: np.ndarray) -> np.ndarray:
    """Retorno acumulado de cada operación cerrada (entrada→salida)."""
    returns: list[float] = []
    acc = 0.0
    in_trade = False
    for i, pos in enumerate(position):
        if pos > 0 and not in_trade:
            in_trade = True
            acc = 0.0
        if in_trade:
            acc += strategy_return[i]
            if pos == 0.0 or i == len(position) - 1:
                returns.append(acc)
                in_trade = False
    return np.array(returns, dtype=float)
