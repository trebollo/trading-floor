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
        """Failover registrado como evento (auditado). Fase 0: solo publica el evento."""
        if bus is not None:
            bus.publish_raw(
                "model.failover.v1",
                {"agent": agent, "from_model": from_model, "to_model": None, "reason": reason},
            )
