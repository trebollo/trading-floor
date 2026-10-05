"""Departamentos como workers del AgentHost: puente entre el bus y los núcleos.

Cada clase es un subagente de un departamento. Los núcleos deterministas
(`PreTradeGate`, `ExecutionRouter`) siguen siendo quienes deciden — aquí solo se
traducen sobrés del bus a llamadas y de vuelta a sobrés tipados. Los canales
compartidos (`decisions`, `fills`, `orders_ctx`) los inyecta quien orquesta: los
agentes no guardan estado entre ciclos (regla transversal 1).

  · risk       — `risk-pretrade`: consume `order.request.v1`, valida con el
                 gate determinista (K-1..K-4) y publica `risk.decision.v1`.
                 Fail-closed: sin contrato o sin estado ⇒ RECHAZADA técnica.
  · execution  — `execution-router`: consume `risk.decision.v1` autorizada,
                 ejecuta vía router (idempotencia E-5, token E-2, frecuencia
                 E-6) y publica `fill.v1` + `order.status.v1`.
  · macro      — `macro-analyst`: fuente de régimen determinista (SMA larga);
                 publica `macro.regime.v1` al inicio del ciclo.
  · executive  — `chief-of-staff`: consume veredictos, regímenes e incidentes
                 y publica `executive.daily_report.v1` para el CEO.
"""

from __future__ import annotations

import uuid
from typing import Any

import numpy as np

from tf.agents import Agent
from tf.contracts import Envelope
from tf.execution import ExecutionRouter
from tf.risk import AUTORIZADA, REDUCIR, RECHAZADA, PortfolioState, PreTradeGate, StrategyContract

AUTHORIZED_VERDICTS = (AUTORIZADA, REDUCIR)


class RiskPreTradeAgent(Agent):
    """Departamento de riesgo: valida TODA operación antes de ejecutarse."""

    department = "risk"
    subscriptions: tuple[str, ...] = ("order.request.v1", "macro.regime.v1")

    def __init__(
        self,
        gate: PreTradeGate,
        contracts: dict[str, StrategyContract],
        state: PortfolioState,
        decisions: dict[str, dict[str, Any]],
        regime: dict[str, str | None],
        orders_ctx: dict[str, dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.gate = gate
        self.contracts = contracts
        self.state = state
        self.decisions = decisions
        self.regime = regime  # {"current": "normal" | "adverso" | None}
        self.orders_ctx = orders_ctx or {}  # {request_id: {request, price, ts}} — lo llena la sesión

    def handle(self, envelope: Envelope) -> None:
        if envelope.type == "macro.regime.v1":
            self.regime["current"] = envelope.payload["regime"]
            return
        request = envelope.payload
        request_id = request["request_id"]
        contract = self.contracts.get(request["strategy_id"])
        decision = self.gate.check(
            request, contract, self.state, regime=self.regime.get("current"), now=self._now_of(request_id)
        )
        self.decisions[request_id] = {
            "verdict": decision.verdict,
            "max_size": decision.max_size,
            "reason": decision.reason,
            "technical": decision.technical,
            "risk_token": decision.risk_token,
        }
        self.publish(
            "risk.decision.v1",
            {
                "decision_id": f"dec-{uuid.uuid4().hex[:8]}",
                "request_id": request_id,
                "verdict": decision.verdict,
                "max_size": decision.max_size,
                "risk_token": decision.risk_token,
                "reason": decision.reason,
                "technical": decision.technical,
            },
        )

    def _now_of(self, request_id: str) -> float | None:
        ctx = self.orders_ctx.get(request_id)
        return ctx["ts"] if ctx else None


class ExecutionRouterAgent(Agent):
    """Departamento de ejecución: único con acceso al broker (G6)."""

    department = "execution"
    subscriptions: tuple[str, ...] = ("risk.decision.v1",)

    def __init__(
        self,
        router: ExecutionRouter,
        orders_ctx: dict[str, dict[str, Any]],
        fills: dict[str, dict[str, Any] | None],
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.router = router
        self.orders_ctx = orders_ctx
        self.fills = fills

    def handle(self, envelope: Envelope) -> None:
        decision = envelope.payload
        request_id = decision["request_id"]
        ctx = self.orders_ctx.get(request_id)
        if decision["verdict"] not in AUTHORIZED_VERDICTS:
            self.fills[request_id] = None
            self.publish(
                "order.status.v1",
                {"order_id": f"ord-{request_id}", "request_id": request_id,
                 "status": "REJECTED", "detail": decision["reason"]},
            )
            return
        try:
            fill = self.router.execute(
                {k: ctx["request"][k] for k in ("request_id", "instrument", "side", "size")}
                | ({"stop_loss": ctx["request"]["stop_loss"]} if ctx["request"].get("stop_loss") is not None else {}),
                decision["risk_token"],
                price=ctx["price"],
                now=ctx["ts"],
                ts=ctx["ts"],
            )
        except Exception as exc:  # token expirado, router suspendido, broker rechaza...
            self.fills[request_id] = None
            self.publish(
                "order.status.v1",
                {"order_id": f"ord-{request_id}", "request_id": request_id,
                 "status": "REJECTED", "detail": f"{type(exc).__name__}: {exc}"},
            )
            return
        self.fills[request_id] = {"size": fill.size, "price": fill.price}
        self.publish(
            "fill.v1",
            {"fill_id": fill.order_id.replace("ord-", "fil-"), "order_id": fill.order_id,
             "instrument": fill.instrument, "side": fill.side, "size": fill.size,
             "price": fill.price, "ts": None},
        )
        self.publish(
            "order.status.v1",
            {"order_id": f"ord-{request_id}", "request_id": request_id, "status": "FILLED", "detail": ""},
        )


class MacroAnalystAgent(Agent):
    """Departamento macro: régimen determinista de la serie (precio vs SMA larga)."""

    department = "macro"
    subscriptions: tuple[str, ...] = ()

    def __init__(self, sma_window: int = 200, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.sma_window = sma_window

    def handle(self, envelope: Envelope) -> None:
        return None  # fuente pull: el scheduler pide el régimen al inicio del ciclo

    def emit_regime(self, close: np.ndarray, **envelope_kwargs: Any) -> Envelope | None:
        if len(close) < self.sma_window:
            return None  # sin historia suficiente no se opina (fail-closed informativo)
        window = close[-self.sma_window:]
        adverse = bool(close[-1] < window.mean())
        return self.publish(
            "macro.regime.v1",
            {"regime": "adverso" if adverse else "normal", "confidence": 0.6,
             "horizon": "days", "stale": False,
             "rationale": f"precio {'bajo' if adverse else 'sobre'} su SMA{self.sma_window}"},
            **envelope_kwargs,
        )


class ChiefOfStaffAgent(Agent):
    """Departamento ejecutivo: tally del ciclo e informe diario para el CEO."""

    department = "executive"
    subscriptions: tuple[str, ...] = ("validation.verdict.v1", "ops.incident.v1", "macro.regime.v1")

    def __init__(self, tally: dict[str, int], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.tally = tally

    def handle(self, envelope: Envelope) -> None:
        self.tally[envelope.type] = self.tally.get(envelope.type, 0) + 1

    def daily_report(self, cycle_date: str, budget: dict[str, Any], summary: str = "") -> Envelope:
        return self.publish(
            "executive.daily_report.v1",
            {
                "report_id": f"rep-{uuid.uuid4().hex[:8]}",
                "cycle_date": cycle_date,
                "counts": dict(self.tally),
                "budget": budget,
                "summary": summary or "informe del ciclo",
            },
        )
