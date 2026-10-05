"""Model Gateway: los modelos son configuración, no código (§7.1 de la arquitectura).

Ningún agente conoce su proveedor. El Gateway tipa los modelos (`generative` vs
`evaluator`) y valida en arranque que la asignación de cada agente es coherente:
una configuración inválida impide el arranque, nunca se ignora.

Fase 0: sin llamadas reales a LLM. Los proveedores se conectan en Fase 1; lo que ya
queda fijado es el contrato de tipado, routing y failover.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator


class ModelConfig(BaseModel):
    name: str
    kind: Literal["generative", "evaluator"]
    id: str | None = None  # id externo, p. ej. "typesafe-ai/jev" vía Vercel AI Gateway
    tier: Literal["premium", "standard", "economic"] | None = None
    input_cost_per_mtok: float | None = None
    context_window: int | None = None
    # Fase 4: proveedor real (clientes HTTP en este módulo).
    provider: Literal["vercel-ai-gateway", "opencode-go"] | None = None
    endpoint: str | None = None  # base URL de la API
    api_key_env: str | None = None  # variable de entorno con la credencial

    @model_validator(mode="after")
    def _external_id_for_evaluator(self) -> "ModelConfig":
        # Un evaluador se consume vía API externa tipada; debe tener id declarado.
        if self.kind == "evaluator" and not self.id:
            raise ValueError(f"el modelo evaluador '{self.name}' debe declarar su id externo")
        return self


class AgentModelAssignment(BaseModel):
    generative: str | None = None
    decisions: str | None = None
    # Una asignación vacía es válida: agente determinista, sin LLM en su camino.

class GatewayConfig(BaseModel):
    models: dict[str, ModelConfig]
    agents: dict[str, AgentModelAssignment]

    @model_validator(mode="before")
    @classmethod
    def _inject_model_names(cls, data: Any) -> Any:
        # La clave del dict es el nombre del modelo; no se repite dentro.
        for name, spec in (data.get("models") or {}).items():
            if isinstance(spec, dict) and "name" not in spec:
                spec["name"] = name
        return data

    @model_validator(mode="after")
    def _validate_assignments(self) -> "GatewayConfig":
        for agent, assignment in self.agents.items():
            for field, kind_required in (("generative", "generative"), ("decisions", "evaluator")):
                model_name = getattr(assignment, field)
                if model_name is None:
                    continue
                model = self.models.get(model_name)
                if model is None:
                    raise ValueError(
                        f"agente '{agent}': modelo '{model_name}' no declarado en la sección models"
                    )
                if model.kind != kind_required:
                    raise ValueError(
                        f"agente '{agent}': '{field}' requiere un modelo {kind_required}, "
                        f"pero '{model_name}' es {model.kind}"
                    )
        return self


class ModelGateway:
    def __init__(self, config: GatewayConfig) -> None:
        self._config = config

    @classmethod
    def from_yaml(cls, path: str | Path) -> "ModelGateway":
        raw = yaml.safe_load(Path(path).read_text())
        return cls(GatewayConfig.model_validate(raw))

    def resolve(self, agent: str, kind: Literal["generative", "evaluator"]) -> ModelConfig:
        """Devuelve el modelo asignado a un agente para un tipo de tarea."""
        assignment = self._config.agents.get(agent)
        if assignment is None:
            raise KeyError(f"agente sin asignación de modelos: {agent}")
        model_name = assignment.generative if kind == "generative" else assignment.decisions
        if model_name is None:
            raise KeyError(
                f"agente '{agent}' no tiene modelo {kind} asignado; "
                f"la configuración debe declararlo explícitamente"
            )
        return self._config.models[model_name]

    def record_failover(self, agent: str, from_model: str, reason: str, bus: Any | None = None) -> None:
        """Failover registrado como evento (auditado)."""
        if bus is not None:
            bus.publish_raw(
                "model.failover.v1",
                {"agent": agent, "from_model": from_model, "to_model": None, "reason": reason},
            )

    # -- runtime: clientes reales (Fase 4) -------------------------------------

    def client_for(
        self, agent: str, kind: Literal["generative", "evaluator"], env: dict[str, str] | None = None
    ) -> JevClient | OpenAICompatClient | None:
        """Cliente HTTP del modelo asignado, o None si falta credencial.

        None nunca se ignora en silencio: el agente que lo recibe debe degradar a su
        ruta determinista y auditar el failover (contrato de Fase 0).
        """
        import os

        model = self.resolve(agent, kind)
        if model.provider is None or model.api_key_env is None:
            return None  # modelo declarado sin proveedor real: ruta determinista
        api_key = (env or os.environ).get(model.api_key_env, "")
        if not api_key:
            return None
        if model.kind == "evaluator":
            return JevClient(model_id=model.id or model.name, api_key=api_key, base_url=model.endpoint or VERCEL_TYPESAFE_URL)
        return OpenAICompatClient(model_id=model.id or model.name, api_key=api_key, base_url=model.endpoint or "")


# ---------------------------------------------------------------------------
# Clientes HTTP de proveedores reales (Fase 4). Sin dependencias externas.
# ---------------------------------------------------------------------------

VERCEL_TYPESAFE_URL = "https://ai-gateway.vercel.sh/typesafe/v1"


def _post_json(url: str, api_key: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    import json as _json
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        url,
        data=_json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return _json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        # El motivo real (plan sin acceso, modelo deshabilitado, auth...) va en el cuerpo.
        body = e.read().decode(errors="replace")[:500]
        raise RuntimeError(f"HTTP {e.code} de {url}: {body}") from e


class JevClient:
    """Modelo evaluador (System One) vía un endpoint TypeSafe-compatible.

    OpenCode Zen: https://opencode.ai/zen/v1 · Vercel AI Gateway:
    https://ai-gateway.vercel.sh/typesafe/v1. Entra `state`, salen respuestas
    tipadas con probabilidades — Jev no genera texto. Pregunta tipos: noul
    (sí/no calibrado), choice (una opción de `criteria`) y score (escala ordenada).
    """

    def __init__(self, model_id: str, api_key: str, base_url: str = VERCEL_TYPESAFE_URL, timeout: float = 30.0) -> None:
        self.model_id = model_id
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def evaluate(self, state: str | dict[str, Any] | list[str], questions: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Devuelve {pregunta: respuesta} tal cual el proveedor (answers map)."""
        payload = {"model": self.model_id, "state": state, "questions": questions}
        resp = _post_json(f"{self.base_url}/systemone", self.api_key, payload, self.timeout)
        return resp.get("answers", {})


class OpenAICompatClient:
    """Modelo generativo vía API OpenAI-compatible (OpenCode Go: /zen/go/v1)."""

    def __init__(self, model_id: str, api_key: str, base_url: str, timeout: float = 60.0) -> None:
        self.model_id = model_id
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def complete(self, system: str, user: str, temperature: float = 0.7) -> str:
        payload = {
            "model": self.model_id,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": temperature,
        }
        resp = _post_json(f"{self.base_url}/chat/completions", self.api_key, payload, self.timeout)
        return resp["choices"][0]["message"]["content"]
