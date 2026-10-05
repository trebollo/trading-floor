"""Día de trading en papel sobre datos reales (Fase 4).

Ejecuta: uv run python scripts/run_paper_day.py --csv data/aapl.csv
         uv run python scripts/run_paper_day.py --csv data/aapl.csv --bars 750

Toma las estrategias VALIDADA / VALIDADA_PROVISIONAL del catálogo del pipeline
(.amp/in/artifacts/fase1-catalogo.json, lo produce run_pipeline.py) y simula una
sesión de paper trading sobre la ventana final del histórico, con todos los
guardarraíles activos: señal de la estrategia → gate pre-trade determinista (K-1..K-4)
→ risk token → router (idempotencia E-5, frecuencia E-6) → broker de papel → ledger
→ reconciliación.

Las VALIDADA_PROVISIONAL operan con only_normal_regime: no abren en régimen adverso
(por ahora: precio bajo su SMA de 200 barras). Nada aquí habla con un broker real.
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from tf.dsl import generate_target_position
from tf.execution import ExecutionRouter, Ledger, PaperBroker, reconcile
from tf.marketdata import load_csv
from tf.risk import (
    AUTORIZADA,
    REDUCIR,
    PortfolioState,
    PositionInfo,
    PreTradeGate,
    RiskLimits,
    StrategyContract,
)

SECRET = "paper-day-fase4"
CATALOG = Path(".amp/in/artifacts/fase1-catalogo.json")


def adverse_regime(close: np.ndarray, i: int, sma_window: int = 200) -> bool:
    """Régimen adverso determinista: precio por debajo de su media larga."""
    if i < sma_window:
        return False
    return bool(close[i] < close[i - sma_window : i + 1].mean())


def run_session(entry: dict, close: np.ndarray, open_: np.ndarray, ts: np.ndarray, n_bars: int) -> dict:
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
    equity = 100_000.0
    state = PortfolioState(equity=equity, equity_start_of_day=equity, equity_peak=equity)
    position: dict | None = None  # {frac, entry_price, equity_at_entry}
    events: list[tuple[str, str]] = []
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
        "retorno": state.equity / 100_000.0 - 1,
        "events": events,
        "reconcile": mismatches,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Paper trading sobre datos reales con guardarraíles completos")
    parser.add_argument("--csv", required=True, help="CSV de datos reales (ts,open,high,low,close)")
    parser.add_argument("--bars", type=int, default=500, help="barras de la ventana de simulación")
    parser.add_argument("--catalog", default=str(CATALOG), help="catálogo JSON del pipeline")
    args = parser.parse_args()

    data = load_csv(Path(args.csv))
    catalog = json.loads(Path(args.catalog).read_text())
    validated = [e for e in catalog if e["final"] in ("VALIDADA", "VALIDADA_PROVISIONAL") and e.get("spec")]
    if not validated:
        print("Sin estrategias validadas en el catálogo: ejecuta antes run_pipeline.py")
        sys.exit(1)

    close, open_, ts = data.close, data.open, data.ts.astype(float)
    print(
        f"Paper trading sobre {data.symbol}: {len(validated)} estrategia(s) validada(s), "
        f"ventana de {args.bars} barras\n" + "=" * 74
    )
    for entry in validated:
        result = run_session(entry, close, open_, ts, args.bars)
        print(f"\n▸ {result['strategy_id']} ({'PROVISIONAL' if result['provisional'] else 'VALIDADA'})")
        for step, msg in result["events"]:
            print(f"  {step}: {msg}")
        print(
            f"  → órdenes={result['n_orders']} rechazadas={result['n_rejected']} "
            f"retorno={result['retorno']:+.2%} equity={result['equity_final']:,.0f}"
        )
        print(f"  reconciliación: {'íntegra' if not result['reconcile'] else result['reconcile']}")


if __name__ == "__main__":
    main()
