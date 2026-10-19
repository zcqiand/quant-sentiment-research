"""SQLite 存储层测试：watchlist / news_scores / research_runs / scans。"""

from quant_sentiment.store import WorkbenchStore


def test_watchlist_roundtrip(tmp_path):
    store = WorkbenchStore(str(tmp_path / "wb.db"))
    store.upsert_watchlist("600000", "浦发银行")
    store.upsert_watchlist("000001", "平安银行")
    rows = store.list_watchlist()
    assert [r["symbol"] for r in rows] == ["600000", "000001"]
    assert rows[0]["name"] == "浦发银行"

    store.upsert_watchlist("600000", "浦发银行SPDB")  # 更名即 upsert
    rows = store.list_watchlist()
    assert len(rows) == 2
    assert rows[0]["name"] == "浦发银行SPDB"

    store.remove_watchlist("600000")
    assert [r["symbol"] for r in store.list_watchlist()] == ["000001"]


def test_news_score_put_get(tmp_path):
    store = WorkbenchStore(str(tmp_path / "wb.db"))
    assert store.get_news_score("http://x/1") is None
    store.put_news_score("http://x/1", "600000", "利好", 0.9)
    hit = store.get_news_score("http://x/1")
    assert hit == {"label": "利好", "confidence": 0.9}


def test_research_runs_latest_per_symbol(tmp_path):
    store = WorkbenchStore(str(tmp_path / "wb.db"))
    store.save_run("600000", "2026-10-19T09:00:00", 42.0, {"composite": 42.0})
    store.save_run("600000", "2026-10-19T09:30:00", 55.0, {"composite": 55.0})
    store.save_run("000001", "2026-10-19T09:10:00", -10.0, {"composite": -10.0})

    latest = store.latest_run_per_symbol()
    assert latest["600000"]["composite"] == 55.0
    assert latest["000001"]["composite"] == -10.0


def test_scan_save_and_latest(tmp_path):
    store = WorkbenchStore(str(tmp_path / "wb.db"))
    assert store.latest_scan() is None
    store.save_scan("2026-10-19T09:00:00", {"results": [], "errors": []})
    scan = store.latest_scan()
    assert scan["ts"] == "2026-10-19T09:00:00"
    assert scan["payload"] == {"results": [], "errors": []}
