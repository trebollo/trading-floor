"""Departamentos riesgo/ejecución/macro/dirección como workers del AgentHost."""

import numpy as np

from tf.audit import SqliteAuditLog
from tf.bus import InMemoryBus
from tf.contracts import Actor, Envelope
from tf.departments import ChiefOfStaffAgent, ExecutionRouterAgent, MacroAnalystAgent, RiskPreTradeAgent
from tf.execution import ExecutionRouter, Ledger, PaperBroker
from tf.host import AgentHost
from tf.paper import run_paper_session
from tf.permissions import PermissionBroker
from tf.risk import PortfolioState, PreTradeGate, RiskLimits, StrategyContract

SECRET = "test-departments"


def make_env(msg_type: str, payload: dict) -> Envelope:
    return Envelope(type=msg_type, payload=payload, actor=Actor(agent="t", role="r", department="d"))


def order_request(request_id: str, strategy_id: str = "s1", side: str = "BUY", size: float = 0.02, stop_loss: float | None = 98.0) -> dict:
    return {"request_id": request_id, "strategy_id": strategy_id, "instrument": "PAPER",
            "side": side, "size": size, "order_type": "MARKET", "stop_loss": stop_loss}


def wire_risk_and_execution(state, contract, host, bus, audit, orders_ctx):
    limits = RiskLimits(universe=["PAPER"])
    decisions: dict[str, dict] = {}
    regime = {"current": "normal"}
    fills: dict[str, dict | None] = {}
    risk = RiskPreTradeAgent(
        gate=PreTradeGate(limits, secret=SECRET), contracts={contract.strategy_id: contract},
        state=state, decisions=decisions, regime=regime, orders_ctx=orders_ctx,
        name="risk-pretrade", role="pretrade", bus=bus, broker=broker_for(audit), audit=audit,
    )
    exec_dept = ExecutionRouterAgent(
        router=ExecutionRouter(PaperBroker(), secret=SECRET, ledger=Ledger(), max_orders_per_minute=1000),
        orders_ctx=orders_ctx, fills=fills,
        name="execution-router", role="router", bus=bus, broker=broker_for(audit), audit=audit,
    )
    host.register("risk", workers={"risk-pretrade": risk.receive},
                  msg_types={"risk-pretrade": ["order.request.v1", "macro.regime.v1"]})
    host.register("execution", workers={"execution-router": exec_dept.receive},
                  msg_types={"execution-router": ["risk.decision.v1"]})
    return risk, exec_dept, decisions, fills


def broker_for(audit) -> PermissionBroker:
    from pathlib import Path

    return PermissionBroker.from_yaml(Path(__file__).parent.parent / "config" / "guardrails.yaml", audit=audit)


class TestRiskDepartment:
    def test_authorized_order_flows_to_execution(self):
        bus, audit, host = InMemoryBus(), SqliteAuditLog(), AgentHost(InMemoryBus(), SqliteAuditLog())
        # host sobre SU bus: rehacer con el mismo bus
        bus2 = InMemoryBus()
        host = AgentHost(bus2, audit)
        contract = StrategyContract(strategy_id="s1", max_size=0.05, universe=["PAPER"], require_stop=False)
        state = PortfolioState(equity=100_000.0, equity_start_of_day=100_000.0, equity_peak=100_000.0)
        orders_ctx = {"r1": {"request": order_request("r1", stop_loss=None), "price": 100.0, "ts": 1e9}}
        risk, exec_dept, decisions, fills = wire_risk_and_execution(state, contract, host, bus2, audit, orders_ctx)

        bus2.publish(make_env("order.request.v1", order_request("r1", stop_loss=None)))
        host.drain()

        assert decisions["r1"]["verdict"] in ("AUTORIZADA", "REDUCIR")
        assert fills["r1"] is not None and fills["r1"]["size"] > 0
        types = {e.type for e in bus2.published}
        assert {"order.request.v1", "risk.decision.v1", "fill.v1", "order.status.v1"} <= types

    def test_fail_closed_without_contract(self):
        bus2, audit = InMemoryBus(), SqliteAuditLog()
        host = AgentHost(bus2, audit)
        contract = StrategyContract(strategy_id="s1", max_size=0.05, universe=["PAPER"], require_stop=False)
        state = PortfolioState(equity=100_000.0, equity_start_of_day=100_000.0, equity_peak=100_000.0)
        orders_ctx = {"r1": {"request": order_request("r1", strategy_id="DESCONOCIDA", stop_loss=None), "price": 100.0, "ts": 1e9}}
        risk, exec_dept, decisions, fills = wire_risk_and_execution(state, contract, host, bus2, audit, orders_ctx)

        bus2.publish(make_env("order.request.v1", order_request("r1", strategy_id="DESCONOCIDA", stop_loss=None)))
        host.drain()

        assert decisions["r1"]["verdict"] == "RECHAZADA"
        assert decisions["r1"]["technical"] is True  # fail-closed
        assert fills["r1"] is None  # nada llegó al broker

    def test_macro_regime_updates_risk_view(self):
        bus2, audit = InMemoryBus(), SqliteAuditLog()
        host = AgentHost(bus2, audit)
        contract = StrategyContract(strategy_id="s1", max_size=0.05, universe=["PAPER"], require_stop=False, only_normal_regime=True)
        state = PortfolioState(equity=100_000.0, equity_start_of_day=100_000.0, equity_peak=100_000.0)
        orders_ctx = {"r1": {"request": order_request("r1", stop_loss=None), "price": 100.0, "ts": 1e9}}
        risk, exec_dept, decisions, fills = wire_risk_and_execution(state, contract, host, bus2, audit, orders_ctx)

        # El macro publica régimen adverso ANTES de la orden: el riesgo lo ve.
        bus2.publish(make_env("macro.regime.v1", {"regime": "adverso", "confidence": 0.6, "horizon": "days", "rationale": "test"}))
        bus2.publish(make_env("order.request.v1", order_request("r1", stop_loss=None)))
        host.drain()

        # Contrato provisional: sin aperturas en régimen adverso ⇒ RECHAZADA.
        assert decisions["r1"]["verdict"] == "RECHAZADA"
        assert "adverso" in decisions["r1"]["reason"]


class TestMacroAndExecutive:
    def test_macro_emits_regime_and_chief_tallies(self):
        bus2, audit = InMemoryBus(), SqliteAuditLog()
        host = AgentHost(bus2, audit)
        broker = broker_for(audit)
        macro = MacroAnalystAgent(name="macro-analyst", role="analyst", bus=bus2, broker=broker, audit=audit)
        chief = ChiefOfStaffAgent(tally={}, name="chief-of-staff", role="chief_of_staff", bus=bus2, broker=broker, audit=audit)
        host.register("macro", workers={"macro-analyst": macro.receive}, msg_types={"macro-analyst": []})
        host.register("executive", workers={"chief-of-staff": chief.receive},
                      msg_types={"chief-of-staff": list(ChiefOfStaffAgent.subscriptions)})

        close = np.concatenate([np.full(200, 100.0), [90.0]])  # precio bajo su SMA200
        env = macro.emit_regime(close)  # fuente pull del scheduler
        host.drain()  # el chief consume el régimen por el bus

        assert env is not None and env.payload["regime"] == "adverso"
        assert chief.tally.get("macro.regime.v1") == 1

        report = chief.daily_report("2026-10-05", budget={"eur": 0.0})
        assert report.payload["counts"]["macro.regime.v1"] == 1
        assert report.payload["cycle_date"] == "2026-10-05"

    def test_macro_without_history_stays_silent(self):
        bus2, audit = InMemoryBus(), SqliteAuditLog()
        macro = MacroAnalystAgent(name="macro-analyst", role="analyst", bus=bus2, broker=broker_for(audit), audit=audit)
        assert macro.emit_regime(np.full(50, 100.0)) is None  # sin SMA suficiente no opina


class TestPaperSessionBusDriven:
    def test_full_session_routes_orders_through_departments(self, tmp_path):
        """La sesión completa de papel sigue funcionando con las órdenes pasando
        por riesgo y ejecución en el bus (comportamiento equivalente al inline)."""
        from tf.marketdata import synthetic_market

        data = synthetic_market(n=800, seed=7)
        entry = {"spec": {"type": "momentum", "params": {"lookback": 20, "threshold": 0.03}}, "final": "VALIDADA"}
        session = run_paper_session(
            entry, data.close, data.open, data.ts.astype(float), 300,
            permissions=broker_for(SqliteAuditLog()), audit=SqliteAuditLog(),
        )
        assert session["n_orders"] > 0
        assert session["reconcile"] == []  # broker y ledger de acuerdo
        assert 0 < session["equity_final"]
