"""个人选股工作台 API：条件选股（统一条件引擎）+ 人工池子，只做选股这一件事。

端口约定：api=8610（配套前端 dev=5610，vite proxy /api → 127.0.0.1:8610）。

- GET  /api/health              探活 + 在线/离线
- GET  /api/metrics             指标目录（27个，五大类，带口径与可用运算符）
- GET  /api/presets             内置模板（低估值/质量与成长/趋势突破）
- POST /api/screen              条件选股 {logic, conditions, rank?}
- POST /api/backtest            规则回测（仅纯K线规则；财务条件 422 防未来数据泄漏）
- GET/POST/DELETE /api/rules    选股规则保存（同名版本+1，历史版本保留）
- GET  /api/watchlist           人工池子（watchlist + 报价/候选池快照）
- POST /api/watchlist           加自选 {symbol, name?, note?}
- DELETE /api/watchlist/{sym}   移出自选
- GET  /api/stocks/{symbol}     个股极简详情（K线 + 交易计划 + 人工核查清单）

选股结果仅供研究参考，不构成买卖指令。
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .. import conditions as cd
from .. import hist_analysis as ha
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


class ConditionIn(BaseModel):
    metric: str
    op: str
    value: float | str | None = None
    min: float | None = None
    max: float | None = None
    negate: bool = False


class RankIn(BaseModel):
    metric: str
    top_pct: float = Field(gt=0, le=100)
    order: str = "desc"


class RuleIn(BaseModel):
    name: str = ""
    logic: str = "all"
    conditions: list[ConditionIn]
    rank: RankIn | None = None


class RuleSaveIn(BaseModel):
    name: str = Field(min_length=1)
    rule: RuleIn


class HistIn(BaseModel):
    rule: RuleIn
    asof: str = Field(min_length=8, max_length=10)
    kline_limit: int = Field(default=300, ge=10, le=1000)


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

    # ---- 条件选股（统一条件引擎） ----

    @app.get("/api/metrics")
    def metrics() -> dict:
        return {"metrics": [
            {"key": key, **meta} for key, meta in cd.METRICS.items()
        ]}

    @app.get("/api/presets")
    def presets() -> dict:
        return {"presets": cd.PRESETS}

    @app.post("/api/screen")
    def screen(rule: RuleIn) -> dict:
        spec = rule.model_dump()
        errors = cd.validate_rule(spec)
        if errors:
            raise HTTPException(422, "；".join(errors))
        try:
            return cd.run_screen(spec, cache_dir)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - 数据源故障统一 502
            raise HTTPException(502, f"筛选失败：{exc}") from exc

    @app.post("/api/backtest")
    def backtest(rule: RuleIn) -> dict:
        spec = rule.model_dump()
        errors = cd.validate_rule(spec)
        if errors:
            raise HTTPException(422, "；".join(errors))
        try:
            return cd.run_backtest(spec, cache_dir)
        except ValueError as exc:  # 含财务条件 → 防未来数据泄漏拒绝回测
            raise HTTPException(422, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"回测失败：{exc}") from exc

    @app.post("/api/hist_screen")
    def hist_screen(body: HistIn) -> dict:
        spec = body.rule.model_dump()
        errors = cd.validate_rule(spec)
        if errors:
            raise HTTPException(422, "；".join(errors))
        try:
            return ha.run_hist_screen(spec, body.asof, cache_dir, body.kline_limit)
        except ValueError as exc:  # 泄漏拒绝 / 日期非法
            raise HTTPException(422, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - 数据源故障统一 502
            raise HTTPException(502, f"历史选股分析失败：{exc}") from exc

    # ---- 选股规则保存（版本保留） ----

    @app.get("/api/rules")
    def list_rules() -> dict:
        return {"rules": store.list_rules()}

    @app.post("/api/rules", status_code=201)
    def save_rule(body: RuleSaveIn) -> dict:
        spec = body.rule.model_dump()
        errors = cd.validate_rule(spec)
        if errors:
            raise HTTPException(422, "；".join(errors))
        version = store.save_rule(body.name.strip(), spec)
        return {"name": body.name.strip(), "version": version}

    @app.delete("/api/rules/{name}", status_code=204)
    def delete_rule(name: str) -> None:
        if not store.delete_rule(name):
            raise HTTPException(404, f"规则不存在：{name}")

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
            "plan": cd.trade_plan(quote["price"]),
            "manual_review": cd.manual_review_items({"code": symbol, "name": quote["name"]}),
        }

    return app


__all__ = ["create_app"]
