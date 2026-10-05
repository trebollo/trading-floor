"""Tests de la fuente de datos real (offline: sin red, sin Yahoo)."""

import pytest

from tf.datafeed import ingest_yahoo, normalize_yahoo
from tf.marketdata import load_csv

# Respuesta real de Yahoo recortada a 3 barras (y una con OHLC incompleto).
YAHOO_SAMPLE = """{
  "chart": {"result": [{
    "meta": {"symbol": "AAPL"},
    "timestamp": [1704153600, 1704240000, 1704326400, 1704412800],
    "indicators": {"quote": [{
      "open": [100.5, 101.3, 102.9, null],
      "high": [102.0, 103.1, 103.5, null],
      "low": [99.8, 101.0, 101.7, null],
      "close": [101.3, 102.9, 103.0, null]
    }]}
  }], "error": null}
}"""


def test_normalize_yahoo_to_internal_format():
    normalized = normalize_yahoo(YAHOO_SAMPLE, "AAPL")
    lines = normalized.strip().splitlines()
    assert lines[0] == "ts,open,high,low,close"
    assert len(lines) == 4  # cabecera + 3 barras (la 4ª con nulls se descarta)
    assert lines[1] == "1704153600,100.5,102.0,99.8,101.3"


def test_ingest_writes_valid_csv_loadable_by_load_csv(tmp_path):
    path = ingest_yahoo("AAPL", YAHOO_SAMPLE, out_dir=tmp_path)
    assert path.name == "aapl.csv"
    md = load_csv(path, symbol="AAPL")
    assert len(md) == 3
    assert md.symbol == "AAPL"


def test_ingest_rejects_symbol_error(tmp_path):
    raw = '{"chart": {"result": null, "error": {"code": "Bad Request", "description": "Invalid input - start date cannot be after end date."}}}'
    with pytest.raises(ValueError, match="start date cannot be after end date"):
        ingest_yahoo("XX", raw, out_dir=tmp_path)


def test_ingest_rejects_empty_result(tmp_path):
    raw = '{"chart": {"result": [{"timestamp": [], "indicators": {"quote": [{}]}}], "error": null}}'
    with pytest.raises(ValueError, match="no devolvió filas"):
        ingest_yahoo("XX", raw, out_dir=tmp_path)


def test_ingest_rejects_incoherent_ohlc(tmp_path):
    raw = """{
      "chart": {"result": [{
        "timestamp": [1704153600, 1704240000],
        "indicators": {"quote": [{
          "open": [100.5, 101.3], "high": [102.0, 90.0],
          "low": [99.8, 101.0], "close": [101.3, 102.9]
        }]}
      }], "error": null}
    }"""
    with pytest.raises(ValueError, match="OHLC"):
        ingest_yahoo("XX", raw, out_dir=tmp_path)


def test_fetch_yahoo_builds_expected_url(monkeypatch):
    from tf import datafeed

    captured = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url

        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return YAHOO_SAMPLE.encode()

        return Resp()

    monkeypatch.setattr(datafeed.urllib.request, "urlopen", fake_urlopen)
    datafeed.fetch_yahoo("AAPL", start="20240101", end="20240201")
    assert (
        captured["url"]
        == "https://query1.finance.yahoo.com/v8/finance/chart/AAPL?interval=1d&period1=1704067200&period2=1706745600"
    )
