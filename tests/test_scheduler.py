"""Tests del planificador: ciclo diario offline, memoria persistente y comité."""

import json

import numpy as np

from tf.audit import SqliteAuditLog
from tf.bus import InMemoryBus
from tf.gateway import GatewayConfig, ModelGateway
from tf.memory import MemoryStore
from tf.scheduler import CycleConfig, DailyCycle


def make_config(tmp_path, primary="SYNTH", start=None):
    return CycleConfig(
        data_dir=tmp_path / "data",
        memory_path=tmp_path / "state" / "memory.json",
        state_path=tmp_path / "state" / "cycle_state.json",
        primary=primary,
        start=start,
        bars=300,
    )


def write_csv(tmp_path, symbol="SYNTH", n=1500):
    """CSV de serie sintética determinista, formato de datafeed."""
    from tf.marketdata import synthetic_market

    data = synthetic_market(n=n, seed=7)
    lines = ["ts,open,high,low,close"]
    for i in range(n):
        lines.append(f"{i},{data.open[i]},{data.high[i]},{data.low[i]},{data.close[i]}")
    path = tmp_path / "data"
    path.mkdir(exist_ok=True)
    (path / f"{symbol.lower()}.csv").write_text("\n".join(lines))
    return path / f"{symbol.lower()}.csv"


def test_memory_save_load_roundtrip(tmp_path):
    store = MemoryStore()
    rec = store.add_evaluation("s1", "backtest", "RECHAZAR", "pierde", spec={"type": "momentum", "params": {"lookback": 20}})
    store.add_lesson("momentum pierde en régimen adverso", tags=["momentum"], source_evaluation_id=rec.id, family_key="momentum|SYNTH")
    path = tmp_path / "memory.json"

    store.save(path)
    loaded = MemoryStore.load(path)

    assert len(loaded.lessons) == 1 and len(loaded.evaluations) == 1
    assert loaded.lessons[0].id == store.lessons[0].id
    assert loaded.lessons[0].embedding == store.lessons[0].embedding  # embedding intacto
    assert loaded.is_spec_dead({"type": "momentum", "params": {"lookback": 20}})  # R-4 sobrevive


def test_daily_cycle_end_to_end_offline(tmp_path):
    write_csv(tmp_path)
    audit = SqliteAuditLog()
    cycle = DailyCycle(InMemoryBus(), audit, config=make_config(tmp_path), news_config={}, now=1_000_000.0)

    report = cycle.run(force_weekly=True)

    # Fases: sin red, la ingesta cae como incidente pero el ciclo sigue.
    assert report["phases"]["ingesta"]["ingested"] is None
    assert report["phases"]["research"]["evaluadas"] > 0
    assert report["phases"]["comite_programado"] is True
    assert report["audit_verificado"] is True
    # El comité revisó lo que hubo en papel (o no hubo sesión válida aún).
    assert isinstance(report["phases"].get("comite"), list)

    events = [e["event_type"] for e in audit.entries()]
    assert "ops.incident" in events
    assert "pipeline.spec_evaluated" in events

    # Estado persistido.
    state = json.loads((tmp_path / "state" / "cycle_state.json").read_text())
    assert state["last_run"] == 1_000_000.0
    assert state["last_committee"] == 1_000_000.0


def test_daily_cycle_persists_collective_memory(tmp_path):
    write_csv(tmp_path)
    config = make_config(tmp_path)
    cycle = DailyCycle(InMemoryBus(), SqliteAuditLog(), config=config, news_config={}, now=1_000_000.0)
    cycle.run()

    assert (config.memory_path).exists()
    persisted = MemoryStore.load(config.memory_path)
    # El pipeline del ciclo registró evaluaciones en la memoria persistida.
    assert len(persisted.evaluations) > 0

    # Segundo ciclo: parte de la memoria cargada (no se pierde ni se duplica el aprendido).
    cycle2 = DailyCycle(InMemoryBus(), SqliteAuditLog(), config=config, news_config={}, now=2_000_000.0)
    assert len(cycle2.memory.evaluations) == len(persisted.evaluations)
    cycle2.run()
    assert len(cycle2.memory.evaluations) >= len(persisted.evaluations)


def test_committee_not_due_within_week(tmp_path):
    write_csv(tmp_path)
    config = make_config(tmp_path)
    cycle = DailyCycle(InMemoryBus(), SqliteAuditLog(), config=config, news_config={}, now=1_000_000.0)
    report = cycle.run()  # primer ciclo: comité programado por defecto
    assert report["phases"]["comite_programado"] is True

    # Segundo ciclo un día después: no toca comité.
    cycle2 = DailyCycle(InMemoryBus(), SqliteAuditLog(), config=config, news_config={}, now=1_000_000.0 + 86_400)
    report2 = cycle2.run()
    assert report2["phases"]["comite_programado"] is False


def test_research_phase_failure_is_incident_not_crash(tmp_path):
    # Sin CSV y sin red: research debe caer como incidente y el ciclo terminar.
    config = make_config(tmp_path)  # data/ vacío
    audit = SqliteAuditLog()
    cycle = DailyCycle(InMemoryBus(), audit, config=config, news_config={}, now=1_000_000.0)

    report = cycle.run()

    assert "error" in report["phases"]["research"]
    assert report["audit_verificado"] is True
    events = [e["event_type"] for e in audit.entries()]
    assert "ops.incident" in events


def test_gateway_without_credentials_is_accepted():
    # El ciclo arranca con gateway declarado aunque no haya keys: degrada a plantilla.
    config = GatewayConfig.model_validate(
        {
            "models": {"jev": {"kind": "evaluator", "id": "jev-1.13-free", "provider": "opencode-go", "api_key_env": "OPENCODE_API_KEY"}},
            "agents": {"research-hypothesis": {"decisions": "jev"}},
        }
    )
    gw = ModelGateway(config)
    assert gw.client_for("research-hypothesis", "evaluator", env={}) is None
