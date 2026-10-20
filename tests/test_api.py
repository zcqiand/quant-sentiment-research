"""API 层测试：FastAPI TestClient + 离线 fixture，无 Key 无网全绿。"""

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from quant_sentiment.api.app import create_app
from quant_sentiment.gateway import set_offline
from quant_sentiment.store import Store


@pytest.fixture(autouse=True)
def _offline():
    set_offline(True)
    yield
    set_offline(False)


def _kline_frame():
    return pd.DataFrame(
        {
            "date": [f"2026-01-{d:02d}" for d in range(1, 31)],
            "open": [10.0] * 30,
            "close": [10.0 + i * 0.1 for i in range(30)],
            "high": [10.5 + i * 0.1 for i in range(30)],
            "low": [9.8 + i * 0.1 for i in range(30)],
            "volume": [1000] * 30,
        }
    )


def _client(tmp_path, monkeypatch) -> TestClient:
    store = Store(str(tmp_path / "wb.db"))
    store.upsert("600000", "浦发银行")
    monkeypatch.setattr("quant_sentiment.api.app.fetch_quotes", lambda codes: {
        "600000": {"name": "浦发银行", "price": 10.0, "turnover_wan": 20000.0,
                   "pe_ttm": 6.3, "pb": 0.43, "mcap_yi": 3227.0},
    })
    monkeypatch.setattr("quant_sentiment.api.app.rows_cached", lambda cache_dir, refresh=False: [])
    monkeypatch.setattr("quant_sentiment.api.app.fetch_stock_name", lambda sym: "平安银行")
    return TestClient(create_app(store=store, cache_dir=str(tmp_path)))


def test_health(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["mode"] == "offline"


def test_watchlist_crud_and_snapshot(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    body = client.get("/api/watchlist").json()
    assert body["count"] == 1
    row = body["items"][0]
    assert row["symbol"] == "600000"
    assert row["price"] == 10.0  # 报价快照
    assert row["in_pool"] is False

    resp = client.post("/api/watchlist", json={"symbol": "000001"})  # 名称自动回查
    assert resp.status_code == 201
    assert resp.json()["name"] == "平安银行"
    assert client.get("/api/watchlist").json()["count"] == 2

    assert client.post("/api/watchlist", json={"symbol": "abc"}).status_code == 422
    assert client.delete("/api/watchlist/000001").status_code == 204
    assert client.delete("/api/watchlist/000001").status_code == 404


def test_strategy_endpoint(monkeypatch, tmp_path):
    store = Store(str(tmp_path / "wb.db"))
    monkeypatch.setattr("quant_sentiment.strategies.rows_cached", lambda cache_dir, refresh=False: [])
    monkeypatch.setattr("quant_sentiment.strategies.market_guard",
                        lambda cache_dir: {"above_ma20": True, "text": "ok"})
    client = TestClient(create_app(store=store, cache_dir=str(tmp_path)))

    body = client.get("/api/strategy/value").json()
    assert body["key"] == "value"
    assert body["market_guard"]["above_ma20"] is True

    assert client.get("/api/strategy/nope").status_code == 404

    def boom(cache_dir, refresh=False):
        raise RuntimeError("数据源不可用")

    monkeypatch.setattr("quant_sentiment.strategies.rows_cached", boom)
    resp = client.get("/api/strategy/value")
    assert resp.status_code == 502
    assert "数据源不可用" in resp.json()["detail"]


def test_strategy_endpoint_uses_app_cache_dir(monkeypatch, tmp_path):
    """strategy 端点必须把 create_app 的 cache_dir 传给 run_strategy（缓存根因指纹）。"""
    store = Store(str(tmp_path / "wb.db"))
    seen = {}

    def fake_run(key, cache_dir, refresh=False):
        seen["cache_dir"] = cache_dir
        return {"key": key, "count": 0, "items": [], "backtest": None,
                "backtest_note": "", "market_guard": None, "manual_review": []}

    monkeypatch.setattr("quant_sentiment.strategies.run_strategy", fake_run)
    client = TestClient(create_app(store=store, cache_dir=str(tmp_path)))
    client.get("/api/strategy/momentum")
    assert seen["cache_dir"] == str(tmp_path)


def test_stock_detail(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    monkeypatch.setattr("quant_sentiment.api.app.fetch_kline",
                        lambda symbol, days, cache_dir: _kline_frame())
    body = client.get("/api/stocks/600000").json()
    assert body["name"] == "浦发银行"
    assert len(body["kline"]) == 30
    assert body["kline"][-1]["close"] == pytest.approx(12.9)
    assert body["plan"]["stop_price"] == pytest.approx(9.25)
    assert any("质押" in t for t in body["manual_review"])


def test_stock_detail_unknown_symbol(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    assert client.get("/api/stocks/999999").status_code == 404  # 报价里没有
    assert client.get("/api/stocks/abc").status_code == 422
