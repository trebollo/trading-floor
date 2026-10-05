"""Demo Fase 2: día de trading en papel con todos los guardarraíles activos.

Ejecuta: uv run python scripts/run_trading_day.py

Flujo por decisión: señal de la estrategia validada → order.request → gate pre-trade
(determinista) → risk_token firmado → execution router (verifica token, idempotencia,
frecuencia) → broker de papel → ledger → reconciliación.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from tf.execution import ExecutionRouter, Ledger, PaperBroker, reconcile
from tf.marketdata import synthetic_market
from tf.risk import (
    AUTORIZADA,
    REDUCIR,
    RECHAZADA,
    PortfolioState,
    PositionInfo,
    PreTradeGate,
    RiskLimits,
    StrategyContract,
)

SECRET = "demo-secret-fase2"


def main() -> None:
    data = synthetic_market(n=600, seed=99)
    limits = RiskLimits(max_risk_per_trade=0.01, max_daily_drawdown=0.02, max_total_drawdown=0.10)
    gate = PreTradeGate(limits, secret=SECRET)
    broker = PaperBroker()
    router = ExecutionRouter(broker, secret=SECRET, ledger=Ledger(), max_orders_per_minute=100)

    contract = StrategyContract(
        strategy_id="momentum-validated", max_size=0.02, universe=["SYNTH"], require_stop=True
    )

    equity = 100_000.0
    equity_peak = equity
    start_of_day = equity
    state = PortfolioState(equity=equity, equity_start_of_day=start_of_day, equity_peak=equity_peak)
    ts = 1000.0

    scenarios = [
        ("Apertura normal", {"request_id": "d1", "instrument": "SYNTH", "side": "BUY", "size": 0.008, "stop_loss": 95.0}),
        ("Sin stop (violación E-4)", {"request_id": "d2", "instrument": "SYNTH", "side": "BUY", "size": 0.005, "stop_loss": None}),
        ("Tamaño excesivo (REDUCIR)", {"request_id": "d3", "instrument": "SYNTH", "side": "BUY", "size": 0.08, "stop_loss": 95.0}),
        ("Instrumento fuera del universo", {"request_id": "d4", "instrument": "TSLA", "side": "BUY", "size": 0.005, "stop_loss": 95.0}),
        ("Reintento con mismo id (E-5)", {"request_id": "d1", "instrument": "SYNTH", "side": "BUY", "size": 0.008, "stop_loss": 95.0}),
        ("Crash: drawdown diario superado", None),
        ("Apertura en modo solo-cierre", {"request_id": "d5", "instrument": "SYNTH", "side": "BUY", "size": 0.005, "stop_loss": 95.0}),
        ("Cierre de posición en modo solo-cierre", {"request_id": "d6", "instrument": "SYNTH", "side": "SELL", "size": 0.008, "stop_loss": None}),
        ("Token expirado (E-2)", "EXPIRED"),
    ]

    print("Día de trading en papel — gate determinista + router + broker de papel\n" + "=" * 74)
    for name, order in scenarios:
        print(f"\n▸ {name}")
        if order is None:  # simulación de crash: cae el equity 2.5% intradía
            state.equity *= 0.975
            print(f"  [mercado] equity cae a {state.equity:,.0f} (DD diario {state.daily_drawdown:.2%})")
            continue
        if order == "EXPIRED":
            from tf.risk import issue_risk_token
            stale_token = issue_risk_token("d9", contract.strategy_id, "SYNTH", "BUY", 0.005, SECRET, 5, now=ts)
            ts += 100  # el token caduca antes de llegar al router
            try:
                router.execute({"request_id": "d9", "instrument": "SYNTH", "side": "BUY", "size": 0.005}, stale_token, price=data.open[-1], now=ts)
                print("  ✗ el router aceptó un token expirado: BUG")
            except Exception as exc:
                print(f"  router: RECHAZADA ({exc})")
            continue

        # 1) Gate pre-trade determinista
        price = float(data.open[min(int(ts) % len(data), len(data) - 1)])
        decision = gate.check(order, contract, state, regime="normal", now=ts)
        print(f"  gate: {decision.verdict} — {decision.reason}")
        if not decision.authorized:
            continue

        # 2) Router: verifica token, idempotencia, frecuencia → broker → ledger
        if name.startswith("Reintento"):
            try:
                router.execute(order, decision.risk_token, price=price, now=ts)
                print("  ✗ el router aceptó un id duplicado: BUG")
            except RuntimeError as exc:
                print(f"  router: bloqueado ({exc})")
            continue
        fill = router.execute(order, decision.risk_token, price=price, now=ts, ts=ts)
        print(f"  router: enviada → fill {fill.instrument} {fill.side} {fill.size:.4f} @ {fill.price:.2f}")
        # Sincroniza el estado del portfolio con el broker (posiciones reales).
        state.positions[fill.instrument] = PositionInfo(
            fill.instrument, fill.side, state.positions.get(fill.instrument, PositionInfo(fill.instrument, fill.side, 0.0)).size
            + (fill.size if state.positions.get(fill.instrument, None) is None or state.positions[fill.instrument].side == fill.side else -fill.size)
        )
        if state.positions[fill.instrument].size <= 1e-9:
            del state.positions[fill.instrument]
        ts += 1

    # Reconciliación final
    print("\n" + "=" * 74)
    issues = reconcile(broker.positions, router.ledger.positions())
    print(f"Reconciliación: {'sin discrepancias ✓' if not issues else issues}")
    print(f"Posiciones del broker: {broker.positions}")
    print(f"Ledger: {len(router.ledger.entries)} asientos")


if __name__ == "__main__":
    main()
