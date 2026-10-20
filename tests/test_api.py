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


def test_strategy_endpoint_gone(tmp_path):
    """机器池子模板端点已退役——条件选股引擎取代（404=无此路由）。"""
    store = Store(str(tmp_path / "wb.db"))
    client = TestClient(create_app(store=store, cache_dir=str(tmp_path)))
    assert client.get("/api/strategy/value").status_code == 404


def test_metrics_endpoint(tmp_path):
    store = Store(str(tmp_path / "wb.db"))
    client = TestClient(create_app(store=store, cache_dir=str(tmp_path)))
    body = client.get("/api/metrics").json()
    assert len(body["metrics"]) == 27
    m = body["metrics"][0]
    for key in ("key", "name", "category", "caliber", "kind", "ops", "unit"):
        assert key in m
    cats = {m["category"] for m in body["metrics"]}
    assert cats == {"基础信息", "估值", "财务", "技术", "风险过滤"}


def test_presets_endpoint(tmp_path):
    store = Store(str(tmp_path / "wb.db"))
    client = TestClient(create_app(store=store, cache_dir=str(tmp_path)))
    body = client.get("/api/presets").json()
    assert [p["key"] for p in body["presets"]] == ["value", "quality", "trend"]
    assert all(p["rule"]["conditions"] for p in body["presets"])


def test_screen_endpoint(monkeypatch, tmp_path):
    store = Store(str(tmp_path / "wb.db"))
    captured = {}

    def fake_run_screen(rule, cache_dir, refresh=False):
        captured.update({"rule": rule, "cache_dir": cache_dir})
        return {"universe": 100, "kline_scanned": 0, "slow_fetched": 0, "count": 1,
                "items": [{"code": "600000", "name": "浦发银行", "reasons": ["PE 6.3 < 20✓"],
                           "values": {"pe_ttm": 6.3}}],
                "market_guard": {"above_ma20": True}, "manual_review": [], "asof": "2026-10-20T10:00:00"}

    monkeypatch.setattr("quant_sentiment.conditions.run_screen", fake_run_screen)
    client = TestClient(create_app(store=store, cache_dir=str(tmp_path)))
    rule = {"logic": "all",
            "conditions": [{"metric": "pe_ttm", "op": "between", "min": 0, "max": 20}]}
    resp = client.post("/api/screen", json=rule)
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1 and body["items"][0]["code"] == "600000"
    assert captured["cache_dir"] == str(tmp_path)  # cache_dir 传递（缓存根因指纹）

    # 非法规则 → 422 + 错误明细
    resp = client.post("/api/screen", json={"conditions": [{"metric": "nope", "op": ">", "value": 1}]})
    assert resp.status_code == 422
    assert "nope" in resp.json()["detail"]

    # 数据源故障 → 502
    monkeypatch.setattr("quant_sentiment.conditions.run_screen",
                        lambda rule, cache_dir, refresh=False: (_ for _ in ()).throw(RuntimeError("数据源不可用")))
    resp = client.post("/api/screen", json=rule)
    assert resp.status_code == 502


def test_backtest_endpoint(monkeypatch, tmp_path):
    store = Store(str(tmp_path / "wb.db"))
    client = TestClient(create_app(store=store, cache_dir=str(tmp_path)))

    # 含财务条件的规则 → 422 防未来数据泄漏
    rule = {"conditions": [{"metric": "pe_ttm", "op": "<", "value": 20}]}
    resp = client.post("/api/backtest", json=rule)
    assert resp.status_code == 422
    assert "泄漏" in resp.json()["detail"]

    # 纯K线规则 → 回测结果
    def fake_run_backtest(rule, cache_dir, kline_limit=250, hold=20, stop=-0.08):
        return {"stats": {"n": 25, "win_rate": 0.6, "payoff": 1.6, "max_dd": -0.1, "sharpe": 1.2},
                "verdict": {"ok": True, "text": "达标"}, "trades": [0.1, -0.02],
                "note": "口径", "n_stocks": 250, "asof": "2026-10-20T10:00:00"}

    monkeypatch.setattr("quant_sentiment.conditions.run_backtest", fake_run_backtest)
    kline_rule = {"conditions": [{"metric": "above_ma20", "op": "eq", "value": 1}]}
    resp = client.post("/api/backtest", json=kline_rule)
    assert resp.status_code == 200
    assert resp.json()["stats"]["n"] == 25


def test_rules_crud_endpoint(tmp_path):
    store = Store(str(tmp_path / "wb.db"))
    client = TestClient(create_app(store=store, cache_dir=str(tmp_path)))

    assert client.get("/api/rules").json()["rules"] == []

    rule = {"logic": "all",
            "conditions": [{"metric": "pe_ttm", "op": "between", "min": 0, "max": 20}]}
    resp = client.post("/api/rules", json={"name": "低估值改良", "rule": rule})
    assert resp.status_code == 201
    assert resp.json()["version"] == 1

    body = client.get("/api/rules").json()["rules"]
    assert len(body) == 1 and body[0]["name"] == "低估值改良"
    assert body[0]["spec"]["conditions"][0]["max"] == 20

    resp = client.post("/api/rules", json={"name": "", "rule": rule})
    assert resp.status_code == 422  # 空名字拒绝

    resp = client.delete("/api/rules/低估值改良")
    assert resp.status_code == 204
    assert client.delete("/api/rules/低估值改良").status_code == 404


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
