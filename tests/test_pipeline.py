"""Tests del pipeline end-to-end Research → Backtest → Validation."""

from tf.audit import SqliteAuditLog
from tf.bus import InMemoryBus
from tf.marketdata import synthetic_market
from tf.permissions import PermissionBroker
from tf.pipeline import PipelineRunner
from tf.validation import ValidationPolicy


def make_runner(policy: ValidationPolicy | None = None):
    bus = InMemoryBus()
    audit = SqliteAuditLog()
    broker = PermissionBroker.from_yaml(
        __import__("pathlib").Path(__file__).parent.parent / "config" / "guardrails.yaml", audit=audit
    )
    policy = policy or ValidationPolicy(min_trades=30)
    return PipelineRunner(bus, broker, audit, policy=policy)


def test_pipeline_produces_catalog_and_audits():
    data = synthetic_market(n=2000, seed=42)
    runner = make_runner()
    catalog = runner.run(data)
    assert len(catalog) == 5
    finals = {e.final.split(":")[0] for e in catalog}
    assert finals <= {"VALIDADA", "VALIDADA_PROVISIONAL", "RECHAZADA_BACKTEST", "RECHAZADA_BATERIA", "RECHAZADA_SPEC"}
    # Todo el ciclo quedó auditado.
    events = [e["event_type"] for e in runner.audit.entries()]
    assert "pipeline.spec_evaluated" in events
    assert runner.audit.verify()


def test_overfit_seed_does_not_reach_validada():
    """La hipótesis contra-tendencia no puede salir VALIDADA en mercado con tendencia."""
    data = synthetic_market(n=2000, drift=0.0012, vol=0.008, seed=42)
    runner = make_runner()
    catalog = runner.run(data)
    countertrend = [e for e in catalog if e.spec["type"] == "rsi_reversion"]
    assert countertrend and countertrend[0].final == "RECHAZADA_BACKTEST"


def test_trend_strategy_reaches_validated_or_provisional():
    """La estrategia de momentum sana debe llegar a provisional (régimen) o validada."""
    data = synthetic_market(n=2500, drift=0.0012, vol=0.008, seed=42)
    runner = make_runner()
    catalog = runner.run(data)
    momentum = [e for e in catalog if e.spec["type"] == "momentum" and e.spec["params"]["lookback"] == 60]
    assert momentum, "la propuesta de momentum debería existir"
    entry = momentum[0]
    assert entry.final in {"VALIDADA", "VALIDADA_PROVISIONAL"}
    if entry.final == "VALIDADA_PROVISIONAL":
        # El resto de la batería pasó íntegro; solo el estrés de régimen falla.
        assert all(v for k, v in entry.battery.items() if k != "regimen_stress")


def test_research_agent_cannot_publish_outside_role():
    """El agente de research (plantilla) no puede publicar decisiones de riesgo."""
    from tf.pipeline import ResearchTemplateAgent
    from tf.permissions import PermissionDenied
    import pytest

    bus = InMemoryBus()
    audit = SqliteAuditLog()
    broker = PermissionBroker.from_yaml(
        __import__("pathlib").Path(__file__).parent.parent / "config" / "guardrails.yaml", audit=audit
    )
    agent = ResearchTemplateAgent(
        name="research-hypothesis", role="hypothesis", bus=bus, broker=broker, audit=audit
    )
    with pytest.raises(PermissionDenied):
        agent.publish("risk.decision.v1", {"decision_id": "x", "request_id": "y", "verdict": "AUTORIZADA", "reason": "r"})
