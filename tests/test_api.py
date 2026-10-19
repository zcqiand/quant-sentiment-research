"""API 层测试：FastAPI TestClient + 离线 fixture，无 Key 无网全绿。"""

import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from quant_sentiment.api.app import create_app
from quant_sentiment.gateway import set_offline
from quant_sentiment.llm import FakeLLM
from quant_sentiment.workbench import Workbench


@pytest.fixture(autouse=True)
def _offline():
    set_offline(True)
    yield
    set_offline(False)


def _fixtures(tmp_path):
    pd.DataFrame(
        {
            "date": [f"2026-01-{d:02d}" for d in range(1, 31)],
            "open": [10.0] * 30,
            "close": [10.0 + i * 0.1 for i in range(30)],
            "high": [10.5 + i * 0.1 for i in range(30)],
            "low": [9.8 + i * 0.1 for i in range(30)],
            "volume": [1000] * 30,
        }
    ).to_parquet(tmp_path / "kline_600000.parquet")
    (tmp_path / "news_600000.json").write_text(
        json.dumps(
            [{"title": "业绩超预期", "content": "净利润大增", "url": "http://x/1", "ts": "2026-01-30 08:00"}]
        ),
        encoding="utf-8",
    )


def _client(tmp_path) -> TestClient:
    _fixtures(tmp_path)
    wb = Workbench(
        db_path=str(tmp_path / "wb.db"),
        cache_dir=str(tmp_path),
        llm=FakeLLM(script=['{"label":"利好","confidence":0.9}']),
    )
    wb.add_stock("600000", "浦发银行")
    return TestClient(create_app(workbench=wb))


def test_health(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["llm"]["mode"] == "fake"


def test_watchlist_crud(tmp_path):
    client = _client(tmp_path)
    assert [r["symbol"] for r in client.get("/api/watchlist").json()] == ["600000"]

    resp = client.post("/api/watchlist", json={"symbol": "000001", "name": "平安银行"})
    assert resp.status_code == 201
    assert len(client.get("/api/watchlist").json()) == 2

    assert client.delete("/api/watchlist/000001").status_code == 204
    assert client.delete("/api/watchlist/000001").status_code == 404


def test_scan_and_latest(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/api/scan")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["results"]) == 1
    assert body["results"][0]["composite_label"]

    latest = client.get("/api/scan/latest").json()
    assert latest["results"][0]["symbol"] == "600000"


def test_stock_detail(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/api/stocks/600000")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["kline"]) == 30
    assert body["kline"][-1]["close"] == pytest.approx(12.9)
    assert "ma5" in body["indicators"]
    assert body["news"][0]["label"] == "利好"
    assert client.post("/api/stocks/600000/research").status_code == 200


def test_stock_detail_unknown_symbol_502(tmp_path):
    client = _client(tmp_path)
    assert client.get("/api/stocks/999999").status_code == 502


def test_backtest_requires_gold(tmp_path):
    client = _client(tmp_path)
    assert client.get("/api/backtest/600000").status_code == 404

    gold = {"http://x/1": "利好"}
    (tmp_path / "gold_600000.json").write_text(json.dumps(gold, ensure_ascii=False), encoding="utf-8")
    resp = client.get("/api/backtest/600000")
    assert resp.status_code == 200
    body = resp.json()
    assert body["samples"] == 1
    assert body["precision"] == 1.0


# ---- 选股器 ----

def _screener_rows():
    def row(code, name, **kw):
        base = {
            "code": code, "name": name, "price": 10.0, "pe_ttm": 15.0, "pb": 1.0,
            "mcap_yi": 100.0, "roe": 18.0, "debt_ratio": 40.0,
            "ocf": {"2025": 5.0, "2024": 4.0, "2023": 3.0}, "profit": 6.0,
            "dps": {"2025": 0.7, "2024": 0.7, "2023": 0.7}, "div_yield": 7.0,
        }
        base.update(kw)
        return base

    return [
        row("600001", "甲", roe=18.0, div_yield=6.0),
        row("600002", "乙", roe=22.0, div_yield=8.0),
        row("600003", "不符合", roe=3.0, div_yield=1.0),
    ]


def test_screener_endpoints(tmp_path, monkeypatch):
    from quant_sentiment import screener

    monkeypatch.setattr(screener, "rows_cached", lambda cache_dir, refresh=False: _screener_rows())
    client = _client(tmp_path)

    white = client.get("/api/screener/whitehorse").json()
    assert white["count"] == 2
    assert white["items"][0]["code"] == "600002"  # ROE 降序
    assert white["caliber"]

    div = client.get("/api/screener/dividend").json()
    assert div["count"] == 2
    assert div["items"][0]["div_yield"] == 8.0  # 股息率降序


def test_screener_failure_502(tmp_path, monkeypatch):
    from quant_sentiment import screener

    def boom(cache_dir, refresh=False):
        raise RuntimeError("数据源不可用")

    monkeypatch.setattr(screener, "rows_cached", boom)
    client = _client(tmp_path)
    resp = client.get("/api/screener/whitehorse")
    assert resp.status_code == 502
    assert "数据源不可用" in resp.json()["detail"]
