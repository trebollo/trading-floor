"""Permission Broker: guardarrail G1 — lista cerrada de herramientas y salidas.

Todo agente declara en `config/guardrails.yaml` qué herramientas puede usar y qué
tipos de mensaje puede publicar. Lo que no está en la lista no existe para el agente.
Las violaciones se registran en el audit log y escalan: 3 violaciones = suspensión (V3).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class PermissionDenied(PermissionError):
    def __init__(self, agent: str, kind: str, target: str) -> None:
        super().__init__(f"{agent}: {kind} no permitido: {target}")
        self.agent = agent
        self.kind = kind
        self.target = target


from pydantic import BaseModel, Field  # noqa: E402


class AgentPolicy(BaseModel):
    agent: str
    department: str
    role: str
    tools: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)  # tipos de mensaje que puede publicar
    data_domains: list[str] = Field(default_factory=list)
    budget: dict[str, float] = Field(default_factory=dict)


VIOLATIONS_BEFORE_SUSPENSION = 3


class PermissionBroker:
    def __init__(self, policies: dict[str, AgentPolicy], audit: Any | None = None) -> None:
        self._policies = policies
        self._audit = audit
        self.violations: dict[str, int] = {}
        self.suspended: set[str] = set()

    # -- carga de configuración -------------------------------------------------

    @classmethod
    def from_yaml(cls, path: str | Path, audit: Any | None = None) -> "PermissionBroker":
        raw = yaml.safe_load(Path(path).read_text())["agents"]
        policies = {
            name: AgentPolicy(agent=name, **spec) for name, spec in raw.items()
        }
        return cls(policies, audit=audit)

    # -- consultas --------------------------------------------------------------

    def policy(self, agent: str) -> AgentPolicy:
        try:
            return self._policies[agent]
        except KeyError:
            raise PermissionDenied(agent, "existencia", "agente sin política declarada") from None

    def is_suspended(self, agent: str) -> bool:
        return agent in self.suspended

    # -- enforcement ------------------------------------------------------------

    def allow_tool(self, agent: str, tool: str) -> bool:
        return tool in self.policy(agent).tools

    def allow_publish(self, agent: str, msg_type: str) -> bool:
        return msg_type in self.policy(agent).outputs

    def check_tool(self, agent: str, tool: str) -> None:
        if self.is_suspended(agent):
            raise PermissionDenied(agent, "agente suspendido", tool)
        if not self.allow_tool(agent, tool):
            self._record_violation(agent, "tool", tool)
            raise PermissionDenied(agent, "herramienta", tool)

    def check_publish(self, agent: str, msg_type: str, ignore_suspension: bool = False) -> None:
        if not ignore_suspension and self.is_suspended(agent):
            raise PermissionDenied(agent, "agente suspendido", msg_type)
        if not self.allow_publish(agent, msg_type):
            self._record_violation(agent, "publish", msg_type)
            raise PermissionDenied(agent, "publicación", msg_type)

    def _record_violation(self, agent: str, kind: str, target: str) -> None:
        self.violations[agent] = self.violations.get(agent, 0) + 1
        if self._audit is not None:
            self._audit.append(
                actor="permission-broker",
                event_type="guardrail.violation",
                payload={"agent": agent, "kind": kind, "target": target, "count": self.violations[agent]},
            )
        if self.violations[agent] >= VIOLATIONS_BEFORE_SUSPENSION:
            self.suspended.add(agent)
            if self._audit is not None:
                self._audit.append(
                    actor="permission-broker",
                    event_type="guardrail.agent_suspended",
                    payload={"agent": agent, "violations": self.violations[agent]},
                )
