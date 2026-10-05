"""Departamento de news (Fase 7): dedup, clasificación y filtro Jev (M-x)."""

from tf.audit import SqliteAuditLog
from tf.bus import InMemoryBus
from tf.contracts import MessageValidationError
from tf.news import NewsAnalystAgent, classify, dedup
from tf.permissions import PermissionBroker, PermissionDenied

from pathlib import Path

import pytest


def make_agent(items_by_source: dict[str, list[dict]], jev=None) -> NewsAnalystAgent:
    """Agente con las fuentes parcheadas (sin red)."""
    agent = NewsAnalystAgent(
        feed_config={"lookback_hours": 24, "max_alerts_per_source": 10, "rss": []},
        jev=jev, name="news-analyst", role="news", bus=InMemoryBus(),
        broker=PermissionBroker.from_yaml(
            Path(__file__).parent.parent / "config" / "guardrails.yaml", audit=SqliteAuditLog()
        ),
        audit=SqliteAuditLog(), now=1_800_000_000,
    )
    agent._fetch_all = lambda: [item for items in items_by_source.values() for item in items]
    return agent


def item(title: str, url: str, source: str, summary: str = "") -> dict:
    return {"title": title, "url": url, "source": source, "summary": summary, "published_ts": 1_799_996_400}


class TestDedup:
    def test_dedup_by_url(self):
        items = [item("A", "https://x/1", "a.com"), item("A otra", "https://x/1/", "b.com")]
        unique, dropped = dedup(items)
        assert len(unique) == 1 and dropped == 1

    def test_cross_source_count(self):
        # M-2: mismo titular en dos fuentes ⇒ corroborado.
        items = [
            item("Fed sube tipos", "https://a/1", "a.com"),
            item("Fed sube tipos!", "https://b/1", "b.com"),
        ]
        unique, _ = dedup(items)
        assert all(i["cross_sources"] == 2 for i in unique)
        _cat, conf = classify(unique[0])
        assert conf > 0.5  # corroborada ⇒ más confianza


class TestClassify:
    def test_tail_risk_keyword(self):
        cat, conf = classify(item("War escalates in key region", "https://a/1", "a.com"))
        assert cat == "TAIL_RISK" and conf > 0.5

    def test_plain_relevant(self):
        assert classify(item("Stocks rally on earnings", "https://a/1", "a.com"))[0] == "relevant"


class TestJevFilter:
    def test_jev_blocks_irrelevant(self):
        class LowJev:
            def evaluate(self, state, questions):
                return {"market_relevant": {"noul": 0.1}}

        agent = make_agent({"a": [item("Nada que ver", "https://a/1", "a.com")]}, jev=LowJev())
        alerts = agent.ingest()
        assert alerts == []
        assert any(e.event_type == "news.alert_skipped" for e in agent.audit.entries())

    def test_jev_passes_relevant(self):
        class HighJev:
            def evaluate(self, state, questions):
                return {"market_relevant": {"noul": 0.9}}

        agent = make_agent({"a": [item("War escalates", "https://a/1", "a.com")]}, jev=HighJev())
        alerts = agent.ingest()
        assert len(alerts) == 1 and alerts[0].payload["category"] == "TAIL_RISK"

    def test_no_jev_degrades_with_penalty_and_audit(self):
        agent = make_agent({"a": [item("Stocks rally", "https://a/1", "a.com")]}, jev=None)
        alerts = agent.ingest()
        assert len(alerts) == 1
        assert alerts[0].payload["confidence"] <= 0.5  # 0.5 * 0.7 penalizado
        assert any(e.event_type == "model.failover" for e in agent.audit.entries())


class TestGuardrails:
    def test_news_agent_cannot_publish_orders(self):
        """M-1/G1: news-analyst no publica órdenes, veredictos ni directrices."""
        agent = make_agent({})
        for msg_type in ("order.request.v1", "validation.verdict.v1", "directive.new.v1", "risk.decision.v1"):
            with pytest.raises(PermissionDenied):
                agent.publish(msg_type, {"alert_id": "x"})

    def test_alert_payload_validates(self):
        agent = make_agent({})
        env = agent.publish(
            "news.alert.v1",
            {"alert_id": "a1", "category": "relevant", "confidence": 0.7,
             "single_source": True, "source": "a.com", "quotes": ["t"], "summary": "s"},
        )
        assert env.payload["alert_id"] == "a1"

    def test_invalid_alert_never_published(self):
        agent = make_agent({})
        with pytest.raises(MessageValidationError):
            agent.publish("news.alert.v1", {"alert_id": "a1", "category": "IMPOSIBLE"})


class TestSchedulerNewsPhase:
    def test_daily_cycle_ingests_news(self, tmp_path, monkeypatch):
        """El ciclo diario integra la fase de news con la red simulada."""
        import tf.news as news_mod
        from tf.scheduler import CycleConfig, DailyCycle

        def fake_gdelt(**kwargs):
            return {"articles": [
                {"url": "https://x.com/1", "title": "War escalates in key region", "seendate": "", "domain": "x.com"},
                {"url": "https://x.com/1", "title": "duplicado", "seendate": "", "domain": "y.com"},
            ]}

        monkeypatch.setattr(news_mod, "fetch_gdelt", fake_gdelt)
        from test_scheduler import make_config, write_csv

        write_csv(tmp_path)
        cycle = DailyCycle(
            InMemoryBus(), SqliteAuditLog(), config=make_config(tmp_path),
            news_config={"gdelt": {"query": "q", "maxrecords": 10}, "lookback_hours": 24},
            now=1_000_000.0,
        )
        report = cycle.run()
        news_phase = report["phases"]["news"]
        assert news_phase["alerts"] == 1  # dedup por URL: 2 artículos → 1 alerta
        assert news_phase["categories"] == ["TAIL_RISK"]
        assert any(e.event_type == "model.failover" for e in cycle.audit.entries())  # M-3 sin Jev
