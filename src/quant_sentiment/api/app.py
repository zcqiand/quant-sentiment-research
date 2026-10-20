"""个人选股工作台 API：人工池子 / 机器池子，只做选股这一件事。

端口约定：api=8610（配套前端 dev=5610，vite proxy /api → 127.0.0.1:8610）。

- GET  /api/health              探活 + 在线/离线
- GET  /api/watchlist           人工池子（watchlist + 报价/候选池快照）
- POST /api/watchlist           加自选 {symbol, name?, note?}
- DELETE /api/watchlist/{sym}   移出自选
- GET  /api/strategy/{key}      机器池子（value/momentum：因子交叉+回测+计划）
- GET  /api/stocks/{symbol}     个股极简详情（K线 + 交易计划 + 人工核查清单）

选股结果仅供研究参考，不构成买卖指令。
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .. import strategies as st
from ..gateway import _offline_active, fetch_kline, fetch_stock_name
from ..screener import fetch_quotes, rows_cached
from ..store import Store

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DATA_DIR = _REPO_ROOT / "data"
_SYMBOL_RE = re.compile(r"^\d{6}$")

_WEB_ORIGINS = [
    "http://localhost:5610",
    "http://127.0.0.1:5610",
]


class WatchlistItem(BaseModel):
    symbol: str
    name: str = ""
    note: str = ""


def _default_store() -> Store:
    db_path = os.getenv("WORKBENCH_DB_PATH") or str(_DATA_DIR / "workbench.db")
    return Store(db_path)


def create_app(store: Store | None = None, cache_dir: str | None = None) -> FastAPI:
    store = store if store is not None else _default_store()
    cache_dir = cache_dir or str(_DATA_DIR)  # K线/因子缓存的落盘目录，必须给
    app = FastAPI(title="stock-picker-workbench", version="3.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_WEB_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def _pool_rows() -> list[dict]:
        return rows_cached(cache_dir)

    def _pool_rows_safe() -> list[dict]:
        try:
            return _pool_rows()
        except Exception:  # noqa: BLE001 - 候选池拉不到不阻塞人工池子
            return []

    @app.get("/api/health")
    def health() -> dict:
        return {
            "ok": True,
            "app": "个人选股工作台",
            "mode": "offline" if _offline_active() else "online",
        }

    # ---- 人工池子 ----

    @app.get("/api/watchlist")
    def watchlist() -> dict:
        items = store.list_all()
        codes = [i["symbol"] for i in items]
        quotes: dict = {}
        if codes:
            try:
                quotes = fetch_quotes(codes)
            except Exception:  # noqa: BLE001
                quotes = {}
        pool = {r["code"]: r for r in _pool_rows_safe()}
        rows = []
        for it in items:
            row = {**it}
            q = quotes.get(it["symbol"])
            if q:
                row.update({"price": q["price"], "pe_ttm": q["pe_ttm"], "pb": q["pb"], "mcap_yi": q["mcap_yi"]})
            p = pool.get(it["symbol"])
            if p:  # 候选池命中 → 附基础因子快照（不做逐股重请求）
                row.update({
                    "roe": p["roe"], "debt_ratio": p["debt_ratio"],
                    "div_yield": p["div_yield"], "turnover_wan": p.get("turnover_wan"),
                    "in_pool": True,
                })
            else:
                row.setdefault("in_pool", False)
            rows.append(row)
        return {"count": len(rows), "items": rows}

    @app.post("/api/watchlist", status_code=201)
    def add_watch(item: WatchlistItem) -> dict:
        if not _SYMBOL_RE.match(item.symbol):
            raise HTTPException(422, "代码须为6位数字")
        name = item.name or fetch_stock_name(item.symbol)
        store.upsert(item.symbol, name, item.note)
        return {"symbol": item.symbol, "name": name}

    @app.delete("/api/watchlist/{symbol}", status_code=204)
    def remove_watch(symbol: str) -> None:
        if not store.remove(symbol):
            raise HTTPException(404, f"{symbol} 不在人工池子")

    # ---- 机器池子 ----

    @app.get("/api/strategy/{key}")
    def strategy(key: str, refresh: bool = False) -> dict:
        try:
            return st.run_strategy(key, cache_dir, refresh)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - 数据源故障统一 502
            raise HTTPException(502, f"选股失败：{exc}") from exc

    # ---- 个股详情（极简：K线 + 计划 + 人工核查） ----

    @app.get("/api/stocks/{symbol}")
    def stock_detail(symbol: str) -> dict:
        if not _SYMBOL_RE.match(symbol):
            raise HTTPException(422, "代码须为6位数字")
        try:
            quote = fetch_quotes([symbol]).get(symbol)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"行情不可用：{exc}") from exc
        if quote is None:
            raise HTTPException(404, f"{symbol} 无行情数据")
        try:
            kline = fetch_kline(symbol, days=120, cache_dir=cache_dir)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"K线不可用：{exc}") from exc
        return {
            "symbol": symbol,
            "name": quote["name"],
            "price": quote["price"],
            "pe_ttm": quote["pe_ttm"],
            "pb": quote["pb"],
            "mcap_yi": quote["mcap_yi"],
            "kline": kline.to_dict(orient="records"),
            "plan": st.trade_plan(quote["price"]),
            "manual_review": st.manual_review_items({"code": symbol, "name": quote["name"]}),
        }

    return app


__all__ = ["create_app"]
