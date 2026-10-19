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


def test_default_workbench_has_cache_dir(tmp_path, monkeypatch):
    """线上默认 Workbench 必须带 cache_dir——详情接口的 K 线/新闻 TTL 缓存靠它落盘。"""
    from quant_sentiment.api.app import _default_workbench

    monkeypatch.setenv("WORKBENCH_DB_PATH", str(tmp_path / "wb.db"))
    wb = _default_workbench()
    assert wb.cache_dir


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
    assert body["news"][0]["label"] is None  # 详情不做 LLM 打分，秒开
    assert client.post("/api/stocks/600000/research").status_code == 200


def test_news_scoring_button_triggered(tmp_path):
    """打分由按钮（POST score-news）触发；打过的进缓存，二次触发零 LLM 消费。"""
    from quant_sentiment.api.app import create_app
    from quant_sentiment.llm import FakeLLM
    from quant_sentiment.workbench import Workbench

    _fixtures(tmp_path)
    wb = Workbench(
        db_path=str(tmp_path / "wb.db"),
        cache_dir=str(tmp_path),
        llm=FakeLLM(script=['{"label":"利好","confidence":0.9}']),
    )
    wb.add_stock("600000", "浦发银行")
    client = TestClient(create_app(workbench=wb))

    body = client.get("/api/stocks/600000").json()
    assert body["news"][0]["label"] is None
    assert wb.llm._cursor == 0  # 详情零 LLM 消费

    scored = client.post("/api/stocks/600000/score-news")
    assert scored.status_code == 200
    assert scored.json()["news"][0]["label"] == "利好"
    assert wb.llm._cursor == 1  # 恰好消费一次

    again = client.post("/api/stocks/600000/score-news").json()
    assert again["news"][0]["label"] == "利好"
    assert wb.llm._cursor == 1  # 二次全走缓存


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


def _buyindex_rows():
    hist = {"20251231": 20.0, "20241231": 19.0, "20231231": 18.0, "20221231": 21.0, "20211231": 17.0}
    def row(code, name, **kw):
        base = {
            "code": code, "name": name, "price": 20.0, "pe_ttm": 15.0, "pb": 1.2,
            "mcap_yi": 200.0, "roe": 20.0, "debt_ratio": 35.0, "growth": 25.0,
            "ocf": {"20251231": 12.0, "20241231": 11.0, "20231231": 10.0},
            "ocf_hist": {"20251231": 12.0, "20241231": 11.0, "20231231": 10.0},
            "profit": 10.0, "profit_hist": {"20251231": 10.0, "20241231": 9.0, "20231231": 8.0},
            "roe_hist": hist,
            "dps": {"20251231": 0.5, "20241231": 0.5, "20231231": 0.5}, "div_yield": 2.5,
        }
        base.update(kw)
        return base

    return [row("600001", "甲"), row("600002", "乙", roe_hist={k: v - 5 for k, v in hist.items()}, roe=15.0)]


def test_screener_buyindex(tmp_path, monkeypatch):
    from quant_sentiment import buy_index as bi_mod
    from quant_sentiment import screener

    monkeypatch.setattr(screener, "rows_cached", lambda cache_dir, refresh=False: _buyindex_rows())
    monkeypatch.setattr(bi_mod, "percentiles_cached", lambda codes, cache_dir: {c: 40.0 for c in codes})
    monkeypatch.setattr(bi_mod, "industry_cached", lambda pairs, cache_dir: {c: "食品饮料-白酒" for c, _ in pairs})
    client = _client(tmp_path)

    body = client.get("/api/screener/buyindex").json()
    assert body["kind"] == "buyindex"
    assert body["count"] == 2
    assert 0 < body["items"][0]["buy_index"] <= 100
    assert body["items"][0]["label"]
    assert set(body["items"][0]["dims"]) == {"roe", "debt", "peg", "percentile", "cash", "industry"}
