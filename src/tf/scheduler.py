"""Planificador del sistema vivo: ciclo diario + comité semanal (Fase 5).

Orquesta las fases que hasta ahora eran demos sueltas, con la memoria colectiva
persistida y todo auditado:

  1. ingesta    — datos reales a `data/` (tf.datafeed); fallo ⇒ incidente, la fase
                  siguiente usa el último CSV válido.
  2. research   — pipeline Research → Backtest → Validation sobre la serie principal
                  (LLM reales si hay credenciales; plantilla si no, con failover auditado).
                  El pipeline ya registra evaluaciones y lecciones en memoria.
  3. paper day  — sesión de paper trading por estrategia validada (tf.paper).
  4. memoria    — MemoryStore.save: la memoria colectiva sobrevive reinicios.
  5. comité     — si ha pasado una semana: DriftDetector + WeeklyCommittee sobre el
                  portfolio en papel; toda RETIRADA genera postmortem (lecciones).

Regla de oro: una fase que falla no tumba el ciclo — se audita como incidente
(ops.incident) y el ciclo continúa con lo que tenga. Los guardarrieles deterministas
siguen siendo quienes autorizan cualquier cosa que afecte a capital.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tf.audit import AuditLog
from tf.bus import BaseBus
from tf.datafeed import fetch_yahoo, ingest_yahoo
from tf.directives import DirectivesBoard
from tf.drift import DriftVerdict, StrategyPerformance, WeeklyCommittee, postmortem_lessons
from tf.gateway import ModelGateway
from tf.host import AgentHost
from tf.marketdata import load_csv
from tf.memory import MemoryStore
from tf.paper import run_paper_session
from tf.pipeline import PipelineRunner
from tf.risk import StrategyContract
from tf.validation import ValidationPolicy

WEEK_SECONDS = 7 * 24 * 3600


@dataclass
class CycleConfig:
    data_dir: Path
    memory_path: Path
    state_path: Path
    primary: str = "AAPL"            # serie principal: la que alimenta research
    start: str | None = "20150101"   # ingesta: desde cuándo
    bars: int = 500                  # ventana de paper trading
    initial_equity: float = 100_000.0

    @classmethod
    def under(cls, root: str | Path, **kwargs: Any) -> "CycleConfig":
        root = Path(root)
        return cls(
            data_dir=root / "data",
            memory_path=root / "state" / "memory.json",
            state_path=root / "state" / "cycle_state.json",
            **kwargs,
        )


class DailyCycle:
    def __init__(
        self,
        bus: BaseBus,
        audit: AuditLog,
        gateway: ModelGateway | None = None,
        config: CycleConfig | None = None,
        policy: ValidationPolicy | None = None,
        governor: Any | None = None,      # G3: presupuesto compartido; None = sin corte
        directives: DirectivesBoard | None = None,  # K-5: directrices del CEO
        now: float | None = None,
    ) -> None:
        self.bus = bus
        self.audit = audit
        self.gateway = gateway
        self.config = config or CycleConfig.under(".")
        self.governor = governor
        self.directives = directives
        self.now = now if now is not None else time.time()
        if policy is None:
            policy = ValidationPolicy(min_trades=30)
            if directives is not None:  # la directiva vigente sobreescribe (K-5)
                policy = directives.apply_to_policy(policy)
        self.policy = policy
        self.memory = MemoryStore.load(self.config.memory_path) if self.config.memory_path.exists() else MemoryStore()

    # -- estado persistente del ciclo ------------------------------------------

    def _load_state(self) -> dict[str, Any]:
        if self.config.state_path.exists():
            return json.loads(self.config.state_path.read_text())
        return {"last_run": None, "last_committee": None, "portfolio": []}

    def _save_state(self, state: dict[str, Any]) -> None:
        self.config.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.state_path.write_text(json.dumps(state, indent=2))

    def _incident(self, phase: str, exc: Exception) -> None:
        self.audit.append(
            actor="scheduler", event_type="ops.incident",
            payload={"phase": phase, "error": f"{type(exc).__name__}: {exc}"},
        )

    def _permissions(self):
        from tf.permissions import PermissionBroker

        # Desde src/tf/scheduler.py a la raíz del repo (checkout de desarrollo).
        root = Path(__file__).resolve().parents[2]
        return PermissionBroker.from_yaml(root / "config" / "guardrails.yaml", audit=self.audit)

    # -- fases -------------------------------------------------------------------

    def _ingest(self) -> dict[str, Any]:
        """Descarga la serie principal. Sin red o sin API ⇒ incidente y se sigue."""
        try:
            raw = fetch_yahoo(self.config.primary, start=self.config.start)
            path = ingest_yahoo(self.config.primary, raw, out_dir=self.config.data_dir)
            return {"ingested": str(path), "bars": path.read_text().count("\n") - 1}
        except Exception as exc:
            self._incident("ingesta", exc)
            return {"ingested": None, "error": str(exc)}

    def _research(self) -> dict[str, Any]:
        csv_path = self.config.data_dir / f"{self.config.primary.lower()}.csv"
        if not csv_path.exists():
            raise FileNotFoundError(f"sin datos para research: {csv_path}")
        data = load_csv(csv_path)
        runner = PipelineRunner(
            self.bus, self._permissions(), self.audit,
            policy=self.policy, memory=self.memory, gateway=self.gateway,
            governor=self.governor,
        )
        catalog = runner.run(data)
        entries = [e.__dict__ | {"spec": e.spec} for e in catalog]
        validated = [e for e in entries if e["final"] in ("VALIDADA", "VALIDADA_PROVISIONAL")]
        return {"catalog": entries, "validated": validated}

    def _paper_day(self, validated: list[dict[str, Any]]) -> list[dict[str, Any]]:
        csv_path = self.config.data_dir / f"{self.config.primary.lower()}.csv"
        if not csv_path.exists():
            if validated:
                self._incident("paper_day", FileNotFoundError(f"sin datos para paper day: {csv_path}"))
            return []
        data = load_csv(csv_path)
        sessions = []
        for entry in validated:
            try:
                session = run_paper_session(
                    entry, data.close, data.open, data.ts.astype(float),
                    self.config.bars, initial_equity=self.config.initial_equity,
                )
                session["metrics"] = entry.get("metrics") or {}
                sessions.append(session)
            except Exception as exc:
                self._incident("paper_day", exc)
        return sessions

    def _committee_due(self, state: dict[str, Any]) -> bool:
        last = state.get("last_committee")
        return last is None or (self.now - last) >= WEEK_SECONDS

    def _committee(self, sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        performances = []
        for s in sessions:
            curve = s.get("equity_curve") or []
            if len(curve) < 2:
                continue
            returns = [(curve[i] - curve[i - 1]) / curve[i - 1] for i in range(1, len(curve)) if curve[i - 1] > 0]
            performances.append(
                StrategyPerformance(
                    strategy_id=s["strategy_id"],
                    contract=StrategyContract(strategy_id=s["strategy_id"], max_size=0.05),
                    expected_sharpe=float(s.get("metrics", {}).get("sharpe", 0.0)),
                    daily_returns=returns,
                    # equity_peak en escala relativa (el detector normaliza los retornos a 1.0).
                    equity_peak=1.0,
                )
            )
        out = []
        for p in WeeklyCommittee(self.memory).review(performances):
            out.append({"strategy_id": p.strategy_id, "action": p.action, "needs_ceo": p.needs_ceo, "reason": p.reason})
            if p.action == "RETIRAR":  # toda retirada genera lecciones (aprendizaje, no castigo)
                session = next((s for s in sessions if s["strategy_id"] == p.strategy_id), None)
                if not session:
                    continue
                curve = session.get("equity_curve") or []
                peak = max(curve) if curve else 0.0
                for lesson in postmortem_lessons(
                    session["spec"],
                    realized_sharpe=0.0,  # el comité puntúa la semana en papel; drift fino con más historia
                    expected_sharpe=float(session.get("metrics", {}).get("sharpe", 0.0)),
                    own_drawdown=1.0 - curve[-1] / peak if peak > 0 else 0.0,
                    days_alive=len(curve),
                ):
                    self.memory.add_lesson(content=lesson["content"], tags=lesson["tags"], family_key=lesson["family_key"])
        return out

    # -- ciclo completo ------------------------------------------------------------

    def run(self, force_weekly: bool = False) -> dict[str, Any]:
        started = time.time()
        state = self._load_state()
        report: dict[str, Any] = {
            "run_at": datetime.fromtimestamp(self.now, tz=timezone.utc).isoformat(),
            "phases": {},
        }

        # K-5: la directiva vigente del CEO se audita al inicio de cada ciclo.
        directive = self.directives.current() if self.directives else None
        self.audit.append(
            actor="scheduler", event_type="directive.applied",
            payload={"directive_id": directive.id, "summary": directive.summary} if directive
            else {"directive_id": None, "summary": "sin directrices cargadas"},
        )

        # G3/G7: host multiagente — los agentes del ciclo corren en departamentos
        # sobre el bus, con drenaje acotado (anti-bucle) y colas con techo.
        host = AgentHost(self.bus, self.audit)
        host.register(
            "research",
            workers={"research-hypothesis": lambda env: None},  # el pipeline publica en su nombre; el host transporta
            msg_types={"research-hypothesis": ["strategy.proposal.v1", "agent.heartbeat.v1"]},
        )
        host.register(
            "backtest",
            workers={"backtest-engineer": lambda env: None},
            msg_types={"backtest-engineer": ["backtest.report.v1", "agent.heartbeat.v1"]},
        )
        host.register(
            "validation",
            workers={"validation-quant": lambda env: None},
            msg_types={"validation-quant": ["validation.verdict.v1", "agent.heartbeat.v1"]},
        )

        report["phases"]["ingesta"] = self._ingest()

        try:
            research = self._research()
            report["phases"]["research"] = {
                "evaluadas": len(research["catalog"]),
                "validadas": len(research["validated"]),
                "finals": [e["final"] for e in research["catalog"]],
            }
        except Exception as exc:
            self._incident("research", exc)
            research = {"catalog": [], "validated": []}
            report["phases"]["research"] = {"error": str(exc)}

        # G7: drenaje acotado del host — los mensajes que el pipeline dejó en el
        # bus se procesan aquí, con techo de pasos; nada puede buclearse eternamente.
        report["phases"]["host"] = host.drain()

        sessions = self._paper_day(research["validated"])
        report["phases"]["paper_day"] = [
            {k: s[k] for k in ("strategy_id", "n_orders", "n_rejected", "retorno", "reconcile")}
            for s in sessions
        ]
        state["portfolio"] = [s["strategy_id"] for s in sessions]

        weekly = force_weekly or self._committee_due(state)
        report["phases"]["comite_programado"] = weekly
        if weekly and sessions:
            try:
                report["phases"]["comite"] = self._committee(sessions)
                state["last_committee"] = self.now
            except Exception as exc:
                self._incident("comite", exc)

        try:
            self.config.memory_path.parent.mkdir(parents=True, exist_ok=True)
            self.memory.save(self.config.memory_path)
        except Exception as exc:
            self._incident("memoria", exc)

        state["last_run"] = self.now
        self._save_state(state)

        if self.governor is not None:  # G3: consumo del presupuesto en el reporte
            report["presupuesto"] = self.governor.usage()

        report["audit_verificado"] = self.audit.verify() if hasattr(self.audit, "verify") else None
        report["duracion_s"] = round(time.time() - started, 2)
        return report
