"""G3 · Presupuesto: cuánto puede gastar cada agente y el sistema entero.

Los límites viven en `config/guardrails.yaml` (sección `budgets` global y `budget`
por agente). El gobernador mantiene contadores de ventana (día UTC para tokens y
euros, hora para llamadas), los persiste en disco (reiniciar no resetea el gasto) y
audita cada bloqueo. Exceder un límite lanza `BudgetExceeded`: el agente debe degradar
a ruta determinista y dejar failover auditado — nunca ignorar el corte.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class BudgetExceeded(RuntimeError):
    """El agente agotó su presupuesto (G3). El agente debe degradar, no reintentar."""


@dataclass
class BudgetLimits:
    default_tokens_per_day: int = 2_000_000
    calls_per_hour: int = 60
    global_eur_per_day: float = 5.0
    # Overrides por agente declarados en guardrails.yaml (budget.tokens_per_day, etc.).
    per_agent: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "BudgetLimits":
        import yaml

        raw = yaml.safe_load(Path(path).read_text())
        budgets = raw.get("budgets") or {}
        per_agent = {
            name: (spec.get("budget") or {}) for name, spec in (raw.get("agents") or {}).items()
        }
        return cls(
            default_tokens_per_day=int(budgets.get("default_tokens_per_day", cls.default_tokens_per_day)),
            calls_per_hour=int(budgets.get("calls_per_hour", cls.calls_per_hour)),
            global_eur_per_day=float(budgets.get("global_eur_per_day", cls.global_eur_per_day)),
            per_agent=per_agent,
        )


class CostGovernor:
    """Contadores de gasto con ventanas diarias/horarias y estado persistente."""

    def __init__(
        self,
        limits: BudgetLimits | None = None,
        state_path: str | Path | None = None,
        audit: Any | None = None,
        now: float | None = None,
    ) -> None:
        self.limits = limits or BudgetLimits()
        self.state_path = Path(state_path) if state_path else None
        self.audit = audit
        self._now = now
        self._usage = self._load_state()
        if "days" not in self._usage:
            self._usage = {"days": {}}

    # -- tiempo (inyectable para tests) ------------------------------------------

    def _clock(self) -> float:
        return self._now if self._now is not None else time.time()

    def _day(self) -> str:
        return datetime.fromtimestamp(self._clock(), tz=timezone.utc).strftime("%Y-%m-%d")

    def _hour(self) -> int:
        return int(self._clock() // 3600)

    # -- límites -------------------------------------------------------------------

    def _tokens_per_day(self, agent: str) -> int:
        return int((self.limits.per_agent.get(agent) or {}).get("tokens_per_day", self.limits.default_tokens_per_day))

    # -- estado -------------------------------------------------------------------

    def _load_state(self) -> dict[str, Any]:
        if self.state_path and self.state_path.exists():
            return json.loads(self.state_path.read_text())
        return {}

    def _persist(self) -> None:
        if self.state_path:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps(self._usage, indent=2))

    # -- API ------------------------------------------------------------------------

    def check(self, agent: str) -> None:
        """Lanza BudgetExceeded si alguna ventana del agente (o global) está agotada."""
        day = self._usage["days"].get(self._day(), {})
        agent_usage = day.get("agents", {}).get(agent, {})

        tokens = agent_usage.get("tokens", 0)
        tokens_limit = self._tokens_per_day(agent)
        if tokens >= tokens_limit:
            self._blocked(agent, f"tokens diarios {tokens} ≥ límite {tokens_limit}")

        calls_hour_key = str(self._hour())
        calls = day.get("calls_by_hour", {}).get(calls_hour_key, {}).get(agent, 0)
        if calls >= self.limits.calls_per_hour:
            self._blocked(agent, f"llamadas en la hora {calls} ≥ límite {self.limits.calls_per_hour}")

        eur_global = day.get("eur", 0.0)
        if eur_global >= self.limits.global_eur_per_day:
            self._blocked(agent, f"presupuesto global diario {eur_global:.2f}€ ≥ {self.limits.global_eur_per_day:.2f}€")

    def _blocked(self, agent: str, reason: str) -> None:
        if self.audit is not None:
            self.audit.append(
                actor="budget", event_type="budget.exceeded", payload={"agent": agent, "reason": reason}
            )
        raise BudgetExceeded(f"{agent}: {reason}")

    def record(self, agent: str, input_tokens: int, output_tokens: int, cost_usd: float = 0.0) -> None:
        day = self._usage["days"].setdefault(self._day(), {"agents": {}, "calls_by_hour": {}, "eur": 0.0})
        agent_usage = day["agents"].setdefault(agent, {"tokens": 0, "eur": 0.0})
        agent_usage["tokens"] += input_tokens + output_tokens
        agent_usage["eur"] = round(agent_usage["eur"] + cost_usd, 6)
        day["eur"] = round(day["eur"] + cost_usd, 6)
        hour = day["calls_by_hour"].setdefault(str(self._hour()), {})
        hour[agent] = hour.get(agent, 0) + 1
        self._persist()

    def usage(self) -> dict[str, Any]:
        return self._usage["days"].get(self._day(), {"agents": {}, "eur": 0.0})
