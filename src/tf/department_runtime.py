"""Factories de workers residentes para los primeros departamentos distribuibles."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from tf.agents import Agent
from tf.audit import AuditLog
from tf.budget import BudgetLimits, CostGovernor
from tf.bus import BaseBus
from tf.contracts import Envelope
from tf.departments import MacroAnalystAgent
from tf.departments import ChiefOfStaffAgent
from tf.datasets import load_market_snapshot
from tf.gateway import ModelGateway
from tf.memory import PostgresMemoryStore
from tf.news import build_news_agent, load_feed_config
from tf.permissions import PermissionBroker
from tf.pipeline import (
    BacktestEngineerAgent,
    ResearchCoderAgent,
    ResearchTemplateAgent,
    ValidationQuantAgent,
)
from tf.state_pg import PostgresStateStore
from tf.validation import ValidationPolicy


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def _broker(audit: AuditLog) -> PermissionBroker:
    return PermissionBroker.from_yaml(_root() / "config" / "guardrails.yaml", audit=audit)


def _memory(store: PostgresStateStore) -> PostgresMemoryStore:
    return PostgresMemoryStore(store)


def _policy() -> ValidationPolicy:
    return ValidationPolicy(min_trades=int(os.getenv("TF_MIN_TRADES", "30")))


class _ResearchCycleTrigger(Agent):
    department = "research"
    subscriptions = ("cycle.trigger.v1",)

    def __init__(self, generator: ResearchTemplateAgent, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.generator = generator

    def handle(self, envelope: Envelope) -> None:
        payload = envelope.payload
        generated = self.generator.generate(
            payload["proposal_count"],
            cycle_id=payload["cycle_id"],
            market_data_uri=payload["market_data_uri"],
            market_data_sha256=payload["market_data_sha256"],
            causation_id=envelope.id,
        )
        proposal_ids = [event.payload["proposal_id"] for event, _ in generated]
        self.publish(
            "cycle.research_batch.v1",
            {"cycle_id": payload["cycle_id"], "proposal_ids": proposal_ids,
             "skipped_count": payload["proposal_count"] - len(proposal_ids),
             "rationale": "lote determinista de research formalizado por el bus"},
            id=f"research-batch-{payload['cycle_id']}",
            correlation_id=payload["cycle_id"],
            causation_id=envelope.id,
        )


class _MacroNewsCycle(Agent):
    department = "macro"
    subscriptions = ("cycle.trigger.v1",)

    def __init__(
        self,
        macro: MacroAnalystAgent,
        news: Any,
        dataset_dir: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.macro = macro
        self.news = news
        self.dataset_dir = dataset_dir

    def handle(self, envelope: Envelope) -> None:
        payload = envelope.payload
        cycle_id = payload["cycle_id"]
        incidents = 0
        alerts = 0
        regime_published = False
        try:
            data = load_market_snapshot(
                payload["market_data_uri"], payload["market_data_sha256"], self.dataset_dir
            )
            regime_published = self.macro.emit_regime(
                data.close, correlation_id=cycle_id, causation_id=envelope.id
            ) is not None
        except Exception as exc:
            incidents += 1
            self._incident(cycle_id, "macro", exc, envelope)
        try:
            alerts = len(self.news.ingest(cycle_id=cycle_id, causation_id=envelope.id))
        except Exception as exc:
            incidents += 1
            self._incident(cycle_id, "news", exc, envelope)
        self.publish(
            "cycle.macro_news_completed.v1",
            {"cycle_id": cycle_id, "regime_published": regime_published,
             "alerts_published": alerts, "incident_count": incidents},
            id=f"macro-news-completed-{cycle_id}",
            correlation_id=cycle_id,
            causation_id=envelope.id,
        )

    def _incident(self, cycle_id: str, phase: str, exc: Exception, source: Envelope) -> None:
        detail = f"{type(exc).__name__}: {exc}"
        incident_id = f"inc-{cycle_id}-{phase}"
        self.publish(
            "ops.incident.v1",
            {"incident_id": incident_id, "severity": "V2", "source": f"macro/{phase}",
             "summary": f"fallo en fase {phase}", "detail": detail},
            id=incident_id,
            correlation_id=cycle_id,
            causation_id=source.id,
        )
        self.audit.append(
            actor=self.name,
            event_type="ops.incident",
            payload={"phase": phase, "cycle_id": cycle_id, "error": detail},
        )
def research_factory(
    bus: BaseBus, audit: AuditLog, department: str, state_store: PostgresStateStore,
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    if department != "research":
        raise ValueError("research_factory solo sirve al departamento research")
    broker = _broker(audit)
    memory = _memory(state_store)
    base = {"bus": bus, "broker": broker, "audit": audit}
    generator = ResearchTemplateAgent(
        memory=memory, name="research-hypothesis", role="hypothesis", **base,
    )
    trigger = _ResearchCycleTrigger(
        generator, name="research-cycle", role="cycle_coordinator", **base,
    )
    coder = ResearchCoderAgent(name="research-coder", role="coder", **base)
    workers = {
        "research-cycle": trigger.receive,
        "research-coder": coder.receive,
    }
    msg_types = {
        "research-cycle": ["cycle.trigger.v1"],
        "research-coder": list(ResearchCoderAgent.subscriptions),
    }
    return workers, msg_types


def backtest_factory(
    bus: BaseBus, audit: AuditLog, department: str, state_store: PostgresStateStore,
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    if department != "backtest":
        raise ValueError("backtest_factory solo sirve al departamento backtest")
    broker = _broker(audit)
    agent = BacktestEngineerAgent(
        data=None, catalog=None, entries_by_spec=None, specs_by_id=None,
        policy=_policy(), memory=_memory(state_store),
        dataset_dir=os.getenv("TF_DATASET_DIR", "/var/lib/trading-floor/datasets"),
        name="backtest-engineer", role="engineer", bus=bus, broker=broker, audit=audit,
    )
    return (
        {"backtest-engineer": agent.receive},
        {"backtest-engineer": list(BacktestEngineerAgent.subscriptions)},
    )


def validation_factory(
    bus: BaseBus, audit: AuditLog, department: str, state_store: PostgresStateStore,
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    if department != "validation":
        raise ValueError("validation_factory solo sirve al departamento validation")
    broker = _broker(audit)
    agent = ValidationQuantAgent(
        data=None, catalog=None, entries_by_spec=None, specs_by_id=None,
        policy=_policy(), memory=_memory(state_store),
        dataset_dir=os.getenv("TF_DATASET_DIR", "/var/lib/trading-floor/datasets"),
        name="validation-quant", role="quant", bus=bus, broker=broker, audit=audit,
    )
    return (
        {"validation-quant": agent.receive},
        {"validation-quant": list(ValidationQuantAgent.subscriptions)},
    )


def macro_news_factory(
    bus: BaseBus, audit: AuditLog, department: str, state_store: PostgresStateStore,
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    if department != "macro":
        raise ValueError("macro_news_factory solo sirve al departamento macro")
    broker = _broker(audit)
    root = _root()
    gateway = ModelGateway.from_yaml(root / "config" / "models.yaml")
    governor = CostGovernor(
        BudgetLimits.from_yaml(root / "config" / "guardrails.yaml"),
        audit=audit,
        state_store=state_store,
    )
    base = {"bus": bus, "broker": broker, "audit": audit}
    macro = MacroAnalystAgent(name="macro-analyst", role="analyst", **base)
    news_config = load_feed_config(root / "config" / "news.yaml")
    news = build_news_agent(
        gateway,
        news_config,
        governor=governor,
        name="news-analyst",
        role="news",
        **base,
    )
    coordinator = _MacroNewsCycle(
        macro,
        news,
        os.getenv("TF_DATASET_DIR", "/var/lib/trading-floor/datasets"),
        name="macro-cycle",
        role="cycle_coordinator",
        **base,
    )
    return (
        {"macro-cycle": coordinator.receive},
        {"macro-cycle": list(_MacroNewsCycle.subscriptions)},
    )


def executive_factory(
    bus: BaseBus, audit: AuditLog, department: str, state_store: PostgresStateStore,
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    if department != "executive":
        raise ValueError("executive_factory solo sirve al departamento executive")
    chief = ChiefOfStaffAgent(
        tally={}, state_store=state_store,
        name="chief-of-staff", role="chief_of_staff",
        bus=bus, broker=_broker(audit), audit=audit,
    )
    return (
        {"chief-of-staff": chief.receive},
        {"chief-of-staff": list(ChiefOfStaffAgent.subscriptions)},
    )
