"""Pipeline de Fase 1: Research → Backtest → Validation, end-to-end sobre el bus.

Los agentes de Research son *templates deterministas* en Fase 1: generan propuestas
a partir de un catálogo de hipótesis semilla. En Fase 2 se sustituyen por agentes LLM
sin cambiar los contratos ni el pipeline: misma interfaz, mismos guardarraíles.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from tf.agents import Agent
from tf.bus import BaseBus
from tf.contracts import Envelope
from tf.dsl import validate_spec, SpecError
from tf.engine import DEFAULT_COSTS, run_backtest
from tf.marketdata import MarketData
from tf.permissions import PermissionBroker
from tf.audit import AuditLog
from tf.validation import BatteryResult, ValidationPolicy, run_battery


# ---------------------------------------------------------------------------
# Research: fuente de hipótesis (template determinista en Fase 1)
# ---------------------------------------------------------------------------

SEED_HYPOTHESES: list[dict[str, Any]] = [
    {
        "hypothesis": "El cruce de medias captura tendencia en índices con deriva positiva.",
        "spec": {"type": "sma_cross", "params": {"fast_window": 20, "slow_window": 60}},
    },
    {
        "hypothesis": "La ruptura de máximos recientes persiste por momentum institucional.",
        "spec": {"type": "breakout", "params": {"lookback": 50, "exit_buffer": 0.05}},
    },
    {
        "hypothesis": "El RSI extremo revierte en horizontes cortos por sobreextensión.",
        "spec": {"type": "rsi_reversion", "params": {"rsi_window": 14, "lower": 30, "upper": 70}},
    },
    {
        "hypothesis": "El momentum de 60 días continúa en los siguientes periodos.",
        "spec": {"type": "momentum", "params": {"lookback": 60, "threshold": 0.02}},
    },
    # Hipótesis deliberadamente inválida: ventanas invertidas (fast >= slow).
    # Debe morir en el validador de specs, no en mercado.
    {
        "hypothesis": "Invertir el cruce de medias para capturar reversiones (ventanas al revés).",
        "spec": {"type": "sma_cross", "params": {"fast_window": 60, "slow_window": 20}},
    },
]


class ResearchTemplateAgent(Agent):
    """Genera propuestas deterministas. Fase 2: reemplazo por LLM con misma interfaz."""

    department = "research"
    subscriptions: tuple[str, ...] = ()

    def handle(self, envelope: Envelope) -> None:
        # Fuente push: no consume mensajes del bus en Fase 1.
        return None

    def generate(self, count: int | None = None) -> list[tuple[Envelope, dict[str, Any]]]:
        """Publica propuestas y devuelve (envelope, semilla) para el coder."""
        out = []
        for seed in SEED_HYPOTHESES[: count or len(SEED_HYPOTHESES)]:
            proposal_id = f"prop-{uuid.uuid4().hex[:8]}"
            env = self.publish(
                "strategy.proposal.v1",
                {
                    "proposal_id": proposal_id,
                    "hypothesis": seed["hypothesis"],
                    "universe": ["SYNTH"],
                    "timeframe": "1d",
                    "entry_rules": "según spec",
                    "exit_rules": "según spec",
                    "prior_risk_estimate": "0.5% por operación",
                    "cited_lesson_ids": [],
                },
            )
            out.append((env, seed))
        return out


class ResearchCoderAgent(Agent):
    """Formaliza propuestas en specs ejecutables (rol research-coder)."""

    department = "research"
    subscriptions: tuple[str, ...] = ()

    def handle(self, envelope: Envelope) -> None:
        return None

    def formalize(self, proposal_id: str, spec: dict[str, Any]) -> Envelope:
        return self.publish(
            "strategy.spec.v1",
            {
                "spec_id": f"spec-{uuid.uuid4().hex[:8]}",
                "proposal_id": proposal_id,
                "spec": spec,
                "code_dsl": str(spec),
            },
        )


# ---------------------------------------------------------------------------
# Backtest + Validation: orquestación del pipeline
# ---------------------------------------------------------------------------


@dataclass
class CatalogEntry:
    spec: dict
    backtest_verdict: str
    metrics: dict[str, float]
    battery: dict[str, bool] | None
    final: str  # VALIDADA | VALIDADA_PROVISIONAL | RECHAZADA_BACKTEST | RECHAZADA_BATERIA


class PipelineRunner:
    """Ejecuta el ciclo completo y produce el catálogo de estrategias evaluadas."""

    def __init__(
        self,
        bus: BaseBus,
        broker: PermissionBroker,
        audit: AuditLog,
        policy: ValidationPolicy = ValidationPolicy(),
        backtest_promotion_sharpe: float = 0.5,
    ) -> None:
        self.bus = bus
        self.broker = broker
        self.audit = audit
        self.policy = policy
        self.backtest_promotion_sharpe = backtest_promotion_sharpe
        self.catalog: list[CatalogEntry] = []

    def run(self, data: MarketData, proposals: int | None = None) -> list[CatalogEntry]:
        hypothesis_agent = ResearchTemplateAgent(
            name="research-hypothesis",
            role="hypothesis",
            bus=self.bus,
            broker=self.broker,
            audit=self.audit,
        )
        coder_agent = ResearchCoderAgent(
            name="research-coder",
            role="coder",
            bus=self.bus,
            broker=self.broker,
            audit=self.audit,
        )
        spec_envelopes = []
        for proposal_env, seed in hypothesis_agent.generate(proposals):
            spec_envelopes.append(coder_agent.formalize(proposal_env.payload["proposal_id"], seed["spec"]))
        for env in spec_envelopes:
            entry = self._evaluate_spec(env.payload["spec_id"], env.payload["spec"], data)
            self.catalog.append(entry)
            self.audit.append(
                actor="pipeline",
                event_type="pipeline.spec_evaluated",
                payload={"spec_id": env.payload["spec_id"], "final": entry.final},
            )
        return self.catalog

    def _evaluate_spec(self, spec_id: str, spec: dict, data: MarketData) -> CatalogEntry:
        # 1+2) Validez estructural (lista blanca) y backtest con costes conservadores
        try:
            validate_spec(spec)
            result = run_backtest(data, spec, DEFAULT_COSTS).compute_metrics()
        except SpecError as exc:
            return CatalogEntry(spec=spec, backtest_verdict="RECHAZAR", metrics={}, battery=None, final=f"RECHAZADA_SPEC: {exc}")
        metrics = result.metrics
        n_trades = metrics["n_trades"]
        profitable = metrics["total_return"] > 0 and metrics["sharpe"] >= self.backtest_promotion_sharpe
        if not profitable or n_trades < self.policy.min_trades:  # B-4 incluido
            return CatalogEntry(spec=spec, backtest_verdict="RECHAZAR", metrics=metrics, battery=None, final="RECHAZADA_BACKTEST")

        # 3) Batería canónica de validación
        battery: BatteryResult = run_battery(data, spec, self.policy, seed=42)
        non_regime = {k: v for k, v in battery.checks.items() if k != "regimen_stress"}
        if battery.all_passed:
            final = "VALIDADA"
        elif all(non_regime.values()):
            # Pasa todo salvo el estrés de régimen: provisional, con contrato que
            # condiciona la exposición en régimen adverso (spec 03, V-7).
            final = "VALIDADA_PROVISIONAL"
        else:
            final = "RECHAZADA_BATERIA"
        return CatalogEntry(
            spec=spec,
            backtest_verdict="PROMOVER_A_VALIDACION",
            metrics=metrics,
            battery=battery.checks,
            final=final,
        )
