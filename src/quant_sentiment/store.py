"""工作台 SQLite 存储层：watchlist / 舆情打分缓存 / 研究快照 / 扫描历史。

stdlib sqlite3，单文件库；表结构在构造时自动建齐（幂等）。
"""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS watchlist (
    symbol   TEXT PRIMARY KEY,
    name     TEXT NOT NULL DEFAULT '',
    added_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS news_scores (
    nkey       TEXT PRIMARY KEY,
    symbol     TEXT NOT NULL,
    label      TEXT NOT NULL,
    confidence REAL NOT NULL,
    scored_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_runs (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol    TEXT NOT NULL,
    ts        TEXT NOT NULL,
    composite REAL NOT NULL,
    payload   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scans (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_symbol ON research_runs(symbol, id);
"""


class WorkbenchStore:
    """工作台持久化门面。个人单机用，单连接 + 写后 commit。"""

    def __init__(self, db_path: str) -> None:
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ---- watchlist ----

    def upsert_watchlist(self, symbol: str, name: str = "") -> None:
        from datetime import datetime

        self._conn.execute(
            "INSERT INTO watchlist(symbol, name, added_at) VALUES(?, ?, ?) "
            "ON CONFLICT(symbol) DO UPDATE SET name = excluded.name",
            (symbol, name, datetime.now().isoformat(timespec="seconds")),
        )
        self._conn.commit()

    def remove_watchlist(self, symbol: str) -> bool:
        cur = self._conn.execute("DELETE FROM watchlist WHERE symbol = ?", (symbol,))
        self._conn.commit()
        return cur.rowcount > 0

    def list_watchlist(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT symbol, name, added_at FROM watchlist ORDER BY rowid"
        ).fetchall()
        return [dict(r) for r in rows]

    # ---- 舆情打分缓存 ----

    def get_news_score(self, nkey: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT label, confidence FROM news_scores WHERE nkey = ?", (nkey,)
        ).fetchone()
        return {"label": row["label"], "confidence": row["confidence"]} if row else None

    def put_news_score(self, nkey: str, symbol: str, label: str, confidence: float) -> None:
        from datetime import datetime

        self._conn.execute(
            "INSERT OR REPLACE INTO news_scores(nkey, symbol, label, confidence, scored_at) "
            "VALUES(?, ?, ?, ?, ?)",
            (nkey, symbol, label, confidence, datetime.now().isoformat(timespec="seconds")),
        )
        self._conn.commit()

    # ---- 研究快照 ----

    def save_run(self, symbol: str, ts: str, composite: float, payload: dict) -> None:
        self._conn.execute(
            "INSERT INTO research_runs(symbol, ts, composite, payload) VALUES(?, ?, ?, ?)",
            (symbol, ts, composite, json.dumps(payload, ensure_ascii=False)),
        )
        self._conn.commit()

    def latest_run_per_symbol(self) -> dict[str, dict]:
        """每个 symbol 取最新一次快照，返回 {symbol: payload}。"""
        rows = self._conn.execute(
            "SELECT r.symbol AS sym, r.payload AS payload FROM research_runs r "
            "WHERE r.id = (SELECT MAX(id) FROM research_runs WHERE symbol = r.symbol)"
        ).fetchall()
        return {r["sym"]: json.loads(r["payload"]) for r in rows}

    def list_runs(self, symbol: str, limit: int = 30) -> list[dict]:
        rows = self._conn.execute(
            "SELECT ts, composite, payload FROM research_runs WHERE symbol = ? "
            "ORDER BY id DESC LIMIT ?",
            (symbol, limit),
        ).fetchall()
        return [
            {"ts": r["ts"], "composite": r["composite"], "payload": json.loads(r["payload"])}
            for r in rows
        ]

    # ---- 扫描历史 ----

    def save_scan(self, ts: str, payload: dict) -> None:
        self._conn.execute(
            "INSERT INTO scans(ts, payload) VALUES(?, ?)",
            (ts, json.dumps(payload, ensure_ascii=False)),
        )
        self._conn.commit()

    def latest_scan(self) -> dict | None:
        row = self._conn.execute(
            "SELECT ts, payload FROM scans ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return {"ts": row["ts"], "payload": json.loads(row["payload"])}


__all__ = ["WorkbenchStore"]
