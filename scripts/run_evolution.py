"""Demo Fase 3: el sistema aprende y evoluciona.

Ejecuta: uv run python scripts/run_evolution.py

Semana a semana: una estrategia validada opera, su rendimiento se degrada, el drift
detector la manda a revalidación, el contrato la retira, el post-mortem extrae lecciones
a la memoria colectiva, y la siguiente ronda de Research ya no propone ideas muertas.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import numpy as np

from tf.drift import DriftDetector, DriftVerdict, StrategyPerformance, WeeklyCommittee, postmortem_lessons
from tf.marketdata import synthetic_market
from tf.memory import MemoryStore
from tf.pipeline import PipelineRunner
from tf.risk import StrategyContract
from tf.validation import ValidationPolicy


def make_runner(bus, audit, broker, memory):
    return PipelineRunner(bus, broker, audit, policy=ValidationPolicy(min_trades=30), memory=memory)


def main() -> None:
    memory = MemoryStore()
    from tf.audit import SqliteAuditLog
    from tf.bus import InMemoryBus
    from tf.permissions import PermissionBroker

    audit = SqliteAuditLog()
    bus = InMemoryBus()
    broker = PermissionBroker.from_yaml(Path(__file__).parent.parent / "config" / "guardrails.yaml", audit=audit)

    # ── Semana 0: ronda de investigación con memoria vacía ──────────────────────
    data = synthetic_market(n=2500, drift=0.0012, vol=0.008, seed=42)
    catalog = make_runner(bus, audit, broker, memory).run(data)
    validadas = [e for e in catalog if e.final in ("VALIDADA", "VALIDADA_PROVISIONAL")]
    print("Semana 0 — ronda de investigación")
    for e in catalog:
        print(f"  {e.spec['type']} {e.spec['params']}: {e.final}")
    print(f"  → {len(validadas)} validada(s), {len(memory.lessons)} lección(es) en memoria\n")

    # ── Semanas 1-8: la estrategia viva opera y luego se degrada ────────────────
    spec_viva = validadas[0].spec if validadas else {"type": "momentum", "params": {"lookback": 60, "threshold": 0.02}}
    contract = StrategyContract(strategy_id="strat-momentum", max_size=0.02, universe=["SYNTH"], max_own_drawdown=0.10)
    rng = np.random.default_rng(7)
    detector = DriftDetector()
    committee = WeeklyCommittee(memory)
    expected_sharpe = validadas[0].metrics.get("sharpe", 2.0) if validadas else 2.0

    returns_history: list[float] = []
    strategy_id = f"{spec_viva['type']}-v1"
    retired = False
    for week in range(1, 9):
        if not retired:
            returns_history += list(0.002 + 0.005 * rng.standard_normal(5))          # semanas sanas
        else:
            returns_history += list(-0.0005 + 0.01 * rng.standard_normal(5))         # degradación post-retiro no aplica
        if week == 5:  # el régimen cambia: la estrategia empieza a perder
            returns_history += list(-0.006 + 0.012 * rng.standard_normal(10))

        perf = StrategyPerformance(
            strategy_id=strategy_id, contract=contract, expected_sharpe=expected_sharpe,
            daily_returns=list(returns_history), equity_peak=float(np.cumprod(1 + np.array(returns_history)).max()) if returns_history else 1.0,
        )
        report = detector.check(perf)
        proposals = committee.review([perf], detector)
        action = proposals[0]
        print(f"Semana {week}: Sharpe real {report.realized_sharpe:.2f}, DD propio {report.own_drawdown:.2%} → "
              f"{report.verdict.value} / comité: {action.action}{' (al CEO)' if action.needs_ceo else ''}")

        if report.verdict == DriftVerdict.RETIRAR and not retired:
            retired = True
            print(f"  → RETIRADA automática por contrato: {report.reason}")
            # Post-mortem → memoria colectiva
            lessons = postmortem_lessons(spec_viva, report.realized_sharpe, expected_sharpe, report.own_drawdown, days_alive=week * 5)
            for lesson in lessons:
                memory.add_lesson(content=lesson["content"], tags=lesson["tags"], family_key=lesson["family_key"])
            memory.add_evaluation(strategy_id, "postmortem", "RETIRADA", report.reason, spec=spec_viva)
            print(f"  → post-mortem archivado; lecciones en memoria: {len(memory.lessons)}")

    # ── Semana 9: nueva ronda de investigación, ya con memoria colectiva ────────
    print("\nSemana 9 — nueva ronda de investigación (con memoria)")
    catalog2 = make_runner(bus, audit, broker, memory).run(data)
    for e in catalog2:
        print(f"  {e.spec['type']} {e.spec['params']}: {e.final}")
    skipped = [e for e in audit.entries() if e["event_type"] == "research.proposal_skipped"]
    print(f"  → {len(skipped)} propuesta(s) saltadas por memoria (no repetir fracasos)")
    print(f"  → lecciones totales: {len(memory.lessons)}")

    out = Path(".amp/in/artifacts")
    out.mkdir(parents=True, exist_ok=True)
    (out / "fase3-memoria.json").write_text(json.dumps({
        "lessons": [{"content": l.content, "tags": l.tags, "refs": l.times_referenced} for l in memory.lessons],
        "evaluations": len(memory.evaluations),
    }, indent=2, ensure_ascii=False))
    print(f"\nMemoria exportada a {out / 'fase3-memoria.json'}")
    print(f"Audit log: {len(audit.entries())} entradas, cadena íntegra: {audit.verify()}")


if __name__ == "__main__":
    main()
