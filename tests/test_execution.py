"""Tests de Execution & Ops: token, idempotencia, frecuencia, auto-suspensión,
ledger y reconciliación (spec 05)."""

import time

import pytest

from tf.execution import (
    BrokerRejected,
    ExecutionRouter,
    Ledger,
    PaperBroker,
    RouterSuspended,
    reconcile,
)
from tf.risk import issue_risk_token, RiskTokenError

SECRET = "router-secret"


def make_router(**kwargs) -> ExecutionRouter:
    return ExecutionRouter(PaperBroker(), secret=SECRET, **kwargs)


def make_request(request_id="r1", instrument="SYNTH", side="BUY", size=0.01):
    return {"request_id": request_id, "instrument": instrument, "side": side, "size": size}


def make_token(request_id="r1", instrument="SYNTH", side="BUY", max_size=0.01, now=1000.0, ttl=60):
    return issue_risk_token(request_id, "s1", instrument, side, max_size, SECRET, ttl, now=now)


NOW = 1000.0


# ---------------------------------------------------------------------------


def test_valid_order_fills_and_ledgers():
    router = make_router()
    fill = router.execute(make_request(), make_token(), price=100.0, now=NOW)
    assert fill.size == 0.01 and fill.price > 100.0  # slippage de compra
    assert len(router.ledger.entries) == 1
    assert router.ledger.positions()["SYNTH"]["side"] == "BUY"


def test_order_without_valid_token_rejected():
    router = make_router()
    with pytest.raises(RiskTokenError):
        router.execute(make_request(), "token-basura", price=100.0, now=NOW)
    assert router.broker.fills == []


def test_order_exceeding_token_max_size_is_clamped():
    """REDUCIR: el router ejecuta al tamaño autorizado del token, nunca por encima."""
    router = make_router()
    fill = router.execute(make_request(size=0.05), make_token(max_size=0.01), price=100.0, now=NOW)
    assert fill.size == 0.01
    assert len(router.broker.fills) == 1


def test_expired_token_rejected_and_counts_toward_suspension():
    router = make_router(max_consecutive_rejects=2)
    with pytest.raises(RiskTokenError, match="expirado"):
        router.execute(make_request(), make_token(now=1000.0, ttl=10), price=100.0, now=1020.0)  # exp=1010
    with pytest.raises(RiskTokenError):
        router.execute(make_request("r2"), make_token("r2", now=1000.0, ttl=10), price=100.0, now=1020.0)
    assert router.suspended  # E-7: auto-suspensión
    with pytest.raises(RouterSuspended):
        router.execute(make_request("r3"), make_token("r3"), price=100.0, now=NOW)


def test_token_mismatched_to_request_rejected():
    router = make_router()
    with pytest.raises(RiskTokenError, match="corresponde"):
        router.execute(make_request("otro-id"), make_token("r1"), price=100.0, now=NOW)


def test_idempotency_blocks_duplicate_request_id():
    router = make_router()
    router.execute(make_request(), make_token(), price=100.0, now=NOW)
    with pytest.raises(RuntimeError, match="E-5"):
        router.execute(make_request(), make_token(), price=100.0, now=NOW)
    assert len(router.broker.fills) == 1


def test_frequency_limit_blocks_flood():
    router = make_router(max_orders_per_minute=2)
    for i in range(2):
        router.execute(make_request(f"r{i}"), make_token(f"r{i}"), price=100.0, now=NOW + i)
    with pytest.raises(RuntimeError, match="E-6"):
        router.execute(make_request("r9"), make_token("r9"), price=100.0, now=NOW + 3)
    # Pasado el minuto, se libera (token emitido con su propio now).
    router.execute(make_request("r10"), make_token("r10", now=NOW + 61), price=100.0, now=NOW + 61)


def test_broker_rejections_suspend_router():
    router = make_router(max_consecutive_rejects=3)
    router.broker.reject_next_orders = True
    for i in range(3):
        with pytest.raises(BrokerRejected):
            router.execute(make_request(f"r{i}"), make_token(f"r{i}"), price=100.0, now=NOW)
    assert router.suspended


def test_reconciliation_detects_mismatch():
    broker = PaperBroker()
    ledger = Ledger()
    router = ExecutionRouter(broker, secret=SECRET, ledger=ledger)
    router.execute(make_request(), make_token(), price=100.0, now=NOW)

    # Sin manipulación: sin discrepancias.
    assert reconcile(broker.positions, ledger.positions()) == []

    # Un fill "fantasma" en el broker que el ledger no conoce: discrepancia (E-8).
    broker.place("ord-fantasma", "OTRO", "BUY", 0.02, 50.0)
    issues = reconcile(broker.positions, ledger.positions())
    assert len(issues) == 1 and "OTRO" in issues[0]


def test_ledger_replays_positions_from_events():
    ledger = Ledger()
    broker = PaperBroker()
    fill = broker.place("o1", "SYNTH", "BUY", 0.01, 100.0)
    ledger.append_fill(fill, "s1")
    fill2 = broker.place("o2", "SYNTH", "SELL", 0.01, 102.0)
    ledger.append_fill(fill2, "s1")
    assert ledger.positions() == {}  # posición cerrada: replay correcto
