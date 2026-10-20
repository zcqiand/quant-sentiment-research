"""人工池子存储测试：watchlist 增删查，离线全绿。"""

from quant_sentiment.store import Store


def test_watchlist_roundtrip(tmp_path):
    store = Store(str(tmp_path / "t.db"))
    assert store.list_all() == []

    store.upsert("600000", "浦发银行")
    store.upsert("000858", "五粮液", note="动量候选")
    rows = store.list_all()
    assert [r["symbol"] for r in rows] == ["600000", "000858"]
    assert rows[1]["note"] == "动量候选"

    store.upsert("600000", "浦发银行", note="价值候选")  # upsert 更新
    rows = store.list_all()
    assert len(rows) == 2
    assert rows[0]["note"] == "价值候选"

    assert store.remove("600000") is True
    assert store.remove("600000") is False
    assert [r["symbol"] for r in store.list_all()] == ["000858"]


def test_migrate_v2_watchlist_adds_note(tmp_path):
    """2.x 旧库的 watchlist 没有 note 列——打开时自动补，数据保留。"""
    import sqlite3

    db = str(tmp_path / "old.db")
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE watchlist (symbol TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '', added_at TEXT NOT NULL)")
    conn.execute("INSERT INTO watchlist VALUES('600000', '浦发银行', '2026-01-01')")
    conn.commit()
    conn.close()

    store = Store(db)
    rows = store.list_all()
    assert len(rows) == 1
    assert rows[0]["symbol"] == "600000"
    assert rows[0]["note"] == ""
