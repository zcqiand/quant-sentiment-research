"""工作台存储测试：人工池子（watchlist）+ 选股规则版本保留（rules），离线全绿。"""

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


# ---- 选股规则（版本保留：同名单次保存 version+1，旧版本行不删） ----

def _rule_spec(pe_max=20):
    return {"logic": "all",
            "conditions": [{"metric": "pe_ttm", "op": "between", "min": 0, "max": pe_max}]}


def test_rules_crud_and_versions(tmp_path):
    store = Store(str(tmp_path / "t.db"))
    assert store.list_rules() == []

    v1 = store.save_rule("我的低估值", _rule_spec(pe_max=20))
    assert v1 == 1
    v2 = store.save_rule("我的低估值", _rule_spec(pe_max=30))  # 同名再存 → 新版本
    assert v2 == 2

    rules = store.list_rules()
    assert len(rules) == 1  # 列表只出每名最新版
    r = rules[0]
    assert r["name"] == "我的低估值" and r["version"] == 2
    assert r["spec"]["conditions"][0]["max"] == 30  # spec 已还原为 dict

    got = store.get_rule("我的低估值")
    assert got["version"] == 2 and got["spec"]["conditions"][0]["max"] == 30
    assert store.get_rule("不存在") is None

    assert store.delete_rule("我的低估值") is True
    assert store.delete_rule("我的低估值") is False
    assert store.list_rules() == []
