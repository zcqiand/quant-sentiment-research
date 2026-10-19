"""工作台 API 路由：health / watchlist / scan / stock detail / backtest。

端口约定：api=8610（配套前端 dev=5610，vite proxy /api → 127.0.0.1:8610）。
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ..gateway import _offline_active, fetch_kline, fetch_news
from ..backtest import run_backtest
from ..llm import FakeLLM
from ..llm_live import AnthropicLLM, OpenAICompatLLM
from ..workbench import Workbench, _dedupe_news

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


def _llm_descriptor(llm) -> dict:
    if isinstance(llm, FakeLLM):
        return {"mode": "fake", "model": None}
    if isinstance(llm, OpenAICompatLLM):
        return {"mode": "openai-compat", "model": llm.model}
    if isinstance(llm, AnthropicLLM):
        return {"mode": "anthropic", "model": llm.model}
    return {"mode": type(llm).__name__, "model": None}


def _default_workbench() -> Workbench:
    db_path = os.getenv("WORKBENCH_DB_PATH") or str(_DATA_DIR / "workbench.db")
    return Workbench(db_path=db_path)


@lru_cache(maxsize=1)
def _gold_dir() -> str:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    return str(_DATA_DIR)


def create_app(workbench: Workbench | None = None) -> FastAPI:
    wb = workbench if workbench is not None else _default_workbench()
    app = FastAPI(title="quant-sentiment-workbench", version="2.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_WEB_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health():
        return {
            "ok": True,
            "llm": _llm_descriptor(wb.llm),
            "data": {"online": not _offline_active()},
            "version": app.version,
        }

    @app.get("/api/watchlist")
    def get_watchlist():
        return wb.list_watchlist()

    @app.post("/api/watchlist", status_code=201)
    def add_watchlist(item: WatchlistItem):
        if not _SYMBOL_RE.match(item.symbol):
            raise HTTPException(status_code=400, detail="股票代码须为 6 位数字")
        wb.add_stock(item.symbol, item.name)
        return {"symbol": item.symbol, "name": item.name}

    @app.delete("/api/watchlist/{symbol}", status_code=204)
    def remove_watchlist(symbol: str):
        if not wb.remove_stock(symbol):
            raise HTTPException(status_code=404, detail=f"{symbol} 不在自选列表")

    @app.post("/api/scan")
    def scan():
        return wb.scan()

    @app.get("/api/scan/latest")
    def latest_scan():
        scan_row = wb.store.latest_scan()
        if scan_row is None:
            raise HTTPException(status_code=404, detail="还没有扫描记录，先 POST /api/scan")
        return {"ts": scan_row["ts"], **scan_row["payload"]}

    @app.get("/api/stocks/{symbol}")
    def stock_detail(symbol: str):
        kline = None
        news = []
        fetch_errors = []
        for fetcher in (
            lambda: fetch_kline(symbol, days=60, cache_dir=wb.cache_dir),
            lambda: _dedupe_news(fetch_news(symbol, cache_dir=wb.cache_dir, query=wb.news_query(symbol))),
        ):
            try:
                result = fetcher()
            except Exception as exc:  # noqa: BLE001 - 单源降级
                fetch_errors.append(str(exc))
                continue
            if isinstance(result, list):
                news = result
            else:
                kline = result
        if kline is None and not news:
            raise HTTPException(status_code=502, detail=f"行情数据不可用：{'；'.join(fetch_errors)}")
        closes = [float(x) for x in kline["close"].tolist()] if kline is not None else []
        from ..indicators import ma, macd, rsi, technical_score

        scored = [wb.score_news_cached(item, symbol) for item in news]
        news_out = [
            {
                "title": item.get("title", ""),
                "content": item.get("content", ""),
                "url": item.get("url", ""),
                "ts": item.get("ts", ""),
                "label": s["label"],
                "confidence": s["confidence"],
            }
            for item, s in zip(news, scored)
        ]
        indicators = None
        if closes:
            macd_full = macd(closes)
            indicators = {
                "ma5": ma(closes, 5)[-1],
                "ma20": ma(closes, 20)[-1],
                "rsi": rsi(closes),
                "macd": {
                    "dif": macd_full["dif"][-1],
                    "dea": macd_full["dea"][-1],
                    "hist": macd_full["hist"][-1],
                },
                "technical_score": technical_score(closes),
            }
        return {
            "symbol": symbol,
            "name": next((r["name"] for r in wb.list_watchlist() if r["symbol"] == symbol), ""),
            "kline": kline.to_dict(orient="records") if kline is not None else None,
            "indicators": indicators,
            "news": news_out,
            "latest": wb.store.latest_run_per_symbol().get(symbol),
        }

    @app.post("/api/stocks/{symbol}/research")
    def stock_research(symbol: str):
        try:
            return wb.research_snapshot(symbol)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"研究快照失败：{exc}") from exc

    @app.get("/api/backtest/{symbol}")
    def backtest(symbol: str):
        gold_dir = wb.cache_dir or _gold_dir()
        gold_path = Path(gold_dir) / f"gold_{symbol}.json"
        if not gold_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"缺少金标文件 {gold_path}（格式：{{新闻url或标题: 利好|利空|中性}}）",
            )
        gold_labels = json.loads(gold_path.read_text(encoding="utf-8"))

        def strategy(item: dict) -> str:
            return wb.score_news_cached(item, symbol)["label"]

        result = run_backtest(strategy, symbol, wb.cache_dir, gold_labels)
        return {
            "symbol": symbol,
            "precision": result.precision,
            "recall": result.recall,
            "samples": result.samples,
            "gold_count": len(gold_labels),
        }

    return app


__all__ = ["create_app"]
