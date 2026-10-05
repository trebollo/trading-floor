"""Agente de Research con LLM real (Fase 4): hipótesis generativas + filtro Jev.

Sustituye a `ResearchTemplateAgent` manteniendo su interfaz (`generate()` devuelve
`list[(envelope, seed)]`) y sus guardarraíles: los LLM *proponen*, el código
determinista *dispone* — el spec se valida con el DSL, la memoria (R-4/R-5) bloquea
ideas fracasadas y Jev solo filtra plausibilidad. Si falta credencial para algún
modelo, el agente degrada a la plantilla determinista y audita el failover; nunca
falla el pipeline por el proveedor.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from tf.gateway import JevClient, ModelGateway, OpenAICompatClient
from tf.pipeline import ResearchTemplateAgent

SYSTEM_PROMPT = (
    "Eres un investigador cuantitativo de un sistema de trading algorítmico autónomo. "
    "Generas hipótesis de trading expresadas como specs de un DSL cerrado. Solo puedes "
    "usar estos tipos de estrategia, con parámetros numéricos: sma_cross(fast_window, "
    "slow_window), breakout(lookback, exit_buffer), rsi_reversion(rsi_window, lower, "
    "upper), momentum(lookback, threshold). Devuelve EXCLUSIVAMENTE un array JSON de "
    "objetos {\"hypothesis\": str, \"spec\": {\"type\": str, \"params\": dict}}, sin markdown "
    "ni explicaciones. En sma_cross, fast_window debe ser menor que slow_window."
)

# Umbral Jev: por debajo, la hipótesis no se publica (se audita el descarte).
NOUL_THRESHOLD = 0.6

JEV_QUESTIONS: dict[str, dict[str, Any]] = {
    "mechanism_plausible": {
        "type": "noul",
        "instructions": "¿La hipótesis describe un mecanismo causal plausible de anomalía de mercado (momentum, reversión, ruptura)?",
    },
    "not_noise": {
        "type": "noul",
        "instructions": "¿La hipótesis es específica y falsable, en lugar de una frase genérica sin contenido predictivo?",
    },
}


class ResearchLLMAgent(ResearchTemplateAgent):
    """research-hypothesis con modelos reales vía Model Gateway."""

    def __init__(
        self,
        gateway: ModelGateway,
        generative: OpenAICompatClient | None,
        jev: JevClient | None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.gateway = gateway
        self.generative = generative
        self.jev = jev

    @classmethod
    def from_gateway(
        cls, gateway: ModelGateway, env: dict[str, str] | None = None, **kwargs: Any
    ) -> "ResearchLLMAgent":
        """Construye el agente con los clientes del gateway; los que falten quedan None."""
        return cls(
            gateway=gateway,
            generative=gateway.client_for("research-hypothesis", "generative", env=env),
            jev=gateway.client_for("research-hypothesis", "evaluator", env=env),
            **kwargs,
        )

    # -- generación ----------------------------------------------------------

    def generate(self, count: int | None = None) -> list[tuple[Any, dict[str, Any]]]:
        if self.generative is None:
            self._audit_failover("sin credencial del modelo generativo; uso plantilla determinista")
            return super().generate(count)
        raw = self.generative.complete(system=SYSTEM_PROMPT, user=self._user_prompt(count or 5))
        seeds = self._parse_proposals(raw)
        out = []
        for seed in seeds:
            blocked, reason = self._blocked_reason(seed)
            if blocked:
                self.audit.append(
                    actor=self.name,
                    event_type="research.proposal_skipped",
                    payload={"hypothesis": seed["hypothesis"], "reason": reason},
                )
                continue
            if not self._jev_accepts(seed):
                self.audit.append(
                    actor=self.name,
                    event_type="research.proposal_skipped",
                    payload={"hypothesis": seed["hypothesis"], "reason": "jev: plausibilidad por debajo del umbral"},
                )
                continue
            out.append((self._publish_proposal(seed), seed))
        return out

    def _user_prompt(self, count: int) -> str:
        context = []
        if self.memory is not None and self.memory.lessons:
            lessons = self.memory.query_lessons("hipótesis de trading", k=5)
            if lessons:
                context.append("Lecciones aprendidas de iteraciones anteriores:")
                context.extend(f"- {l.text}" for l in lessons)
        context.append(f"Genera {count} hipótesis nuevas que eviten esos fallos.")
        return "\n".join(context)

    def _parse_proposals(self, raw: str) -> list[dict[str, Any]]:
        """Convierte la respuesta del LLM en seeds; los specs inválidos se auditan y caen."""
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("```")[1].removeprefix("json").strip()
        try:
            proposals = json.loads(text)
        except json.JSONDecodeError:
            self.audit.append(
                actor=self.name,
                event_type="model.output_invalid",
                payload={"model": "generativo", "reason": "respuesta no es JSON válido"},
            )
            return []
        seeds = []
        for p in proposals if isinstance(proposals, list) else []:
            seed = {"hypothesis": str(p.get("hypothesis", "")), "spec": p.get("spec")}
            ok, reason = self._spec_ok(seed)
            if ok:
                seeds.append(seed)
            else:
                self.audit.append(
                    actor=self.name,
                    event_type="research.proposal_skipped",
                    payload={"hypothesis": seed["hypothesis"], "reason": reason},
                )
        return seeds

    def _spec_ok(self, seed: dict[str, Any]) -> tuple[bool, str]:
        from tf.dsl import SpecError, validate_spec

        spec = seed["spec"]
        if not isinstance(spec, dict) or not seed["hypothesis"]:
            return False, "formato: falta hypothesis o spec"
        try:
            validate_spec(spec)
        except SpecError as e:
            return False, f"spec inválido: {e}"
        return True, ""

    # R-4/R-5 reutilizados de la plantilla; devuelve (bloqueada, motivo).
    def _blocked_reason(self, seed: dict[str, Any]) -> tuple[bool, str]:
        if self._is_blocked(seed):
            return True, "memoria: idea ya fracasada o familia bloqueada"
        return False, ""

    def _jev_accepts(self, seed: dict[str, Any]) -> bool:
        if self.jev is None:
            self._audit_failover("sin credencial del modelo evaluador (Jev); filtro Jev desactivado")
            return True  # sin evaluador no se bloquea: la validación determinista sigue después
        state = json.dumps({"hypothesis": seed["hypothesis"], "spec": seed["spec"]}, ensure_ascii=False)
        answers = self.jev.evaluate(state, JEV_QUESTIONS)
        for name in JEV_QUESTIONS:
            noul = answers.get(name, {}).get("noul")
            if noul is not None and noul < NOUL_THRESHOLD:
                return False
        return True

    def _publish_proposal(self, seed: dict[str, Any]) -> Any:
        return self.publish(
            "strategy.proposal.v1",
            {
                "proposal_id": f"prop-{uuid.uuid4().hex[:8]}",
                "hypothesis": seed["hypothesis"],
                "universe": ["SYNTH"],
                "timeframe": "1d",
                "entry_rules": "según spec",
                "exit_rules": "según spec",
                "prior_risk_estimate": "0.5% por operación",
                "cited_lesson_ids": [],
            },
        )

    def _audit_failover(self, reason: str) -> None:
        self.audit.append(
            actor=self.name,
            event_type="model.failover",
            payload={"agent": self.name, "from_model": "gateway", "to_model": None, "reason": reason},
        )
