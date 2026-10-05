"""Sesión de paper trading con guardarraíles completos (Fase 4).

Extraída de `scripts/run_paper_day.py` para que el planificador diario la reutilice.
Flujo por señal: target position de la estrategia → gate pre-trade determinista
(K-1..K-4) → risk token → router (idempotencia E-5, frecuencia E-6) → broker de
papel → ledger. Ejecución en la apertura de la barra siguiente (anti look-ahead).
Nada aquí habla con un broker real: el contrato de `PaperBroker` es el que
implementará el adaptador de broker real.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np

from tf.dsl import generate_target_position
from tf.execution import ExecutionRouter, Ledger, PaperBroker, reconcile
from tf.risk import PortfolioState, PositionInfo, PreTradeGate, RiskLimits, StrategyContract

SECRET = "paper-day-fase4"  # de desarrollo; el secreto real va en el entorno del despliegue


def adverse_regime(close: np.ndarray, i: int, sma_window: int = 200) -> bool:
    """Régimen adverso determinista: precio por debajo de su media larga."""
    if i < sma_window:
        return False
    return bool(close[i] < close[i - sma_window : i + 1].mean())


def run_paper_session(
    entry: dict[str, Any],
    close: np.ndarray,
    open_: np.ndarray,
    ts: np.ndarray,
    n_bars: int,
    initial_equity: float = 100_000.0,
) -> dict[str, Any]:
    """Sesión de paper trading para una estrategia validada sobre la ventana final."""
    spec = entry["spec"]
    provisional = entry["final"] == "VALIDADA_PROVISIONAL"
    strategy_id = f"{spec['type']}-{hash(json.dumps(spec, sort_keys=True)) & 0xFFFF:04x}"

    limits = RiskLimits(
        max_risk_per_trade=0.02,
        max_daily_drawdown=0.02,
        max_total_drawdown=0.10,
        universe=["PAPER"],  # sesión de papel: un instrumento sintético por estrategia
    )
    gate = PreTradeGate(limits, secret=SECRET)
    ledger = Ledger()
    broker = PaperBroker()
    router = ExecutionRouter(broker, secret=SECRET, ledger=ledger, max_orders_per_minute=60)

    contract = StrategyContract(
        strategy_id=strategy_id,
        max_size=0.05,
        universe=["PAPER"],
        require_stop=True,
        only_normal_regime=provisional,
    )

    start = len(close) - n_bars
    state = PortfolioState(equity=initial_equity, equity_start_of_day=initial_equity, equity_peak=initial_equity)
    position: dict | None = None  # {frac, entry_price, equity_at_entry}
    events: list[tuple[str, str]] = []
    equity_curve: list[float] = []
    n_orders = n_rejected = 0

    # La señal de la barra i se ejecuta en la apertura de i+1 (anti look-ahead, igual que el motor).
    for i in range(start - 1, len(close) - 1):
        price = float(open_[i + 1])
        target = float(generate_target_position(spec, close[: i + 1])[-1])

        # Marking a mercado para los límites de drawdown.
        if position is not None:
            state.equity = position["equity_at_entry"] + position["frac"] * position["equity_at_entry"] * (
                price / position["entry_price"] - 1
            )
        state.equity_peak = max(state.equity_peak, state.equity)
        if state.equity < state.equity_start_of_day:
            state.equity_start_of_day = state.equity  # sesiones separadas por barra (demo)
        equity_curve.append(state.equity)

        wants_open = target > 0 and position is None
        wants_close = target == 0 and position is not None
        if not wants_open and not wants_close:
            continue

        side = "BUY" if wants_open else "SELL"
        size = contract.max_size if wants_open else position["frac"]
        request_id = f"{strategy_id}-{i}"
        request = {
            "request_id": request_id,
            "instrument": "PAPER",
            "side": side,
            "size": size,
            "stop_loss": price * 0.98 if wants_open else None,
        }
        regime = "adverso" if adverse_regime(close, i) else "normal"
        decision = gate.check(request, contract, state, regime=regime, now=float(ts[i + 1]))

        if not decision.authorized:
            n_rejected += 1
            events.append((f"bar {i}", f"{side} rechazado por el gate: {decision.reason}"))
            if wants_close:  # no pudimos cerrar por gate: forzado interno (fail-safe demo)
                position = None
                state.positions.pop("PAPER", None)
            continue

        try:
            order = {k: request[k] for k in ("request_id", "instrument", "side", "size")}
            if request["stop_loss"] is not None:
                order["stop_loss"] = request["stop_loss"]
            router.execute(order, decision.risk_token, price=price, now=float(ts[i + 1]))
            n_orders += 1
        except Exception as exc:  # token expirado, suspensión del router, etc.
            n_rejected += 1
            events.append((f"bar {i}", f"{side} rechazado por el router: {exc}"))
            continue

        if wants_open:
            events.append(
                (f"bar {i}", f"APERTURA {decision.verdict} {size:.2%} a {price:.2f} "
                 f"({'provisional: sin aperturas en régimen adverso' if provisional and regime == 'adverso' else regime})")
            )
            position = {"frac": decision.max_size or size, "entry_price": price, "equity_at_entry": state.equity}
            # El gate solo ve el portfolio vía PortfolioState: registrar la posición abierta.
            state.positions["PAPER"] = PositionInfo(instrument="PAPER", side="BUY", size=position["frac"])
        else:
            pnl = position["frac"] * position["equity_at_entry"] * (price / position["entry_price"] - 1)
            state.equity += pnl
            events.append((f"bar {i}", f"CIERRE a {price:.2f}: P&L {pnl:+,.0f}"))
            position = None
            state.positions.pop("PAPER", None)

    mismatches = reconcile(broker.positions, ledger.positions())
    return {
        "strategy_id": strategy_id,
        "spec": spec,
        "provisional": provisional,
        "n_orders": n_orders,
        "n_rejected": n_rejected,
        "equity_final": state.equity,
        "retorno": state.equity / initial_equity - 1,
        "equity_curve": equity_curve,
        "events": events,
        "reconcile": mismatches,
    }
