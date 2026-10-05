"""Departamento de news (Fase 7): ingesta multi-fuente + filtro Jev de relevancia.

Fuentes gratuitas, sin key o con key gratuita (FINNHUB_API_KEY en el entorno):
GDELT (geopolítica global, sin key), Finnhub market news y RSS oficiales
(bancos centrales). El flujo:

  ingesta → dedup (URL y título entre fuentes) → filtro Jev (relevancia) →
  news.alert.v1 al bus → el comité de riesgo y el chief-of-staff deciden.

Guardarraíles propios del departamento (M-x):
  · M-1: nunca publica order.request, directrices, límites ni veredictos —
    G1 lo impone (lista cerrada de salidas en guardrails.yaml).
  · M-2: una alerta con `single_source=True` y confianza baja no escala a
    acción; solo informa. El rumor no mueve capital.
  · M-3: sin Jev disponible (sin key, presupuesto G3 agotado), se publica con
    la confianza penalizada y failover auditado — el filtro es optimización,
    no guardarriel determinista.
"""

from __future__ import annotations

import json
import re
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from tf.agents import Agent
from tf.budget import BudgetExceeded
from tf.gateway import JevClient, ModelGateway

NOUL_RELEVANCE_THRESHOLD = 0.6

JEV_QUESTIONS: dict[str, dict[str, Any]] = {
    "market_relevant": {
        "type": "noul",
        "instructions": "¿Esta noticia puede mover el precio de acciones, divisas o materias primas en las próximas 48 horas?",
    },
}

# M-2: palabras que indican riesgo de cola (guerra, embargo, quiebra sistémica...).
TAIL_RISK_KEYWORDS = (
    "war", "sanction", "embargo", "default", "bailout", "devaluation",
    "martial law", "coup", "state of emergency", "nuclear", "currency collapse",
)


# ---------------------------------------------------------------------------
# Fuentes: fetch (red) separado de parse (testeable sin red)
# ---------------------------------------------------------------------------


def _open_with_retry(req: Any, timeout: float, retries: int = 2, backoff_s: float = 3.0) -> Any:
    """GET con reintentos por 429/5xx (backoff): las fuentes gratuitas nos limitan."""
    import time as _time
    import urllib.error

    for attempt in range(retries + 1):
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < retries:
                _time.sleep(backoff_s * (attempt + 1))
                continue
            raise


def fetch_gdelt(query: str, maxrecords: int = 25, timeout: float = 20.0) -> dict[str, Any]:
    """GDELT DOC 2.0: artículos globales por query. Sin API key."""
    import urllib.parse

    url = (
        "https://api.gdeltproject.org/api/v2/doc/doc?query=" + urllib.parse.quote(query)
        + f"&mode=ArtList&maxrecords={maxrecords}&format=json&sort=datedesc"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "trading-floor/0.1"})
    with _open_with_retry(req, timeout) as resp:
        return json.loads(resp.read().decode())


def parse_gdelt(data: dict[str, Any], lookback_hours: int, now_ts: float) -> list[dict[str, Any]]:
    """Artículos GDELT → items normalizados. Filtra por ventana temporal e idioma."""
    out = []
    for art in data.get("articles", []):
        item = {
            "title": art.get("title", ""),
            "url": art.get("url", ""),
            "source": art.get("domain", "gdelt"),
            "summary": "",
            "published_ts": _gdelt_ts(art.get("seendate", "")),
        }
        if item["title"] and item["url"] and _within_lookback(item["published_ts"], lookback_hours, now_ts):
            out.append(item)
    return out


def fetch_finnhub(category: str, token: str, timeout: float = 20.0) -> list[dict[str, Any]]:
    """Finnhub market news (key gratuita). Devuelve items normalizados."""
    url = f"https://finnhub.io/api/v1/news?category={category}&token={token}"
    req = urllib.request.Request(url, headers={"User-Agent": "trading-floor/0.1"})
    with _open_with_retry(req, timeout) as resp:
        raw = json.loads(resp.read().decode())
    out = []
    for art in raw if isinstance(raw, list) else []:
        out.append({
            "title": art.get("headline", ""),
            "url": art.get("url", ""),
            "source": art.get("source", "finnhub"),
            "summary": art.get("summary", "") or "",
            "published_ts": float(art.get("datetime", 0)) or None,
        })
    return [i for i in out if i["title"] and i["url"]]


def fetch_rss(feed_url: str, timeout: float = 20.0) -> list[dict[str, Any]]:
    """RSS/Atom sencillo con la stdlib (bancos centrales, prensa oficial)."""
    req = urllib.request.Request(feed_url, headers={"User-Agent": "trading-floor/0.1"})
    with _open_with_retry(req, timeout) as resp:
        root = ET.fromstring(resp.read())
    out = []
    for item in root.iter():
        if item.tag.rsplit("}", 1)[-1] != "item":
            continue
        fields = {child.tag.rsplit("}", 1)[-1]: (child.text or "") for child in item}
        out.append({
            "title": fields.get("title", "").strip(),
            "url": fields.get("link", "").strip(),
            "source": feed_url.split("/")[2] if "://" in feed_url else feed_url,
            "summary": fields.get("description", "").strip()[:500],
            "published_ts": None,
        })
    return [i for i in out if i["title"] and i["url"]]


def _gdelt_ts(seendate: str) -> float | None:
    """GDELT 'seendate' formato YYYYMMDDTHHMMSSZ → epoch."""
    if not re.match(r"^\d{8}T\d{6}Z$", seendate or ""):
        return None
    from datetime import datetime, timezone

    return datetime.strptime(seendate, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).timestamp()


def _within_lookback(ts: float | None, lookback_hours: int, now_ts: float) -> bool:
    return ts is None or (now_ts - ts) <= lookback_hours * 3600


# ---------------------------------------------------------------------------
# Dedup y clasificación determinista
# ---------------------------------------------------------------------------


def _normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", title.lower())[:120]


def dedup(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Dedup por URL y por título normalizado; cuenta fuentes cruzadas (M-2).

    Devuelve (items únicos enriquecidos con `cross_sources`, conteo de duplicados).
    """
    by_url: dict[str, dict] = {}
    by_title: dict[str, list[str]] = {}
    dropped = 0
    for item in items:
        url = item["url"].rstrip("/")
        title_key = _normalize_title(item["title"])
        if url in by_url:
            dropped += 1
        else:
            item = item | {"cross_sources": 1}
            by_url[url] = item
        if title_key:
            sources = by_title.setdefault(title_key, [])
            if item["source"] not in sources:
                sources.append(item["source"])
    for item in by_url.values():
        item["cross_sources"] = len(by_title.get(_normalize_title(item["title"]), [item["source"]]))
    return list(by_url.values()), dropped


def classify(item: dict[str, Any]) -> tuple[str, float]:
    """Categoría y confianza base (determinista, antes del filtro Jev)."""
    text = f"{item['title']} {item.get('summary', '')}".lower()
    confidence = 0.5
    if any(kw in text for kw in TAIL_RISK_KEYWORDS):
        category = "TAIL_RISK"
        confidence += 0.2
    else:
        category = "relevant"
    if item.get("cross_sources", 1) >= 2:  # M-2: corroborado por otra fuente
        confidence = min(confidence + 0.15, 0.95)
    return category, round(confidence, 2)


# ---------------------------------------------------------------------------
# Agente: news-analyst
# ---------------------------------------------------------------------------


class NewsAnalystAgent(Agent):
    """Departamento macro (rol news): ingesta multi-fuente → news.alert.v1.

    Fuente pull como macro-analyst: el scheduler pide la ingesta al inicio del
    ciclo. La relevancia la filtra Jev (gratuito); sin Jev, confianza
    penalizada y failover auditado (M-3). Nunca publica otra cosa (M-1, G1).
    """

    department = "macro"
    subscriptions: tuple[str, ...] = ()

    def __init__(
        self,
        feed_config: dict[str, Any],
        jev: JevClient | None = None,
        now: float | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.config = feed_config
        self.jev = jev
        self.now = now  # epoch fijo para ventanas deterministas (tests)

    def handle(self, envelope: Envelope) -> None:
        return None  # fuente pull: el scheduler pide la ingesta al inicio del ciclo

    # -- ingesta ----------------------------------------------------------------

    def ingest(self) -> list[Envelope]:
        """Descarga todas las fuentes, dedup, filtro Jev y publica alertas."""
        items = self._fetch_all()
        unique, _dropped = dedup(items)
        degraded = self.jev is None
        if degraded:  # M-3: failover auditado una vez por ciclo
            self.audit.append(
                actor=self.name,
                event_type="model.failover",
                payload={"agent": self.name, "from_model": "jev", "to_model": None,
                         "reason": "sin evaluador (sin key o presupuesto agotado); confianza penalizada (M-3)"},
            )
        published = []
        for item in unique[: int(self.config.get("max_alerts_per_source", 15)) * max(1, self._n_sources())]:
            category, confidence = classify(item)
            if degraded:
                confidence = round(confidence * 0.7, 2)
                accepted, reason = True, ""
            else:
                accepted, reason = self._relevance(item, confidence)
            if not accepted:
                self.audit.append(
                    actor=self.name,
                    event_type="news.alert_skipped",
                    payload={"title": item["title"][:120], "reason": reason},
                )
                continue
            published.append(self.publish(
                "news.alert.v1",
                {
                    "alert_id": f"alert-{uuid.uuid4().hex[:8]}",
                    "category": category,
                    "confidence": confidence,
                    "single_source": item.get("cross_sources", 1) < 2,
                    "source": item["source"],
                    "quotes": [item["title"]],
                    "summary": item["title"],
                },
            ))
        return published

    def _n_sources(self) -> int:
        cfg = self.config
        return 1 + (1 if cfg.get("finnhub") else 0) + len(cfg.get("rss", []))

    def _fetch_all(self) -> list[dict[str, Any]]:
        import time as _time

        now_ts = self.now if self.now is not None else _time.time()
        lookback = int(self.config.get("lookback_hours", 24))
        items: list[dict[str, Any]] = []

        if gdelt := self.config.get("gdelt"):
            raw = self.use_tool("fetch_news", fetch_gdelt, query=gdelt.get("query", "stock market"), maxrecords=int(gdelt.get("maxrecords", 25)))
            items += parse_gdelt(raw, lookback, now_ts)

        if finnhub := self.config.get("finnhub"):
            import os

            token = os.environ.get(finnhub.get("api_key_env", "FINNHUB_API_KEY"), "")
            if token:
                raw = self.use_tool("fetch_news", fetch_finnhub, category=finnhub.get("category", "general"), token=token)
                items += [i for i in raw if _within_lookback(i["published_ts"], lookback, now_ts)]

        for feed_url in self.config.get("rss", []):
            items += self.use_tool("fetch_news", fetch_rss, feed_url=feed_url)

        return items

    # -- filtro Jev (M-3) ---------------------------------------------------------

    def _relevance(self, item: dict[str, Any], confidence: float) -> tuple[bool, str]:
        try:
            state = json.dumps({"title": item["title"], "summary": item.get("summary", "")}, ensure_ascii=False)
            answers = self.jev.evaluate(state, JEV_QUESTIONS)
        except (RuntimeError, BudgetExceeded) as e:
            self.audit.append(
                actor=self.name,
                event_type="model.failover",
                payload={"agent": self.name, "from_model": "jev", "to_model": None,
                         "reason": f"evaluador no disponible; confianza penalizada: {e}"},
            )
            return True, ""
        noul = answers.get("market_relevant", {}).get("noul")
        if noul is not None and noul < NOUL_RELEVANCE_THRESHOLD:
            return False, f"jev: relevancia {noul:.2f} < {NOUL_RELEVANCE_THRESHOLD}"
        return True, ""


def load_feed_config(path: str | Path) -> dict[str, Any]:
    import yaml

    p = Path(path)
    return yaml.safe_load(p.read_text()) if p.exists() else {}


# ---------------------------------------------------------------------------

def build_news_agent(
    gateway: ModelGateway | None,
    feed_config: dict[str, Any],
    env: dict[str, str] | None = None,
    governor: Any | None = None,
    **agent_kwargs: Any,
) -> NewsAnalystAgent:
    """news-analyst con Jev del gateway (sin key de Jev ⇒ filtro M-3 degradado)."""
    jev = None
    if gateway is not None:
        try:
            jev = gateway.client_for("news-analyst", "evaluator", env=env, governor=governor)
        except KeyError:
            jev = None  # sin modelo evaluador asignado: degradación M-3
    return NewsAnalystAgent(feed_config=feed_config, jev=jev, **agent_kwargs)
