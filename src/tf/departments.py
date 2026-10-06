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

import hashlib
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
             "cycle_id": envelope_kwargs.get("correlation_id"),
             "rationale": f"precio {'bajo' if adverse else 'sobre'} su SMA{self.sma_window}"},
            **envelope_kwargs,
        )


class ChiefOfStaffAgent(Agent):
    """Departamento ejecutivo: tally del ciclo e informe diario para el CEO."""

    department = "executive"
    subscriptions: tuple[str, ...] = (
        "validation.verdict.v1", "ops.incident.v1", "ops.dead_letter.v1",
        "macro.regime.v1", "news.alert.v1", "cycle.research_batch.v1",
        "cycle.macro_news_completed.v1", "cycle.completed.v1",
    )

    def __init__(self, tally: dict[str, int], state_store: Any | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.tally = tally
        self.state_store = state_store

    def handle(self, envelope: Envelope) -> None:
        if envelope.type == "cycle.completed.v1":
            payload = envelope.payload
            cycle_id = payload["cycle_id"]
            if self.state_store is not None:
                self.state_store.set(f"executive/cycle-meta/{cycle_id}", payload)
            else:
                self.tally[f"__cycle_meta__:{cycle_id}"] = payload
            self._maybe_report(cycle_id)
            return

        cycle_id = envelope.payload.get("cycle_id") or envelope.correlation_id
        if self.state_store is not None and cycle_id:
            key = f"executive/tally/{cycle_id}"

            def increment(state: dict[str, Any]) -> dict[str, Any]:
                state = state or {"counts": {}, "seen": []}
                # Older rows held only the counts dictionary.
                if "counts" not in state:
                    state = {"counts": state, "seen": []}
                if envelope.id in state["seen"]:
                    return state
                counts = state["counts"]
                counts[envelope.type] = counts.get(envelope.type, 0) + 1
                if envelope.type == "ops.dead_letter.v1":
                    counts["ops.incident.v1"] = counts.get("ops.incident.v1", 0) + 1
                state["seen"].append(envelope.id)
                return state

            self.state_store.mutate(key, increment, default={})
            self._maybe_report(cycle_id)
        else:
            self.tally[envelope.type] = self.tally.get(envelope.type, 0) + 1
            if envelope.type == "ops.dead_letter.v1":
                self.tally["ops.incident.v1"] = self.tally.get("ops.incident.v1", 0) + 1

    def _counts(self, cycle_id: str | None) -> dict[str, int]:
        if self.state_store is not None and cycle_id:
            state = self.state_store.get(f"executive/tally/{cycle_id}", {})
            return state.get("counts", state)
        return dict(self.tally)

    def _maybe_report(self, cycle_id: str) -> None:
        if self.state_store is None:
            meta = self.tally.get(f"__cycle_meta__:{cycle_id}")
        else:
            meta = self.state_store.get(f"executive/cycle-meta/{cycle_id}")
        if not meta:
            return
        counts = self._counts(cycle_id)
        if counts.get("validation.verdict.v1", 0) < meta["validation_count"]:
            return
        if counts.get("cycle.macro_news_completed.v1", 0) < 1:
            return
        macro_news = meta.get("macro_news", {})
        if counts.get("news.alert.v1", 0) < macro_news.get("alerts_published", 0):
            return
        if macro_news.get("regime_published") and counts.get("macro.regime.v1", 0) < 1:
            return
        if counts.get("ops.incident.v1", 0) < macro_news.get("incident_count", 0):
            return
        report_key = f"executive/reported/{cycle_id}"
        if self.state_store is not None and self.state_store.get(report_key, False):
            return
        report = self.daily_report(
            cycle_date=meta["cycle_date"],
            budget=meta.get("budget", {}),
            summary=(
                f"validaciones: {counts.get('validation.verdict.v1', 0)}, "
                f"incidentes: {counts.get('ops.incident.v1', 0)}, "
                f"regímenes: {counts.get('macro.regime.v1', 0)}"
            ),
            cycle_id=cycle_id,
        )
        if self.state_store is not None:
            self.state_store.set(report_key, {"report_id": report.payload["report_id"]})

    def daily_report(
        self,
        cycle_date: str,
        budget: dict[str, Any],
        summary: str = "",
        cycle_id: str | None = None,
    ) -> Envelope:
        report_id = (
            f"rep-{hashlib.sha256(cycle_id.encode()).hexdigest()[:16]}"
            if cycle_id else f"rep-{uuid.uuid4().hex[:8]}"
        )
        envelope_kwargs = {"correlation_id": cycle_id} if cycle_id else {}
        if cycle_id:
            envelope_kwargs["id"] = f"executive-report-{cycle_id}"
        return self.publish(
            "executive.daily_report.v1",
            {
                "report_id": report_id,
                "cycle_date": cycle_date,
                "counts": self._counts(cycle_id),
                "budget": budget,
                "summary": summary or "informe del ciclo",
                "cycle_id": cycle_id,
            },
            **envelope_kwargs,
        )
