"""Directrices de dirección: la voz del CEO en el sistema (departamento ejecutivo).

Las directivas viven en `config/directivas.yaml` y son el único mecanismo por el
que el CEO cambia los guardarraíles operativos (K-5): el scheduler las carga al
inicio de cada ciclo, aplica la vigente sobre la política de validación y audita
`directive.applied`. Lo que la directiva no sobreescribe queda igual; el histórico
completo queda en el audit log para auditoría.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class Directive(BaseModel):
    """Una instrucción del CEO con overrides sobre la política de validación."""

    id: str
    date: str  # ISO; la vigente es la de fecha máxima
    author: str = "CEO"
    summary: str
    overrides: dict[str, Any] = Field(default_factory=dict)


class DirectivesBoard:
    """Carga y aplica las directivas vigentes. Sin directivas, política intacta."""

    def __init__(self, directives: list[Directive]) -> None:
        self.directives = sorted(directives, key=lambda d: (d.date, d.id))

    @classmethod
    def load(cls, path: str | Path) -> "DirectivesBoard | None":
        """Devuelve None si el fichero no existe (todavía no hay directrices)."""
        path = Path(path)
        if not path.exists():
            return None
        raw = yaml.safe_load(path.read_text()) or {}
        directives = [Directive.model_validate(item) for item in raw.get("directives") or []]
        return cls(directives)

    def current(self) -> Directive | None:
        """La directiva más reciente, o None si no hay."""
        return self.directives[-1] if self.directives else None

    def apply_to_policy(self, policy: Any) -> Any:
        """Devuelve una copia de `policy` con los overrides de la directiva vigente.

        Solo sobreescribe campos que la política ya conoce (ValidationPolicy es un
        dataclass congelado): una directiva con claves desconocidas se ignora a
        nivel de política (queda en el audit), nunca inventa comportamiento.
        """
        directive = self.current()
        if directive is None:
            return policy
        known = {f.name for f in dataclasses.fields(policy)}
        safe = {k: v for k, v in directive.overrides.items() if k in known}
        return dataclasses.replace(policy, **safe)
