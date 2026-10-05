"""Tests del bus (G2: validación en el borde) y del Model Gateway."""

from pathlib import Path

import pytest
import yaml

from tf.bus import InMemoryBus
from tf.contracts import Actor, Envelope, MessageValidationError
from tf.gateway import GatewayConfig, ModelGateway


def make_actor() -> Actor:
    return Actor(agent="a", role="r", department="d")


# ---------------------------------------------------------------------------
# Bus
# ---------------------------------------------------------------------------


def test_bus_delivers_valid_message_to_subscribers():
    bus = InMemoryBus()
    received = []
    bus.subscribe("agent.heartbeat.v1", lambda env: received.append(env))
    bus.publish_raw(
        "agent.heartbeat.v1",
        {"agent": "x", "department": "d", "status": "up"},
        actor=make_actor(),
    )
    assert len(received) == 1
    assert bus.published[0].payload["agent"] == "x"


def test_bus_rejects_invalid_payload_at_the_edge():
    bus = InMemoryBus()
    with pytest.raises(MessageValidationError):
        bus.publish(
            Envelope(
                type="news.alert.v1",
                actor=make_actor(),
                payload={"category": "no_existe"},  # faltan campos y categoría inválida
            )
        )
    assert bus.published == []


def test_bus_rejects_unknown_type():
    bus = InMemoryBus()
    with pytest.raises(ValueError):
        bus.publish_raw("tipo.inexistente.v1", {}, actor=make_actor())


# ---------------------------------------------------------------------------
# Model Gateway
# ---------------------------------------------------------------------------

VALID_CONFIG = {
    "models": {
        "jev": {"kind": "evaluator", "id": "typesafe-ai/jev"},
        "strong": {"kind": "generative", "tier": "premium"},
        "lite": {"kind": "generative", "tier": "standard"},
    },
    "agents": {
        "macro-analyst": {"generative": "lite", "decisions": "jev"},
        "research-hypothesis": {"generative": "strong", "decisions": "jev"},
    },
}


def test_valid_config_resolves_models():
    gw = ModelGateway(GatewayConfig.model_validate(VALID_CONFIG))
    assert gw.resolve("macro-analyst", "evaluator").id == "typesafe-ai/jev"
    assert gw.resolve("research-hypothesis", "generative").tier == "premium"


def test_evaluator_requires_external_id():
    bad = {
        "models": {"sin_id": {"kind": "evaluator"}},
        "agents": {"a": {"decisions": "sin_id"}},
    }
    with pytest.raises(ValueError, match="id externo"):
        GatewayConfig.model_validate(bad)


def test_assignment_kind_mismatch_rejected():
    bad = {
        "models": {"jev": {"kind": "evaluator", "id": "x"}, "lite": {"kind": "generative"}},
        "agents": {"a": {"decisions": "lite"}},  # decisions exige evaluator
    }
    with pytest.raises(ValueError, match="evaluator"):
        GatewayConfig.model_validate(bad)


def test_deterministic_agent_allowed_without_models():
    # Una asignación vacía es válida: agente determinista (p. ej. execution-router).
    ok = {
        "models": {"lite": {"kind": "generative"}},
        "agents": {"execution-router": {}},
    }
    config = GatewayConfig.model_validate(ok)
    assert config.agents["execution-router"].generative is None


def test_undeclared_model_rejected():
    bad = {
        "models": {"lite": {"kind": "generative"}},
        "agents": {"a": {"generative": "fantasma"}},
    }
    with pytest.raises(ValueError, match="no declarado"):
        GatewayConfig.model_validate(bad)


def test_gateway_loads_from_repo_yaml():
    config_path = Path(__file__).parent.parent / "config" / "models.yaml"
    gw = ModelGateway.from_yaml(config_path)
    # El ejemplo clave del diseño: Jev arbitra decisiones estructuradas.
    assert gw.resolve("news-analyst", "evaluator").id == "jev-1.13"
    assert gw.resolve("news-analyst", "generative").tier == "economic"
    # Un agente determinista no tiene LLM en su camino.
    with pytest.raises(KeyError):
        gw.resolve("execution-router", "generative")


def test_repo_yaml_matches_documented_pattern():
    raw = yaml.safe_load((Path(__file__).parent.parent / "config" / "models.yaml").read_text())
    gw = ModelGateway(GatewayConfig.model_validate(raw))
    assert gw.resolve("risk-portfolio", "evaluator").id == "jev-1.13"
