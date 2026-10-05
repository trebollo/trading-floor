"""Tests de los contratos de mensajes (G2)."""

import pytest
from pydantic import ValidationError

from tf.contracts import (
    REGISTRY,
    Envelope,
    Actor,
    MessageValidationError,
    UnknownMessageType,
    validate_payload,
)


def test_registry_contains_core_pipeline_types():
    expected = {
        "strategy.proposal.v1",
        "strategy.spec.v1",
        "backtest.report.v1",
        "validation.verdict.v1",
        "order.request.v1",
        "risk.decision.v1",
        "agent.heartbeat.v1",
        "macro.regime.v1",
        "news.alert.v1",
    }
    assert expected <= set(REGISTRY)


def test_valid_payload_passes():
    payload = {
        "alert_id": "a1",
        "category": "TAIL_RISK",
        "confidence": 0.9,
        "source": "calendar",
        "quotes": ["nfp_date=2026-10-09"],
        "summary": "Evento de cola próximo",
    }
    model = validate_payload("news.alert.v1", payload)
    assert model.category == "TAIL_RISK"


def test_invalid_payload_raises_message_validation_error():
    with pytest.raises(MessageValidationError):
        validate_payload("backtest.report.v1", {"verdict": "VALOR_RARO"})


def test_unknown_type_rejected():
    with pytest.raises(UnknownMessageType):
        validate_payload("trading.gurú.v99", {})


def test_envelope_requires_registered_type():
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="no registrado"):
        Envelope(
            type="no.existe.v1",
            actor=Actor(agent="a", role="r", department="d"),
            payload={},
        )


def test_envelope_is_frozen():
    env = Envelope(
        type="directive.new.v1",
        actor=Actor(agent="a", role="r", department="d"),
        payload={"directive_id": "d1", "text": "t", "scope": "research"},
    )
    with pytest.raises(ValidationError):
        env.payload = {}
