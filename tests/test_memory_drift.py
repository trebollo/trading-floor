"""Tests de la memoria colectiva (dedup, R-5, extractor) y del drift detection."""

import numpy as np
import pytest

from tf.drift import (
    CommitteeProposal,
    DriftDetector,
    DriftVerdict,
    StrategyPerformance,
    WeeklyCommittee,
    postmortem_lessons,
)
from tf.memory import MemoryStore, cosine, embed, family_key_of, LessonExtractor
from tf.risk import StrategyContract


# ---------------------------------------------------------------------------
# Embeddings y memoria
# ---------------------------------------------------------------------------


def test_embedding_deterministic_and_semantic():
    e1 = embed("sma_cross pierde en régimen adverso")
    e2 = embed("sma_cross pierde en régimen adverso")
    e3 = embed("momentum falla fuera de muestra en walk-forward")
    assert e1 == e2
    assert cosine(e1, e3) < 0.5  # temas distintos: baja similitud


def test_lesson_dedup_reinforces_instead_of_duplicating():
    mem = MemoryStore()
    first = mem.add_lesson("sma_cross pierde en régimen adverso por exposición mantenida")
    second = mem.add_lesson("sma_cross pierde en régimen adverso por exposición mantenida")
    assert first is not None and second is None  # deduplicada
    assert mem.lessons[0].times_referenced == 1


def test_family_key_and_rejection_count():
    mem = MemoryStore()
    spec = {"type": "sma_cross", "universe": ["SYNTH"]}
    assert family_key_of(spec) == "sma_cross|SYNTH"
    for i in range(3):
        mem.add_evaluation(f"spec-{i}", "validation", "RECHAZADA", f"fracaso {i}", spec=spec)
    assert len(mem.family_rejections(spec)) == 3
    assert mem.is_family_locked(spec)          # R-5: bloqueada
    assert not mem.is_family_locked(spec, max_rejections=4)


def test_query_lessons_ranks_relevant_first():
    mem = MemoryStore()
    mem.add_lesson("rsi_reversion pierde en mercados tendenciales por contra-tendencia")
    mem.add_lesson("el walk-forward detecta sobreajuste de ventanas rápidas")
    hits = mem.query_lessons("rsi_reversion contra-tendencia en mercado tendencial")
    assert "rsi_reversion" in hits[0].content


# ---------------------------------------------------------------------------
# Extractor de lecciones
# ---------------------------------------------------------------------------


def test_extractor_from_backtest_failures():
    extractor = LessonExtractor()
    spec = {"type": "sma_cross", "universe": ["SYNTH"]}
    lessons = extractor.from_backtest(spec, "RECHAZAR", {"total_return": -0.29, "n_trades": 21, "profit_factor": 0.5})
    assert len(lessons) == 2
    assert all(l["family_key"] == "sma_cross|SYNTH" for l in lessons)


def test_extractor_from_battery_failures_maps_each_point():
    extractor = LessonExtractor()
    spec = {"type": "momentum", "universe": ["SYNTH"]}
    checks = {"monte_carlo": True, "walk_forward": False, "regimen_stress": False,
              "param_sensitivity": True, "cost_robustness": True, "portfolio_correlation": True}
    lessons = extractor.from_battery(spec, checks, {})
    assert len(lessons) == 2
    contents = " ".join(l["content"] for l in lessons)
    assert "walk-forward" in contents and "régimen adverso" in contents


# ---------------------------------------------------------------------------
# Drift detection
# ---------------------------------------------------------------------------

CONTRACT = StrategyContract(strategy_id="s1", max_size=0.02, max_own_drawdown=0.10)


def perf(daily_returns, expected_sharpe=2.0) -> StrategyPerformance:
    return StrategyPerformance(strategy_id="s1", contract=CONTRACT, expected_sharpe=expected_sharpe, daily_returns=list(daily_returns))


def test_healthy_strategy_is_ok():
    rng = np.random.default_rng(3)
    returns = 0.002 + 0.005 * rng.standard_normal(60)  # Sharpe real ≈ previsto
    report = DriftDetector().check(perf(returns))
    assert report.verdict == DriftVerdict.OK


def test_insufficient_data_does_not_opine():
    report = DriftDetector().check(perf([0.001, -0.002, 0.001]))
    assert report.verdict == DriftVerdict.OK and "insuficiente" in report.reason


def test_degraded_sharpe_triggers_revalidate():
    rng = np.random.default_rng(8)
    # Degradación con drawdown dentro del contrato: solo procede revalidación.
    returns = (-0.0004 + 0.01 * rng.standard_normal(60)).tolist()
    report = DriftDetector().check(perf(returns))
    assert report.verdict == DriftVerdict.REVALIDAR


def test_breached_own_drawdown_triggers_automatic_retirement():
    # Picas: el equity sube al doble y luego pierde el 25 % ⇒ DD propio 50 % > 10 %.
    returns = [0.01] * 70 + [-0.005] * 50
    report = DriftDetector().check(perf(returns, expected_sharpe=2.0))
    assert report.verdict == DriftVerdict.RETIRAR


def test_committee_proposes_and_escalates_correctly():
    mem = MemoryStore()
    committee = WeeklyCommittee(mem)
    healthy = perf(list(np.full(40, 0.002)), expected_sharpe=2.0)
    broken = StrategyPerformance(
        strategy_id="s2", contract=CONTRACT, expected_sharpe=2.0,
        daily_returns=[0.01] * 70 + [-0.005] * 50,
    )
    proposals = committee.review([healthy, broken], detector=DriftDetector())
    by_id = {p.strategy_id: p for p in proposals}
    assert by_id["s1"].action == "MANTENER" and not by_id["s1"].needs_ceo
    assert by_id["s2"].action == "RETIRAR" and not by_id["s2"].needs_ceo  # automático por contrato


def test_postmortem_extracts_lesson_about_overestimation():
    lessons = postmortem_lessons({"type": "momentum"}, realized_sharpe=0.2, expected_sharpe=2.0, own_drawdown=0.12, days_alive=90)
    assert "sobreestimaba" in lessons[0]["content"]
    ok_lessons = postmortem_lessons({"type": "momentum"}, realized_sharpe=1.9, expected_sharpe=2.0, own_drawdown=0.10, days_alive=90)
    assert "coherente" in ok_lessons[0]["content"]
