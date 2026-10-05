"""Contratos de mensajes del bus de eventos.

Todos los mensajes son eventos versionados (`{type}.v{n}`). La salida de todo agente
se valida contra el esquema en el borde del bus (guardarrail G2): salida inválida
nunca se publica.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MessageValidationError(ValueError):
    """El payload no cumple el esquema del tipo de mensaje."""


class UnknownMessageType(ValueError):
    """El tipo de mensaje no está registrado (contrato inexistente)."""


class Actor(BaseModel):
    """Identidad completa de todo mensaje (guardarrail transversal #6)."""

    agent: str
    role: str
    department: str
    model: str | None = None  # modelo que produjo el mensaje, si fue un LLM
    prompt_version: str = "0"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Envelope(BaseModel):
    """Sobré de todo mensaje del bus. El payload se valida contra el registro."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: str
    ts: datetime = Field(default_factory=_utcnow)
    actor: Actor
    correlation_id: str | None = None
    causation_id: str | None = None
    payload: dict[str, Any]

    @field_validator("type")
    @classmethod
    def _type_registered(cls, v: str) -> str:
        if v not in REGISTRY:
            raise UnknownMessageType(f"tipo de mensaje no registrado: {v}")
        return v


# ---------------------------------------------------------------------------
# Registro de tipos de mensaje
# ---------------------------------------------------------------------------

REGISTRY: dict[str, type[BaseModel]] = {}


def message(type_name: str):
    """Registra un modelo pydantic como contrato de un tipo de mensaje versionado."""

    def deco(cls: type[BaseModel]) -> type[BaseModel]:
        if type_name in REGISTRY:
            raise ValueError(f"tipo duplicado en el registro: {type_name}")
        REGISTRY[type_name] = cls
        cls.message_type = type_name  # type: ignore[attr-defined]
        return cls

    return deco


def validate_payload(msg_type: str, payload: dict[str, Any]) -> BaseModel:
    """Valida el payload contra el contrato; lanza MessageValidationError si no cumple."""
    model_cls = REGISTRY.get(msg_type)
    if model_cls is None:
        raise UnknownMessageType(f"tipo de mensaje no registrado: {msg_type}")
    try:
        return model_cls.model_validate(payload)
    except Exception as exc:
        raise MessageValidationError(f"payload inválido para {msg_type}: {exc}") from exc


# ---------------------------------------------------------------------------
# Contratos v1 — plataforma
# ---------------------------------------------------------------------------


@message("agent.heartbeat.v1")
class AgentHeartbeat(BaseModel):
    agent: str
    department: str
    status: Literal["up", "degraded", "suspended"]
    subscriptions: list[str] = []


@message("agent.output_invalid.v1")
class AgentOutputInvalid(BaseModel):
    agent: str
    message_type: str
    error: str


@message("model.failover.v1")
class ModelFailover(BaseModel):
    agent: str
    from_model: str
    to_model: str | None
    reason: Literal["timeout", "provider_down", "budget", "error"]
    detail: str = ""


@message("directive.new.v1")
class DirectiveNew(BaseModel):
    directive_id: str
    text: str
    scope: Literal["research", "risk", "portfolio", "system", "operations"]
    issued_by: str = "ceo"


@message("lesson.new.v1")
class LessonNew(BaseModel):
    content: str
    tags: list[str] = []
    source_evaluation_id: str | None = None


# ---------------------------------------------------------------------------
# Contratos v1 — ciclo de vida de una estrategia
# ---------------------------------------------------------------------------


@message("strategy.proposal.v1")
class StrategyProposal(BaseModel):
    proposal_id: str
    hypothesis: str = Field(description="Hipótesis económica en ≤ 2 frases")
    universe: list[str]
    timeframe: str
    entry_rules: str
    exit_rules: str
    prior_risk_estimate: str
    cited_lesson_ids: list[str] = []
    spec: dict[str, Any] | None = Field(
        default=None,
        description="Borrador de spec DSL propuesto por research-hypothesis; research-coder lo formaliza",
    )


@message("strategy.spec.v1")
class StrategySpec(BaseModel):
    spec_id: str
    proposal_id: str
    spec: dict[str, Any]
    code_dsl: str


@message("backtest.report.v1")
class BacktestReport(BaseModel):
    report_id: str
    spec_id: str
    verdict: Literal["PROMOVER_A_VALIDACION", "REFINAR", "RECHAZAR"]
    metrics: dict[str, float]
    variant_count: int = Field(ge=0, le=50)
    blind_test_used: bool = False
    rationale: str


@message("validation.verdict.v1")
class ValidationVerdict(BaseModel):
    verdict_id: str
    spec_id: str
    verdict: Literal["VALIDADA", "VALIDADA_PROVISIONAL", "RECHAZADA"]
    battery: dict[str, bool] = Field(
        description="Resultado de los 6 puntos canónicos: monte_carlo, walk_forward, "
        "regimen_stress, param_sensitivity, cost_robustness, portfolio_correlation"
    )
    skeptic_scenarios: int = Field(ge=0)
    rationale: str


# ---------------------------------------------------------------------------
# Contratos v1 — riesgo y ejecución
# ---------------------------------------------------------------------------


@message("order.request.v1")
class OrderRequest(BaseModel):
    request_id: str
    strategy_id: str
    instrument: str
    side: Literal["BUY", "SELL"]
    size: float = Field(gt=0)
    order_type: Literal["MARKET", "LIMIT", "TWAP"]
    stop_loss: float | None = None


@message("risk.decision.v1")
class RiskDecision(BaseModel):
    decision_id: str
    request_id: str
    verdict: Literal["AUTORIZADA", "REDUCIR", "RECHAZADA"]
    max_size: float | None = None
    risk_token: str | None = None
    reason: str
    technical: bool = Field(
        default=False, description="True si es un rechazo técnico (fail-closed)"
    )


@message("order.status.v1")
class OrderStatus(BaseModel):
    order_id: str
    request_id: str
    status: Literal["SENT", "PARTIAL", "FILLED", "CANCELLED", "REJECTED"]
    detail: str = ""


@message("fill.v1")
class Fill(BaseModel):
    fill_id: str
    order_id: str
    instrument: str
    side: Literal["BUY", "SELL"]
    size: float
    price: float
    ts: datetime | None = None


@message("ops.incident.v1")
class OpsIncident(BaseModel):
    incident_id: str
    severity: Literal["V1", "V2", "V3", "V4"]
    source: str
    summary: str
    detail: str = ""


@message("macro.regime.v1")
class MacroRegime(BaseModel):
    regime: str
    confidence: float = Field(ge=0.0, le=1.0)
    horizon: Literal["intraday", "days", "weeks"]
    stale: bool = False
    rationale: str


@message("news.alert.v1")
class NewsAlert(BaseModel):
    alert_id: str
    category: Literal["relevant", "action", "noise", "TAIL_RISK"]
    confidence: float = Field(ge=0.0, le=1.0)
    single_source: bool = False
    source: str
    quotes: list[str] = Field(
        description="Campos estructurados de la fuente que sustentan cada afirmación"
    )
    summary: str


@message("executive.daily_report.v1")
class DailyReport(BaseModel):
    report_id: str
    cycle_date: str
    counts: dict[str, int] = Field(
        description="Tally de mensajes del ciclo por tipo: veredictos, regímenes, incidentes..."
    )
    budget: dict[str, Any] = {}
    summary: str


__all__ = [
    "Actor",
    "Envelope",
    "REGISTRY",
    "MessageValidationError",
    "UnknownMessageType",
    "validate_payload",
]
