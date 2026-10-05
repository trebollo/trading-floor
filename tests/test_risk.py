"""Tests del Risk Department: gate fail-closed, límites y tokens firmados."""

import pytest

from tf.risk import (
    AUTORIZADA,
    RECHAZADA,
    REDUCIR,
    GateDecision,
    PortfolioState,
    PositionInfo,
    PreTradeGate,
    RiskLimits,
    RiskTokenError,
    StrategyContract,
    issue_risk_token,
    verify_risk_token,
)

SECRET = "test-secret"


def make_gate(**limits) -> PreTradeGate:
    return PreTradeGate(RiskLimits(**limits), secret=SECRET)


def make_state(equity=100_000.0, start=None, peak=None, positions=None) -> PortfolioState:
    return PortfolioState(
        equity=equity,
        equity_start_of_day=start if start is not None else equity,
        equity_peak=peak if peak is not None else equity,
        positions=positions or {},
    )


CONTRACT = StrategyContract(strategy_id="s1", max_size=0.02, universe=["SYNTH"])
ORDER = {"request_id": "r1", "instrument": "SYNTH", "side": "BUY", "size": 0.01, "stop_loss": 95.0}


# ---------------------------------------------------------------------------
# Tokens firmados (K-3)
# ---------------------------------------------------------------------------


def test_token_roundtrip_and_expiry():
    token = issue_risk_token("r1", "s1", "SYNTH", "BUY", 0.01, SECRET, ttl_seconds=60, now=1000.0)
    payload = verify_risk_token(token, SECRET, now=1050.0)
    assert payload["max_size"] == 0.01
    with pytest.raises(RiskTokenError, match="expirado"):
        verify_risk_token(token, SECRET, now=1061.0)


def test_tampered_token_rejected():
    token = issue_risk_token("r1", "s1", "SYNTH", "BUY", 0.01, SECRET, ttl_seconds=60, now=1000.0)
    evil = token[:-8] + ("0" * 8)  # manipular la firma
    with pytest.raises(RiskTokenError, match="firma inválida"):
        verify_risk_token(evil, SECRET, now=1001.0)


def test_wrong_secret_rejected():
    token = issue_risk_token("r1", "s1", "SYNTH", "BUY", 0.01, SECRET, ttl_seconds=60, now=1000.0)
    with pytest.raises(RiskTokenError):
        verify_risk_token(token, "otro-secreto", now=1001.0)


# ---------------------------------------------------------------------------
# Gate: fail-closed (K-2)
# ---------------------------------------------------------------------------


def test_missing_contract_is_technical_rejection():
    gate = make_gate()
    d = gate.check(ORDER, contract=None, state=make_state())
    assert d.verdict == RECHAZADA and d.technical


def test_missing_state_is_technical_rejection():
    gate = make_gate()
    d = gate.check(ORDER, contract=CONTRACT, state=None)
    assert d.verdict == RECHAZADA and d.technical


def test_gate_without_secret_does_not_start():
    with pytest.raises(ValueError, match="secreto"):
        PreTradeGate(RiskLimits(), secret="")


# ---------------------------------------------------------------------------
# Gate: vetos absolutos
# ---------------------------------------------------------------------------


def test_instrument_outside_universe_rejected():
    gate = make_gate()
    d = gate.check({**ORDER, "instrument": "OTRO"}, contract=CONTRACT, state=make_state())
    assert d.verdict == RECHAZADA and "universo" in d.reason


def test_missing_stop_rejected_when_contract_requires_it():
    gate = make_gate()
    d = gate.check({**ORDER, "stop_loss": None}, contract=CONTRACT, state=make_state())
    assert d.verdict == RECHAZADA and "stop" in d.reason


def test_provisional_contract_blocked_in_adverse_regime():
    gate = make_gate()
    contract = StrategyContract(strategy_id="s2", max_size=0.02, universe=["SYNTH"], only_normal_regime=True)
    d = gate.check(ORDER, contract=contract, state=make_state(), regime="adverso")
    assert d.verdict == RECHAZADA and "adverso" in d.reason


# ---------------------------------------------------------------------------
# Gate: reducción por límites
# ---------------------------------------------------------------------------


def test_oversized_order_reduced_not_rejected():
    gate = make_gate(max_risk_per_trade=0.005)
    big = {**ORDER, "size": 0.05}
    d = gate.check(big, contract=CONTRACT, state=make_state())
    assert d.verdict == REDUCIR
    assert d.max_size == pytest.approx(0.005)
    assert d.risk_token is not None


def test_instrument_exposure_cap_reduces():
    gate = make_gate(max_exposure_per_instrument=0.10, max_risk_per_trade=0.02)
    state = make_state(positions={"SYNTH": PositionInfo("SYNTH", "BUY", 0.09)})
    order = {**ORDER, "size": 0.03}  # pide más del hueco disponible (0.01)
    d = gate.check(order, contract=CONTRACT, state=state)
    assert d.verdict == REDUCIR and d.max_size == pytest.approx(0.01)


def test_exhausted_exposure_rejects():
    gate = make_gate(max_exposure_per_instrument=0.10)
    state = make_state(positions={"SYNTH": PositionInfo("SYNTH", "BUY", 0.10)})
    d = gate.check(ORDER, contract=CONTRACT, state=state)
    assert d.verdict == RECHAZADA and "exposición" in d.reason


# ---------------------------------------------------------------------------
# Gate: modo solo-cierre por drawdown
# ---------------------------------------------------------------------------


def test_daily_drawdown_triggers_close_only():
    gate = make_gate(max_daily_drawdown=0.03)
    state = make_state(equity=95_000.0, start=100_000.0)
    d = gate.check(ORDER, contract=CONTRACT, state=state)  # apertura nueva
    assert d.verdict == RECHAZADA and "solo-cierre" in d.reason
    # Pero permitir cerrar: posición larga abierta, orden SELL.
    state.positions["SYNTH"] = PositionInfo("SYNTH", "BUY", 0.01)
    close_order = {**ORDER, "side": "SELL", "size": 0.01}
    d2 = gate.check(close_order, contract=CONTRACT, state=state)
    assert d2.verdict == AUTORIZADA


def test_total_drawdown_triggers_close_only():
    gate = make_gate(max_total_drawdown=0.10)
    state = make_state(equity=85_000.0, peak=100_000.0)
    d = gate.check(ORDER, contract=CONTRACT, state=state)
    assert d.verdict == RECHAZADA and "solo-cierre" in d.reason


# ---------------------------------------------------------------------------
# Gate: correlación y apalancamiento
# ---------------------------------------------------------------------------


def test_correlated_group_limit():
    gate = make_gate(max_open_positions_same_group=1, max_risk_per_trade=0.02)
    state = make_state(positions={"OTRO": PositionInfo("OTRO", "BUY", 0.01, group="equities")})
    synth_contract = StrategyContract(strategy_id="s1", max_size=0.02, universe=["SYNTH"])
    d = gate.check(ORDER, contract=synth_contract, state=state)
    # SYNTH no tiene posición y cae en grupo default; OTRO está en equities: no bloquea.
    assert d.verdict == AUTORIZADA


def test_authorized_decision_carries_token_with_max_size():
    gate = make_gate(max_risk_per_trade=0.02)
    d = gate.check(ORDER, contract=CONTRACT, state=make_state(), now=1000.0)
    assert d.verdict == AUTORIZADA and d.authorized
    payload = verify_risk_token(d.risk_token, SECRET, now=1000.0)
    assert payload["max_size"] == pytest.approx(0.01)
