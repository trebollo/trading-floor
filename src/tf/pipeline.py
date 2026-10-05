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
from tf.gateway import ModelGateway
from tf.marketdata import MarketData
from tf.memory import LessonExtractor, MemoryStore, cosine, embed
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
    """Genera propuestas deterministas. Fase 2: reemplazo por LLM con misma interfaz.

    Con memoria (Fase 3): consulta lecciones antes de proponer (R-4/R-5) y salta
    familias bloqueadas o ideas ya fracasadas.
    """

    department = "research"
    subscriptions: tuple[str, ...] = ()

    def __init__(self, memory: MemoryStore | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.memory = memory

    def handle(self, envelope: Envelope) -> None:
        # Fuente push: no consume mensajes del bus en Fase 1.
        return None

    def _is_blocked(self, seed: dict[str, Any]) -> bool:
        """R-4/R-5: spec ya rechazado, familia bloqueada o hipótesis similar a un fracaso."""
        if self.memory is None:
            return False
        spec = seed["spec"]
        if self.memory.is_spec_dead(spec):
            return True
        if self.memory.is_family_locked(spec):
            return True
        emb = embed(seed["hypothesis"])
        family = f"{spec['type']}|SYNTH"
        for lesson in self.memory.lessons:
            if lesson.family_key == family and cosine(emb, lesson.embedding) >= 0.8:
                return True
        return False

    def generate(self, count: int | None = None) -> list[tuple[Envelope, dict[str, Any]]]:
        """Publica propuestas; las bloqueadas por memoria se saltan y quedan auditadas."""
        out = []
        for seed in SEED_HYPOTHESES[: count or len(SEED_HYPOTHESES)]:
            if self._is_blocked(seed):
                self.audit.append(
                    actor=self.name,
                    event_type="research.proposal_skipped",
                    payload={"hypothesis": seed["hypothesis"], "reason": "memoria: idea ya fracasada o familia bloqueada"},
                )
                continue
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
                    "spec": seed["spec"],
                },
            )
            out.append((env, seed))
        return out


class ResearchCoderAgent(Agent):
    """Formaliza propuestas en specs ejecutables (rol research-coder).

    Bus-driven: consume `strategy.proposal.v1` y publica `strategy.spec.v1`.
    """

    department = "research"
    subscriptions: tuple[str, ...] = ("strategy.proposal.v1",)

    def handle(self, envelope: Envelope) -> None:
        spec = envelope.payload.get("spec")
        if not spec:
            self.audit.append(
                actor=self.name,
                event_type="research.proposal_skipped",
                payload={"proposal_id": envelope.payload.get("proposal_id"), "reason": "propuesta sin spec"},
            )
            return
        self.formalize(envelope.payload["proposal_id"], spec)

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


class BacktestEngineerAgent(Agent):
    """Departamento backtest (rol engineer): consume `strategy.spec.v1`.

    Validez estructural (DSL) + backtest con costes conservadores. Publica
    `backtest.report.v1`; las promovidas siguen su curso al departamento de
    validación, las rechazadas terminan aquí con lección en memoria.
    """

    department = "backtest"
    subscriptions: tuple[str, ...] = ("strategy.spec.v1",)

    def __init__(
        self,
        data: MarketData,
        catalog: list["CatalogEntry"],
        entries_by_spec: dict[str, "CatalogEntry"],
        specs_by_id: dict[str, dict],
        policy: ValidationPolicy,
        backtest_promotion_sharpe: float = 0.5,
        memory: MemoryStore | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.data = data
        self.catalog = catalog
        self.entries_by_spec = entries_by_spec
        self.specs_by_id = specs_by_id
        self.policy = policy
        self.backtest_promotion_sharpe = backtest_promotion_sharpe
        self.memory = memory

    def handle(self, envelope: Envelope) -> None:
        spec_id = envelope.payload["spec_id"]
        spec = envelope.payload["spec"]
        self.specs_by_id[spec_id] = spec
        try:
            validate_spec(spec)
            result = run_backtest(self.data, spec, DEFAULT_COSTS).compute_metrics()
        except SpecError as exc:
            self._record(spec_id, spec, "RECHAZAR", f"spec inválido: {exc}", metrics={})
            self._append(spec_id, CatalogEntry(spec=spec, backtest_verdict="RECHAZAR", metrics={}, battery=None, final=f"RECHAZADA_SPEC: {exc}"))
            self._report(spec_id, "RECHAZAR", {}, f"spec inválido: {exc}")
            return
        metrics = result.metrics
        n_trades = metrics["n_trades"]
        profitable = metrics["total_return"] > 0 and metrics["sharpe"] >= self.backtest_promotion_sharpe
        if not profitable or n_trades < self.policy.min_trades:  # B-4 incluido
            self._record(spec_id, spec, "RECHAZAR", "rechazada en backtest", metrics)
            self._append(spec_id, CatalogEntry(spec=spec, backtest_verdict="RECHAZAR", metrics=metrics, battery=None, final="RECHAZADA_BACKTEST"))
            self._report(spec_id, "RECHAZAR", metrics, "retorno/sharpe/trades por debajo del umbral")
            return
        self._append(spec_id, CatalogEntry(spec=spec, backtest_verdict="PROMOVER_A_VALIDACION", metrics=metrics, battery=None, final="PROMOVER_A_VALIDACION"))
        self._report(spec_id, "PROMOVER_A_VALIDACION", metrics, "supera backtest con costes conservadores")

    def _record(self, spec_id: str, spec: dict, verdict: str, summary: str, metrics: dict) -> None:
        if self.memory is None:
            return
        rec = self.memory.add_evaluation(spec_id, "backtest", verdict, summary, spec=spec, metrics=metrics)
        for lesson in LessonExtractor().from_backtest(spec, verdict, metrics or {}):
            self.memory.add_lesson(
                content=lesson["content"], tags=lesson["tags"],
                source_evaluation_id=rec.id, family_key=lesson["family_key"],
            )

    def _append(self, spec_id: str, entry: CatalogEntry) -> None:
        self.catalog.append(entry)
        self.entries_by_spec[spec_id] = entry

    def _report(self, spec_id: str, verdict: str, metrics: dict, rationale: str) -> None:
        self.publish(
            "backtest.report.v1",
            {"report_id": f"rep-{uuid.uuid4().hex[:8]}", "spec_id": spec_id, "verdict": verdict,
             "metrics": metrics, "variant_count": 0, "rationale": rationale},
        )


class ValidationQuantAgent(Agent):
    """Departamento validation (rol quant): consume `backtest.report.v1`.

    Solo evalúa las promovidas por backtest. Corre la batería canónica
    (determinista) y publica `validation.verdict.v1`; el veredicto final
    queda en la CatalogEntry compartida.
    """

    department = "validation"
    subscriptions: tuple[str, ...] = ("backtest.report.v1",)

    def __init__(
        self,
        data: MarketData,
        catalog: list["CatalogEntry"],
        entries_by_spec: dict[str, "CatalogEntry"],
        specs_by_id: dict[str, dict],
        policy: ValidationPolicy,
        memory: MemoryStore | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.data = data
        self.catalog = catalog
        self.entries_by_spec = entries_by_spec
        self.specs_by_id = specs_by_id
        self.policy = policy
        self.memory = memory

    def handle(self, envelope: Envelope) -> None:
        report = envelope.payload
        if report["verdict"] != "PROMOVER_A_VALIDACION":
            return  # las rechazadas por backtest terminaron ahí
        spec_id = report["spec_id"]
        spec = self.specs_by_id[spec_id]
        battery: BatteryResult = run_battery(self.data, spec, self.policy, seed=42)
        non_regime = {k: v for k, v in battery.checks.items() if k != "regimen_stress"}
        if battery.all_passed:
            final = "VALIDADA"
        elif all(non_regime.values()):
            # Pasa todo salvo el estrés de régimen: provisional, con contrato que
            # condiciona la exposición en régimen adverso (spec 03, V-7).
            final = "VALIDADA_PROVISIONAL"
        else:
            final = "RECHAZADA_BATERIA"
        entry = self.entries_by_spec[spec_id]
        entry.battery = battery.checks
        entry.final = final
        if self.memory is not None:
            rec = self.memory.add_evaluation(spec_id, "validation", final, "batería canónica", spec=spec, metrics=report["metrics"])
            for lesson in LessonExtractor().from_battery(spec, battery.checks, battery.details):
                self.memory.add_lesson(
                    content=lesson["content"], tags=lesson["tags"],
                    source_evaluation_id=rec.id, family_key=lesson["family_key"],
                )
        self.publish(
            "validation.verdict.v1",
            {"verdict_id": f"ver-{uuid.uuid4().hex[:8]}", "spec_id": spec_id, "verdict": final,
             "battery": battery.checks, "skeptic_scenarios": 0, "rationale": "batería canónica determinista"},
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
        memory: MemoryStore | None = None,
        gateway: ModelGateway | None = None,
        governor: Any | None = None,   # G3: CostGovernor compartido por todos los agentes
        host: Any | None = None,       # AgentHost externo (el scheduler comparte el suyo)
    ) -> None:
        self.bus = bus
        self.broker = broker
        self.audit = audit
        self.policy = policy
        self.backtest_promotion_sharpe = backtest_promotion_sharpe
        self.memory = memory
        self.gateway = gateway
        self.governor = governor
        self.host = host
        self.host_stats: dict[str, Any] = {}
        self.catalog: list[CatalogEntry] = []

    def _hypothesis_agent(self) -> ResearchTemplateAgent:
        """research-hypothesis: LLM real si hay gateway, plantilla determinista si no."""
        base = dict(name="research-hypothesis", role="hypothesis", bus=self.bus, broker=self.broker, audit=self.audit, memory=self.memory)
        if self.gateway is not None:
            from tf.research_llm import ResearchLLMAgent

            return ResearchLLMAgent.from_gateway(self.gateway, governor=self.governor, **base)
        return ResearchTemplateAgent(**base)

    def run(self, data: MarketData, proposals: int | None = None) -> list[CatalogEntry]:
        """Ciclo Research → Backtest → Validation orquestado como multiagente.

        Los departamentos son workers independientes que solo se comunican por
        el bus: coder consume `strategy.proposal.v1`, backtest consume
        `strategy.spec.v1` y validation consume `backtest.report.v1`. El
        `AgentHost` despacha con guardas anti-bucle (dedup, colas con techo,
        drenaje acotado).
        """
        from tf.host import AgentHost

        hypothesis_agent = self._hypothesis_agent()
        catalog: list[CatalogEntry] = []
        entries_by_spec: dict[str, CatalogEntry] = {}
        specs_by_id: dict[str, dict] = {}
        base = dict(bus=self.bus, broker=self.broker, audit=self.audit)
        coder = ResearchCoderAgent(name="research-coder", role="coder", **base)
        backtest = BacktestEngineerAgent(
            data, catalog, entries_by_spec, specs_by_id, self.policy,
            backtest_promotion_sharpe=self.backtest_promotion_sharpe,
            memory=self.memory, name="backtest-engineer", role="engineer", **base,
        )
        validation = ValidationQuantAgent(
            data, catalog, entries_by_spec, specs_by_id, self.policy,
            memory=self.memory, name="validation-quant", role="quant", **base,
        )
        host = self.host = self.host or AgentHost(self.bus, self.audit)
        host.register("research", workers={"research-coder": coder.receive},
                      msg_types={"research-coder": list(ResearchCoderAgent.subscriptions)})
        host.register("backtest", workers={"backtest-engineer": backtest.receive},
                      msg_types={"backtest-engineer": list(BacktestEngineerAgent.subscriptions)})
        host.register("validation", workers={"validation-quant": validation.receive},
                      msg_types={"validation-quant": list(ValidationQuantAgent.subscriptions)})

        # Fuente: research publica propuestas en el bus; el host encadena el resto.
        hypothesis_agent.generate(proposals)
        self.host_stats = host.drain()

        for entry in catalog:  # auditoría uniforme del resultado por spec
            self.audit.append(
                actor="pipeline",
                event_type="pipeline.spec_evaluated",
                payload={"spec_id": next((sid for sid, e in entries_by_spec.items() if e is entry), "?"),
                         "final": entry.final},
            )
        self.catalog = catalog
        return catalog
