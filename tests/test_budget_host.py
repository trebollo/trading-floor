"""G3/G7/K-5: presupuesto (CostGovernor), host multiagente anti-bucle y directivas."""

import pytest

from tf.audit import SqliteAuditLog
from tf.budget import BudgetExceeded, BudgetLimits, CostGovernor
from tf.bus import InMemoryBus
from tf.contracts import Actor, Envelope
from tf.directives import Directive, DirectivesBoard
from tf.gateway import GatewayConfig, ModelGateway
from tf.host import AgentHost
from tf.scheduler import CycleConfig, DailyCycle
from tf.validation import ValidationPolicy


def make_env(msg_type: str, env_id: str | None = None) -> Envelope:
    kw = {"id": env_id} if env_id else {}
    return Envelope(type=msg_type, payload={"agent": "a", "department": "d", "status": "up"}, actor=Actor(agent="a", role="r", department="d"), **kw)


# ---------------------------------------------------------------------------
# CostGovernor: corte, persistencia y reset diario
# ---------------------------------------------------------------------------


class TestCostGovernor:
    def test_blocks_after_token_budget_exhausted(self, tmp_path):
        audit = SqliteAuditLog(path=tmp_path / "audit.db")
        limits = BudgetLimits(default_tokens_per_day=100, calls_per_hour=1000, global_eur_per_day=1e9)
        gov = CostGovernor(limits, state_path=tmp_path / "b.json", audit=audit, now=1_800_000_000)
        gov.check("agent-x")  # dentro del límite
        gov.record("agent-x", input_tokens=80, output_tokens=20)
        with pytest.raises(BudgetExceeded):
            gov.check("agent-x")
        # el bloqueo quedó auditado
        assert any(e.event_type == "budget.exceeded" for e in audit.entries())

    def test_resets_next_day_and_persists_across_instances(self, tmp_path):
        limits = BudgetLimits(default_tokens_per_day=100, calls_per_hour=1000, global_eur_per_day=1e9)
        state = tmp_path / "b.json"
        gov1 = CostGovernor(limits, state_path=state, now=1_800_000_000)  # día T
        gov1.record("agent-x", 100, 0)
        gov2 = CostGovernor(limits, state_path=state, now=1_800_000_000)
        with pytest.raises(BudgetExceeded):
            gov2.check("agent-x")  # el estado persiste: reiniciar no resetea
        gov3 = CostGovernor(limits, state_path=state, now=1_800_000_000 + 86_400)  # día T+1
        gov3.check("agent-x")  # nueva ventana: sin excepción

    def test_per_call_rate_limit(self, tmp_path):
        limits = BudgetLimits(default_tokens_per_day=1e9, calls_per_hour=2, global_eur_per_day=1e9)
        gov = CostGovernor(limits, state_path=tmp_path / "b.json", now=1_800_000_000)
        gov.record("a", 1, 1)
        gov.record("a", 1, 1)
        with pytest.raises(BudgetExceeded):
            gov.check("a")

    def test_global_daily_eur_cap_blocks_everyone(self, tmp_path):
        limits = BudgetLimits(default_tokens_per_day=1e9, calls_per_hour=1e9, global_eur_per_day=1.0)
        gov = CostGovernor(limits, state_path=tmp_path / "b.json", now=1_800_000_000)
        gov.record("a", 0, 0, cost_usd=1.0)
        with pytest.raises(BudgetExceeded):
            gov.check("a")
        with pytest.raises(BudgetExceeded):
            gov.check("b")  # el techo global bloquea a todos los agentes

    def test_per_agent_override_from_limits(self, tmp_path):
        limits = BudgetLimits(
            default_tokens_per_day=1e9, calls_per_hour=1e9, global_eur_per_day=1e9,
            per_agent={"research-hypothesis": {"tokens_per_day": 50}},
        )
        gov = CostGovernor(limits, state_path=tmp_path / "b.json", now=1_800_000_000)
        gov.record("research-hypothesis", 60, 0)
        with pytest.raises(BudgetExceeded):
            gov.check("research-hypothesis")
        gov.check("other-agent")  # el default no se ve afectado


# ---------------------------------------------------------------------------
# Gateway + governor: registro de uso y corte antes de gastar
# ---------------------------------------------------------------------------


class TestGatewayBudget:
    def _gateway(self) -> ModelGateway:
        return ModelGateway(GatewayConfig.model_validate({
            "models": {
                "writer": {
                    "kind": "generative", "id": "glm-5.3-flash", "provider": "opencode-go",
                    "protocol": "chat-completions", "endpoint": "https://x/v1",
                    "api_key_env": "K", "input_cost_per_mtok": 1.0, "output_cost_per_mtok": 3.0,
                },
            },
            "agents": {"ag": {"generative": "writer"}},
        }))

    def test_usage_recorded_after_complete(self, tmp_path, monkeypatch):
        import tf.gateway as gw_mod

        captured = {}

        def fake_post(url, api_key, payload, timeout, headers=None):
            captured["payload"] = payload
            return {"choices": [{"message": {"content": "ok"}}], "usage": {"prompt_tokens": 1000, "completion_tokens": 500}}

        monkeypatch.setattr(gw_mod, "_post_json", fake_post)
        gov = CostGovernor(BudgetLimits(), state_path=tmp_path / "b.json", now=1_800_000_000)
        client = self._gateway().client_for("ag", "generative", env={"K": "k"}, governor=gov)
        client.complete("sys", "user")
        usage = gov.usage()
        assert usage["agents"]["ag"]["tokens"] == 1500
        # coste: 1000/1e6*1.0 + 500/1e6*3.0 = 0.0025
        assert abs(usage["agents"]["ag"]["eur"] - 0.0025) < 1e-9

    def test_budget_cut_prevents_call(self, tmp_path, monkeypatch):
        import tf.gateway as gw_mod

        calls = []
        monkeypatch.setattr(gw_mod, "_post_json", lambda *a, **k: calls.append(a) or {})
        gov = CostGovernor(
            BudgetLimits(default_tokens_per_day=10, calls_per_hour=1000, global_eur_per_day=1e9),
            state_path=tmp_path / "b.json", now=1_800_000_000,
        )
        gov.record("ag", 100, 0)  # ya por encima del límite
        client = self._gateway().client_for("ag", "generative", env={"K": "k"}, governor=gov)
        with pytest.raises(BudgetExceeded):
            client.complete("sys", "user")
        assert not calls  # la llamada HTTP nunca salió


# ---------------------------------------------------------------------------
# AgentHost: dedup, overflow y drenaje acotado
# ---------------------------------------------------------------------------


class TestAgentHost:
    def test_workers_receive_and_reply_via_bus(self):
        bus = InMemoryBus()
        audit = SqliteAuditLog()
        host = AgentHost(bus, audit)

        def worker(env):
            if env.payload.get("react"):
                return [make_env("agent.heartbeat.v1")]
            return None

        host.register("dept", workers={"w": worker}, msg_types={"w": ["agent.heartbeat.v1"]})
        bus.publish(make_env("agent.heartbeat.v1"))
        stats = host.drain()
        assert stats["steps"] == 1 and stats["pending"] == 0

    def test_requeued_same_id_is_blocked_and_audited(self):
        bus = InMemoryBus()
        audit = SqliteAuditLog()
        host = AgentHost(bus, audit)

        def loop_worker(env):  # un worker que responde con el MISMO id: bucle
            return [env]

        host.register("dept", workers={"w": loop_worker}, msg_types={"w": ["agent.heartbeat.v1"]})
        bus.publish(make_env("agent.heartbeat.v1"))
        stats = host.drain()
        assert stats["dropped_dedup"] == 1
        assert any(e.event_type == "agent.loop_blocked" for e in audit.entries())

    def test_drain_is_bounded_by_max_steps(self):
        bus = InMemoryBus()
        audit = SqliteAuditLog()
        host = AgentHost(bus, audit, max_steps=10)

        def ping_pong(env):  # responde siempre con ids nuevos: no termina solo
            return [make_env("agent.heartbeat.v1")]

        host.register("d1", workers={"w1": ping_pong}, msg_types={"w1": ["agent.heartbeat.v1"]})
        host.register("d2", workers={"w2": ping_pong}, msg_types={"w2": ["agent.heartbeat.v1"]})
        bus.publish(make_env("agent.heartbeat.v1"))
        stats = host.drain()
        assert stats["steps"] == 10  # techo: el ciclo se corta, no crece sin límite

    def test_worker_exception_does_not_kill_host(self):
        bus = InMemoryBus()
        audit = SqliteAuditLog()
        host = AgentHost(bus, audit)

        def bad(env):
            raise RuntimeError("fallo del worker")

        host.register("dept", workers={"w": bad}, msg_types={"w": ["agent.heartbeat.v1"]})
        bus.publish(make_env("agent.heartbeat.v1"))
        stats = host.drain()
        assert stats["steps"] == 1
        assert any(e.event_type == "agent.error" for e in audit.entries())

    def test_queue_overflow_is_dropped_and_audited(self):
        bus = InMemoryBus()
        audit = SqliteAuditLog()
        host = AgentHost(bus, audit, max_queue=2)

        def slow(env):
            return None

        host.register("dept", workers={"w": slow}, msg_types={"w": ["agent.heartbeat.v1"]})
        for _ in range(5):
            bus.publish(make_env("agent.heartbeat.v1"))
        stats = host.drain()
        assert stats["dropped_overflow"] == 3
        assert any(e.event_type == "host.queue_overflow" for e in audit.entries())


# ---------------------------------------------------------------------------
# Directivas del CEO (K-5)
# ---------------------------------------------------------------------------


class TestDirectives:
    def test_current_picks_latest(self):
        board = DirectivesBoard([
            Directive(id="D-1", date="2026-01-01", summary="antigua", overrides={"min_trades": 50}),
            Directive(id="D-2", date="2026-02-01", summary="vigente", overrides={"min_trades": 10}),
        ])
        assert board.current().id == "D-2"

    def test_apply_overrides_policy(self):
        board = DirectivesBoard([Directive(id="D-1", date="2026-01-01", summary="x", overrides={"min_trades": 30})])
        policy = board.apply_to_policy(ValidationPolicy(min_trades=100))
        assert policy.min_trades == 30
        assert policy.mc_iterations == 10_000  # lo que no toca la directiva, queda

    def test_unknown_keys_ignored(self):
        board = DirectivesBoard([Directive(id="D-1", date="2026-01-01", summary="x", overrides={"min_trades": 30, "campo_inexistente": 1})])
        policy = board.apply_to_policy(ValidationPolicy())
        assert policy.min_trades == 30
        assert not hasattr(policy, "campo_inexistente")

    def test_no_directives_returns_policy_untouched(self):
        board = DirectivesBoard([])
        policy = ValidationPolicy(min_trades=42)
        assert board.apply_to_policy(policy) is policy


# ---------------------------------------------------------------------------
# Ciclo con presupuesto agotado: degradación a plantilla con failover auditado
# ---------------------------------------------------------------------------


class TestCycleBudgetDegradation:
    def _exhausted_governor(self, tmp_path):
        gov = CostGovernor(
            BudgetLimits(default_tokens_per_day=0, calls_per_hour=0, global_eur_per_day=0.0),
            state_path=tmp_path / "b.json", now=1_800_000_000,
        )
        return gov

    def test_exhausted_budget_degrades_to_template(self, tmp_path, monkeypatch):
        import tf.research_llm as rl

        class _Boom:
            def complete(self, **kwargs):
                raise BudgetExceeded("agotado")

            session_id = "s"

        class _NoJev:
            def evaluate(self, *a, **k):
                raise BudgetExceeded("agotado")

            session_id = "s"

        monkeypatch.setattr(rl.ResearchLLMAgent, "from_gateway", classmethod(
            lambda cls, gateway, env=None, governor=None, **kw: rl.ResearchLLMAgent(
                gateway=gateway, generative=_Boom(), jev=_NoJev(), **kw)
        ))

        from tf.marketdata import synthetic_market
        from tf.pipeline import PipelineRunner
        from tf.permissions import PermissionBroker

        write_csv(tmp_path)
        bus, audit = InMemoryBus(), SqliteAuditLog()
        broker = PermissionBroker.from_yaml("config/guardrails.yaml", audit=audit)
        runner = PipelineRunner(
            bus, broker, audit, policy=ValidationPolicy(min_trades=5),
            gateway=ModelGateway.from_yaml("config/models.yaml"),
            governor=self._exhausted_governor(tmp_path),
        )
        config = CycleConfig(data_dir=tmp_path / "data", memory_path=tmp_path / "s" / "m.json", state_path=tmp_path / "s" / "c.json", bars=300)

        # research corre igual (plantilla), aunque el generativo esté bloqueado:
        data = synthetic_market(n=800, seed=7)
        catalog = runner.run(data)
        assert len(catalog) > 0
        # y el failover quedó auditado
        assert any("presupuesto" in str(e.payload.get("reason", "")) for e in audit.entries())


def write_csv(tmp_path, symbol="SYNTH", n=1500):
    from tf.marketdata import synthetic_market

    data = synthetic_market(n=n, seed=7)
    lines = ["ts,open,high,low,close"]
    for i in range(n):
        lines.append(f"{i},{data.open[i]},{data.high[i]},{data.low[i]},{data.close[i]}")
    path = tmp_path / "data"
    path.mkdir(exist_ok=True)
    (path / f"{symbol.lower()}.csv").write_text("\n".join(lines))
    return path / f"{symbol.lower()}.csv"
