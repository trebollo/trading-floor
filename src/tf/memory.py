"""Memoria colectiva de aprendizaje (Fase 3, §5 arquitectura).

Lecciones estructuradas + índice de evaluaciones + bloqueo de familias (R-5).
Los embeddings usan hashing determinista (trick de firmas) con similitud coseno:
mismo contrato que pgvector en producción; sin dependencia de modelos externos.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

EMBED_DIM = 256
DEDUP_SIMILARITY = 0.90


def embed(text: str) -> dict[int, float]:
    """Embedding determinista por hashing con signo (bag-of-words ponderado)."""
    vec: dict[int, float] = {}
    for token in re.findall(r"[a-záéíóúñü]+", text.lower()):
        if len(token) < 3:
            continue
        digest = hashlib.sha256(token.encode()).digest()
        idx = int.from_bytes(digest[:4], "big") % EMBED_DIM
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vec[idx] = vec.get(idx, 0.0) + sign
    return vec


def cosine(a: dict[int, float], b: dict[int, float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(v * b.get(i, 0.0) for i, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


# ---------------------------------------------------------------------------
# Lecciones y evaluaciones
# ---------------------------------------------------------------------------


@dataclass
class Lesson:
    id: str
    content: str
    tags: list[str]
    source_evaluation_id: str | None
    family_key: str | None          # p. ej. "sma_cross|SYNTH" (para R-5)
    embedding: dict[int, float]
    times_referenced: int = 0
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class EvaluationRecord:
    id: str
    spec_id: str
    kind: str                        # backtest | validation | risk_review | postmortem
    verdict: str
    summary: str
    family_key: str | None = None
    spec_fp: str | None = None       # huella del spec exacto (R-4)
    metrics: dict[str, float] = field(default_factory=dict)


def family_key_of(spec: dict[str, Any], universe: list[str] | None = None) -> str:
    """Clave de familia: tipo + universo. Base del bloqueo R-5."""
    return f"{spec.get('type', '?')}|{(universe or spec.get('universe', ['?']))[0]}"


def spec_fingerprint(spec: dict[str, Any]) -> str:
    """Huella del spec exacto (tipo + parámetros): detección de ideas repetidas (R-4)."""
    material = json.dumps(spec, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(material.encode()).hexdigest()[:16]


class MemoryStore:
    """Memoria episódica y semántica. La escriben los eventos; los agentes solo leen."""

    def __init__(self) -> None:
        self.lessons: list[Lesson] = []
        self.evaluations: list[EvaluationRecord] = []

    # -- escritura ----------------------------------------------------------------

    def add_evaluation(
        self,
        spec_id: str,
        kind: str,
        verdict: str,
        summary: str,
        spec: dict[str, Any] | None = None,
        metrics: dict[str, float] | None = None,
    ) -> EvaluationRecord:
        rec = EvaluationRecord(
            id=f"eval-{uuid.uuid4().hex[:8]}",
            spec_id=spec_id,
            kind=kind,
            verdict=verdict,
            summary=summary,
            family_key=family_key_of(spec) if spec else None,
            spec_fp=spec_fingerprint(spec) if spec else None,
            metrics=metrics or {},
        )
        self.evaluations.append(rec)
        return rec

    def add_lesson(
        self, content: str, tags: list[str] | None = None, source_evaluation_id: str | None = None,
        family_key: str | None = None,
    ) -> Lesson | None:
        """Alta de lección con deduplicación semántica: similar ≥ 0.9 ⇒ refuerza la existente."""
        emb = embed(content)
        for lesson in self.lessons:
            if cosine(emb, lesson.embedding) >= DEDUP_SIMILARITY:
                lesson.times_referenced += 1
                return None  # deduplicada: ya se aprendió esto
        lesson = Lesson(
            id=f"les-{uuid.uuid4().hex[:8]}",
            content=content,
            tags=tags or [],
            source_evaluation_id=source_evaluation_id,
            family_key=family_key,
            embedding=emb,
        )
        self.lessons.append(lesson)
        return lesson

    # -- consultas (las que usan los agentes) ---------------------------------------

    def query_lessons(self, context: str, k: int = 5) -> list[Lesson]:
        emb = embed(context)
        ranked = sorted(self.lessons, key=lambda l: (cosine(emb, l.embedding), l.times_referenced), reverse=True)
        return ranked[:k]

    def family_rejections(self, spec: dict[str, Any]) -> list[EvaluationRecord]:
        """Evaluaciones desfavorables de la familia (para el bloqueo R-5)."""
        key = family_key_of(spec)
        return [
            e for e in self.evaluations
            if e.family_key == key and e.verdict in ("RECHAZAR", "RECHAZADA", "RECHAZADA_BACKTEST", "RECHAZADA_BATERIA")
        ]

    def is_spec_dead(self, spec: dict[str, Any]) -> bool:
        """R-4: este spec exacto ya fue rechazado antes; no se vuelve a proponer."""
        fp = spec_fingerprint(spec)
        return any(e.spec_fp == fp and e.verdict in ("RECHAZAR", "RECHAZADA", "RECHAZADA_BACKTEST", "RECHAZADA_BATERIA") for e in self.evaluations)

    def is_family_locked(self, spec: dict[str, Any], max_rejections: int = 3) -> bool:
        """R-5: familia con 3+ fracasos de validación ⇒ bloqueada hasta directriz del CEO."""
        return len(self.family_rejections(spec)) >= max_rejections


# ---------------------------------------------------------------------------
# Extractor de lecciones (reglas en Fase 3; LLM después, misma interfaz)
# ---------------------------------------------------------------------------


class LessonExtractor:
    """Convierte desenlaces de evaluación en lecciones estructuradas."""

    def from_backtest(self, spec: dict[str, Any], verdict: str, metrics: dict[str, float]) -> list[dict[str, Any]]:
        lessons = []
        fkey = family_key_of(spec)
        if verdict == "RECHAZAR" and metrics.get("total_return", 0) < 0:
            lessons.append({
                "content": f"La familia {spec['type']} con estos parámetros pierde en régimen tendencial: "
                           f"retorno {metrics.get('total_return', 0):.1%}, profit factor {metrics.get('profit_factor', 0):.2f}.",
                "tags": [spec["type"], "backtest", "perdedora"],
                "family_key": fkey,
            })
        if verdict == "RECHAZAR" and 0 < metrics.get("n_trades", 0) < 100:
            lessons.append({
                "content": f"Estrategia {spec['type']} sin mínimo estadístico ({metrics.get('n_trades', 0):.0f} operaciones): "
                           f"no promocionar sin más datos o mayor frecuencia.",
                "tags": [spec["type"], "backtest", "minimo-estadistico"],
                "family_key": fkey,
            })
        return lessons

    def from_battery(self, spec: dict[str, Any], checks: dict[str, bool], details: dict[str, Any]) -> list[dict[str, Any]]:
        lessons = []
        fkey = family_key_of(spec)
        failures = [point for point, ok in checks.items() if not ok]
        mapping = {
            "monte_carlo": "la distribución de Monte Carlo no garantiza rentabilidad en el P5",
            "walk_forward": "el rendimiento in-sample no sobrevive fuera de muestra (walk-forward)",
            "param_sensitivity": "el retorno invierte el signo con perturbaciones de ±20 % en parámetros",
            "cost_robustness": "no soporta el doble de costes asumidos",
            "regimen_stress": "pierde de forma acumulada en régimen adverso",
            "portfolio_correlation": "aporta riesgo correlacionado excesivo al portfolio",
        }
        for point in failures:
            lessons.append({
                "content": f"{spec['type']}: {mapping[point]}.",
                "tags": [spec["type"], "bateria", point],
                "family_key": fkey,
            })
        return lessons
