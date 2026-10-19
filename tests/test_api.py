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
