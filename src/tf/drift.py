"""Drift detection y comité semanal (Fase 3, §6 arquitectura).

Compara el rendimiento real de cada estrategia viva con el previsto por su backtest:
desviación ⇒ revalidación; drawdown propio superado ⇒ retiro automático (contrato).
El comité semanal propone: SUBIR | MANTENER | REDUCIR | RETIRAR — solo lo que supera
umbrales llega al CEO (§6).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np

from tf.memory import MemoryStore
from tf.risk import StrategyContract


class DriftVerdict(str, Enum):
    OK = "OK"
    REVISAR = "REVISAR"          # warning: vigilar la próxima semana
    REVALIDAR = "REVALIDAR"      # batería obligatoria antes de seguir operando
    RETIRAR = "RETIRAR"          # contrato de drawdown propio roto: retiro automático


@dataclass
class StrategyPerformance:
    strategy_id: str
    contract: StrategyContract
    expected_sharpe: float           # del backtest de promoción
    daily_returns: list[float]       # retornos diarios reales desde el despliegue
    equity_peak: float = 1.0


@dataclass
class DriftReport:
    strategy_id: str
    verdict: DriftVerdict
    realized_sharpe: float
    own_drawdown: float
    reason: str


def _rolling_sharpe(daily_returns: np.ndarray, window: int = 20) -> float:
    if len(daily_returns) < window:
        window = max(len(daily_returns), 2)
    tail = daily_returns[-window:]
    std = float(np.std(tail, ddof=1)) if len(tail) > 1 else 0.0
    if std == 0:
        return 0.0
    return float(np.mean(tail) / std * np.sqrt(252))


class DriftDetector:
    """Semáforo semanal por estrategia. Determinista; los umbrales son política."""

    def __init__(
        self,
        revalidate_sharpe_ratio: float = 0.3,
        review_sharpe_ratio: float = 0.6,
        min_days: int = 20,
    ) -> None:
        self.revalidate_sharpe_ratio = revalidate_sharpe_ratio
        self.review_sharpe_ratio = review_sharpe_ratio
        self.min_days = min_days

    def check(self, perf: StrategyPerformance) -> DriftReport:
        returns = np.asarray(perf.daily_returns, dtype=float)
        equity = np.cumprod(1.0 + returns) if len(returns) else np.array([1.0])
        peak = max(perf.equity_peak, float(equity.max()))
        own_dd = float(1.0 - equity[-1] / peak) if peak > 0 else 0.0
        realized = _rolling_sharpe(returns)

        # 1) Contrato: drawdown propio roto ⇒ retiro automático (sin decisión).
        if own_dd >= perf.contract.max_own_drawdown:
            return DriftReport(perf.strategy_id, DriftVerdict.RETIRAR, realized, own_dd,
                               f"drawdown propio {own_dd:.2%} ≥ contrato {perf.contract.max_own_drawdown:.2%}")

        # 2) Datos insuficientes: no se opina sin mínimo estadístico (B-4 espíritu).
        if len(returns) < self.min_days:
            return DriftReport(perf.strategy_id, DriftVerdict.OK, realized, own_dd,
                               f"observación insuficiente ({len(returns)} días < {self.min_days})")

        # 3) Drift de Sharpe: real vs previsto.
        if perf.expected_sharpe > 0 and realized < self.revalidate_sharpe_ratio * perf.expected_sharpe:
            return DriftReport(perf.strategy_id, DriftVerdict.REVALIDAR, realized, own_dd,
                               f"Sharpe real {realized:.2f} < {self.revalidate_sharpe_ratio:.0%} del previsto {perf.expected_sharpe:.2f}")
        if perf.expected_sharpe > 0 and realized < self.review_sharpe_ratio * perf.expected_sharpe:
            return DriftReport(perf.strategy_id, DriftVerdict.REVISAR, realized, own_dd,
                               f"Sharpe real {realized:.2f} degradado vs previsto {perf.expected_sharpe:.2f}")
        return DriftReport(perf.strategy_id, DriftVerdict.OK, realized, own_dd, "rendimiento acorde a lo previsto")


# ---------------------------------------------------------------------------
# Comité semanal
# ---------------------------------------------------------------------------


@dataclass
class CommitteeProposal:
    strategy_id: str
    action: str                 # SUBIR_CAPITAL | MANTENER | REDUCIR | RETIRAR | REVALIDAR
    needs_ceo: bool
    reason: str


class WeeklyCommittee:
    """Risk + Validation re-puntúan el portfolio; solo las decisiones por encima de
    umbral llegan al CEO (§6). Fase 3: reglas deterministas."""

    def __init__(self, memory: MemoryStore, retire_is_automatic: bool = True) -> None:
        self.memory = memory
        self.retire_is_automatic = retire_is_automatic

    def review(self, performances: list[StrategyPerformance], detector: DriftDetector | None = None) -> list[CommitteeProposal]:
        detector = detector or DriftDetector()
        proposals = []
        for perf in performances:
            report = detector.check(perf)
            if report.verdict == DriftVerdict.RETIRAR:
                proposals.append(CommitteeProposal(perf.strategy_id, "RETIRAR", needs_ceo=not self.retire_is_automatic, reason=report.reason))
            elif report.verdict == DriftVerdict.REVALIDAR:
                proposals.append(CommitteeProposal(perf.strategy_id, "REVALIDAR", needs_ceo=False, reason=report.reason))
            elif report.verdict == DriftVerdict.REVISAR:
                proposals.append(CommitteeProposal(perf.strategy_id, "REDUCIR", needs_ceo=True, reason=report.reason))
            else:
                proposals.append(CommitteeProposal(perf.strategy_id, "MANTENER", needs_ceo=False, reason=report.reason))
        return proposals


# ---------------------------------------------------------------------------
# Post-mortem: toda retirada genera lecciones (aprendizaje, no castigo)
# ---------------------------------------------------------------------------


def postmortem_lessons(
    spec: dict[str, Any],
    realized_sharpe: float,
    expected_sharpe: float,
    own_drawdown: float,
    days_alive: int,
) -> list[dict[str, Any]]:
    lessons = [{
        "content": f"Retirada {spec['type']} tras {days_alive} días: Sharpe real {realized_sharpe:.2f} vs previsto "
                   f"{expected_sharpe:.2f} y drawdown propio {own_drawdown:.1%}. "
                   + ("El backtest sobreestimaba el rendimiento: revisar costes/regímenes de la familia."
                      if realized_sharpe < expected_sharpe * 0.5 else
                      "El rendimiento real fue coherente con lo previsto; el retiro responde al contrato de drawdown."),
        "tags": [spec["type"], "postmortem"],
        "family_key": None,
    }]
    return lessons
