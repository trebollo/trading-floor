"""Tests del Permission Broker (G1): lista cerrada y escalado V3."""

import pytest

from tf.audit import SqliteAuditLog
from tf.permissions import AgentPolicy, PermissionBroker, PermissionDenied


@pytest.fixture()
def broker():
    policies = {
        "research-hypothesis": AgentPolicy(
            agent="research-hypothesis",
            department="research",
            role="hypothesis",
            tools=["search_memory", "run_python_sandbox"],
            outputs=["strategy.proposal.v1", "agent.heartbeat.v1"],
        )
    }
    return PermissionBroker(policies, audit=SqliteAuditLog())


def test_allowed_tool_passes(broker):
    broker.check_tool("research-hypothesis", "search_memory")


def test_forbidden_tool_denied_and_recorded(broker):
    with pytest.raises(PermissionDenied):
        broker.check_tool("research-hypothesis", "broker_place")  # fuera de su rol
    assert broker.violations["research-hypothesis"] == 1
    # Queda registrado en el audit log.
    events = [e["event_type"] for e in broker._audit.entries()]
    assert "guardrail.violation" in events


def test_three_violations_suspend_agent(broker):
    for _ in range(3):
        with pytest.raises(PermissionDenied):
            broker.check_tool("research-hypothesis", "broker_place")
    assert broker.is_suspended("research-hypothesis")
    # Un agente suspendido no puede ni usar herramientas permitidas.
    with pytest.raises(PermissionDenied, match="suspendido"):
        broker.check_tool("research-hypothesis", "search_memory")


def test_forbidden_publish_denied(broker):
    with pytest.raises(PermissionDenied):
        broker.check_publish("research-hypothesis", "risk.decision.v1")


def test_unknown_agent_denied(broker):
    with pytest.raises(PermissionDenied):
        broker.check_tool("agente-fantasma", "cualquier_tool")
