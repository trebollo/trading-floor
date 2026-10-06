from __future__ import annotations

import json

from tf.audit import SqliteAuditLog
from tf.bus import InMemoryBus
from tf.contracts import Actor, Envelope
from tf.datasets import prepare_market_snapshot
from tf.department_runtime import backtest_factory, research_factory, validation_factory
from tf.marketdata import synthetic_market


class _StateStore:
    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return json.loads(json.dumps(self.values.get(key, default)))

    def mutate(self, key, update, default=None):
        value = self.get(key, default)
        changed = update(value)
        self.values[key] = changed if changed is not None else value
        return self.get(key)


def _csv(path, n=350):
    data = synthetic_market(n=n, seed=23)
    rows = ["ts,open,high,low,close"]
    rows.extend(
        f"{int(data.ts[i])},{data.open[i]},{data.high[i]},{data.low[i]},{data.close[i]}"
        for i in range(n)
    )
    path.write_text("\n".join(rows))


def test_pipeline_factories_exchange_self_contained_messages(tmp_path, monkeypatch):
    bus = InMemoryBus()
    audit = SqliteAuditLog()
    state = _StateStore()
    source = tmp_path / "market.csv"
    dataset_dir = tmp_path / "datasets"
    _csv(source)
    snapshot, digest = prepare_market_snapshot(source, dataset_dir)
    monkeypatch.setenv("TF_DATASET_DIR", str(dataset_dir))

    research, research_subs = research_factory(bus, audit, "research", state)
    trigger = Envelope(
        type="cycle.trigger.v1",
        payload={
            "cycle_id": "cycle-test-1",
            "cycle_date": "2026-10-06",
            "market_data_uri": str(snapshot),
            "market_data_sha256": digest,
            "proposal_count": 1,
        },
        actor=Actor(agent="scheduler", role="scheduler", department="executive"),
        correlation_id="cycle-test-1",
    )
    research["research-cycle"](trigger)
    proposal = next(env for env in bus.published if env.type == "strategy.proposal.v1")
    batch = next(env for env in bus.published if env.type == "cycle.research_batch.v1")
    assert batch.payload["cycle_id"] == "cycle-test-1"
    assert batch.payload["proposal_ids"] == [proposal.payload["proposal_id"]]
    assert proposal.payload["cycle_id"] == "cycle-test-1"
    assert proposal.payload["market_data_sha256"] == digest
    assert research_subs["research-coder"] == ["strategy.proposal.v1"]

    research["research-coder"](proposal)
    strategy = next(env for env in bus.published if env.type == "strategy.spec.v1")
    assert strategy.payload["market_data_uri"] == str(snapshot)
    assert strategy.correlation_id == "cycle-test-1"

    backtest, _ = backtest_factory(bus, audit, "backtest", state)
    invalid_spec = strategy.model_copy(update={"payload": {
        **strategy.payload,
        "spec": {"type": "unknown_strategy", "params": {}},
    }})
    backtest["backtest-engineer"](invalid_spec)
    report = next(env for env in reversed(bus.published) if env.type == "backtest.report.v1")
    assert report.payload["market_data_sha256"] == digest
    assert report.payload["spec"]["type"] == "unknown_strategy"

    validation, _ = validation_factory(bus, audit, "validation", state)
    validation["validation-quant"](report)
    verdict = next(env for env in reversed(bus.published) if env.type == "validation.verdict.v1")
    assert verdict.payload["cycle_id"] == "cycle-test-1"
    assert verdict.payload["proposal_id"] == proposal.payload["proposal_id"]
    assert verdict.payload["verdict"] == "RECHAZADA"


def test_macro_news_factory_completes_trigger_without_network(tmp_path, monkeypatch):
    import tf.department_runtime as runtime

    bus = InMemoryBus()
    audit = SqliteAuditLog()
    state = _StateStore()
    dataset = synthetic_market(n=240, seed=7)
    monkeypatch.setattr(runtime, "load_market_snapshot", lambda *_: dataset)

    class FakeNews:
        def ingest(self, **kwargs):
            assert kwargs["cycle_id"] == "cycle-news-1"
            return []

    monkeypatch.setattr(runtime, "build_news_agent", lambda *args, **kwargs: FakeNews())
    workers, _ = runtime.macro_news_factory(bus, audit, "macro", state)
    trigger = Envelope(
        type="cycle.trigger.v1",
        payload={
            "cycle_id": "cycle-news-1",
            "cycle_date": "2026-10-06",
            "market_data_uri": "/datasets/hash.csv",
            "market_data_sha256": "hash",
            "proposal_count": 1,
        },
        actor=Actor(agent="scheduler", role="scheduler", department="executive"),
    )

    workers["macro-cycle"](trigger)

    completed = next(env for env in bus.published if env.type == "cycle.macro_news_completed.v1")
    regime = next(env for env in bus.published if env.type == "macro.regime.v1")
    assert completed.payload["cycle_id"] == "cycle-news-1"
    assert completed.payload["regime_published"] is True
    assert regime.payload["cycle_id"] == "cycle-news-1"


def test_macro_news_network_failure_is_audited_and_reported(monkeypatch):
    import tf.department_runtime as runtime

    bus = InMemoryBus()
    audit = SqliteAuditLog()
    state = _StateStore()
    monkeypatch.setattr(runtime, "load_market_snapshot", lambda *_: synthetic_market(n=240, seed=7))

    class FailingNews:
        def ingest(self, **kwargs):
            raise RuntimeError("source unavailable")

    monkeypatch.setattr(runtime, "build_news_agent", lambda *args, **kwargs: FailingNews())
    workers, _ = runtime.macro_news_factory(bus, audit, "macro", state)
    trigger = Envelope(
        type="cycle.trigger.v1",
        payload={
            "cycle_id": "cycle-news-failure",
            "cycle_date": "2026-10-06",
            "market_data_uri": "/datasets/hash.csv",
            "market_data_sha256": "hash",
            "proposal_count": 1,
        },
        actor=Actor(agent="scheduler", role="scheduler", department="executive"),
    )

    workers["macro-cycle"](trigger)

    incident = next(env for env in bus.published if env.type == "ops.incident.v1")
    completed = next(env for env in bus.published if env.type == "cycle.macro_news_completed.v1")
    assert incident.payload["source"] == "macro/news"
    assert completed.payload["incident_count"] == 1
