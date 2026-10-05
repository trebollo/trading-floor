"""Tests del esqueleto de agente: heartbeat, permisos de publicación y fail-closed."""

import pytest

from tf.agents import Agent
from tf.audit import SqliteAuditLog
from tf.bus import InMemoryBus
from tf.contracts import Envelope, Actor, MessageValidationError
from tf.gateway import GatewayConfig, ModelGateway
from tf.permissions import AgentPolicy, PermissionBroker, PermissionDenied


class EchoResearchAgent(Agent):
    department = "research"
    subscriptions = ("directive.new.v1",)

    def handle(self, envelope: Envelope) -> None:
        self.publish(
            "strategy.proposal.v1",
            {
                "proposal_id": "p1",
                "hypothesis": "La estacionalidad de octubre impulsa el índice.",
                "universe": ["SPY"],
                "timeframe": "1d",
                "entry_rules": "comprar el primer lunes de octubre",
                "exit_rules": "vender al cierre del mes",
                "prior_risk_estimate": "0.5% por operación",
            },
        )


@pytest.fixture()
def setup():
    bus = InMemoryBus()
    audit = SqliteAuditLog()
    broker = PermissionBroker(
        {
            "r1": AgentPolicy(
                agent="r1",
                department="research",
                role="hypothesis",
                tools=["search_memory"],
                outputs=["strategy.proposal.v1", "agent.heartbeat.v1"],
            )
        },
        audit=audit,
    )
    gw = ModelGateway(
        GatewayConfig.model_validate(
            {
                "models": {
                    "jev": {"kind": "evaluator", "id": "typesafe-ai/jev"},
                    "strong": {"kind": "generative"},
                },
                "agents": {"r1": {"generative": "strong", "decisions": "jev"}},
            }
        )
    )
    agent = EchoResearchAgent("r1", "hypothesis", bus, broker, audit, gateway=gw)
    return agent, bus, broker, audit


def test_agent_publishes_within_permissions(setup):
    agent, bus, _, _ = setup
    agent.handle(Envelope(type="directive.new.v1", actor=Actor(agent="ceo", role="ceo", department="executive"), payload={"directive_id": "d", "text": "t", "scope": "research"}))
    assert any(e.type == "strategy.proposal.v1" for e in bus.published)


def test_agent_cannot_publish_outside_permissions(setup):
    agent, _, broker, _ = setup
    with pytest.raises(PermissionDenied):
        agent.publish("risk.decision.v1", {"decision_id": "x", "request_id": "y", "verdict": "AUTORIZADA", "reason": "r"})


def test_agent_invalid_output_is_not_published_but_audited(setup):
    agent, bus, _, audit = setup
    with pytest.raises(MessageValidationError):
        agent.publish("strategy.proposal.v1", {"proposal_id": "p2"})  # faltan campos
    assert not any(e.type == "strategy.proposal.v1" for e in bus.published)
    assert any(e["event_type"] == "agent.output_invalid" for e in audit.entries())


def test_heartbeat_carries_actor_and_model(setup):
    agent, bus, _, _ = setup
    env = agent.heartbeat()
    assert env.payload["status"] == "up"
    assert env.actor.model == "strong"
    assert env.actor.department == "research"


def test_suspended_agent_reports_degraded_and_cannot_publish(setup):
    agent, _, broker, _ = setup
    broker.suspended.add("r1")
    env = agent.heartbeat()
    assert env.payload["status"] == "degraded"
    # El heartbeat sale (señal de salud), pero ninguna otra publicación pasa.
    with pytest.raises(PermissionDenied, match="suspendido"):
        agent.publish("strategy.proposal.v1", {"proposal_id": "p3"})


def test_tool_access_goes_through_broker(setup):
    agent, _, _, audit = setup
    result = agent.use_tool("search_memory", lambda q: f"result:{q}", "lecciones")
    assert result == "result:lecciones"
    assert any(e["event_type"] == "tool.call" for e in audit.entries())
    with pytest.raises(PermissionDenied):
        agent.use_tool("broker_place", lambda: None)


def test_handler_error_is_audited_not_swallowed(setup):
    agent, _, _, audit = setup
    agent.handle = lambda env: (_ for _ in ()).throw(RuntimeError("boom"))
    with pytest.raises(RuntimeError):
        agent.receive(Envelope(type="directive.new.v1", actor=Actor(agent="ceo", role="ceo", department="executive"), payload={"directive_id": "d", "text": "t", "scope": "research"}))
    assert any(e["event_type"] == "agent.handler_error" for e in audit.entries())
