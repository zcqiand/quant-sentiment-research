"""个人盘前工作台编排层：自选股 → 一键扫描 → 合成分排序 → 证据链快照。

合成口径（值域均归一到 [-1, 1]，heat 为 [0, 1]）：

- technical：趋势 ±0.4 + 收盘 vs MA20 ±0.3 + RSI 修正 ±0.3（见 indicators.technical_score）
- sentiment：(利好票数 - 利空票数) / max(1, 总票数)
- heat：min(1, 资讯条数 / 10)（资金关注度代理，复用 fund_flow_node 思路）
- composite = 100 × (0.45×sentiment + 0.45×technical + 0.10×heat)

合规：输出为研究关注度排序（重点关注/关注/观望/谨慎/回避研究），
不产出任何买卖指令；简报沿用 report.generate_report 的免责声明。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .gateway import fetch_kline, fetch_news
from .grounding import attach_evidence
from .indicators import ma, rsi, technical_score
from .llm import FakeLLM, make_llm
from .llm_live import make_llm_from_env
from .report import generate_report
from .sentiment import score_sentiment
from .store import WorkbenchStore


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _news_key(item: dict) -> str:
    """新闻唯一键：url 优先，缺失退回 title（与 backtest._news_key 口径一致）。"""
    return item.get("url") or item.get("title") or ""


def composite_label(score: float) -> str:
    """合成分 → 研究关注度标签（非买卖指令）。"""
    if score >= 60:
        return "重点关注"
    if score >= 30:
        return "关注"
    if score > -30:
        return "观望"
    if score > -60:
        return "谨慎"
    return "回避研究"


class Workbench:
    """工作台门面：watchlist 管理、舆情缓存、研究快照与一键扫描。"""

    def __init__(self, db_path: str, cache_dir: str | None = None, llm: Any = None) -> None:
        self.store = WorkbenchStore(db_path)
        self.cache_dir = cache_dir
        if llm is None:
            live = make_llm_from_env()
            llm = live if live is not None else make_llm()
        self.llm = llm

    # ---- 自选股 ----

    def add_stock(self, symbol: str, name: str = "") -> None:
        self.store.upsert_watchlist(symbol, name)

    def remove_stock(self, symbol: str) -> bool:
        return self.store.remove_watchlist(symbol)

    def list_watchlist(self) -> list[dict]:
        return self.store.list_watchlist()

    # ---- 舆情（带缓存）----

    def score_news_cached(self, item: dict, symbol: str) -> dict:
        """逐条新闻 LLM 打分，按新闻键落库缓存——同一新闻只花一次 token。"""
        key = _news_key(item)
        hit = self.store.get_news_score(key)
        if hit is not None:
            return {"label": hit["label"], "confidence": hit["confidence"]}
        score = score_sentiment(item, self.llm)
        self.store.put_news_score(key, symbol, score.label, score.confidence)
        return {"label": score.label, "confidence": score.confidence}

    # ---- 研究快照 ----

    def research_snapshot(self, symbol: str) -> dict:
        """单只标的完整研究快照：OHLCV + 指标 + 舆情投票 + 证据链 + 简报。"""
        kline = fetch_kline(symbol, days=60, cache_dir=self.cache_dir)
        news = fetch_news(symbol, cache_dir=self.cache_dir)
        closes = [float(x) for x in kline["close"].tolist()]
        price = closes[-1]
        prev = closes[-2] if len(closes) > 1 else price
        change_pct = (price / prev - 1.0) * 100.0 if prev else 0.0

        ma5 = ma(closes, 5)[-1]
        ma20 = ma(closes, 20)[-1]
        rsi14 = rsi(closes)
        tech = technical_score(closes)
        trend = "上行" if price > closes[0] else ("下行" if price < closes[0] else "横盘")

        scored_news: list[dict] = []
        for item in news:
            s = self.score_news_cached(item, symbol)
            scored_news.append(
                {
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "ts": item.get("ts", ""),
                    "label": s["label"],
                    "confidence": s["confidence"],
                }
            )
        bull = sum(1 for n in scored_news if n["label"] == "利好")
        bear = sum(1 for n in scored_news if n["label"] == "利空")
        neutral = sum(1 for n in scored_news if n["label"] == "中性")
        total = len(scored_news)
        sentiment = (bull - bear) / max(1, total)
        heat = min(1.0, total / 10.0)
        composite = round(100.0 * (0.45 * sentiment + 0.45 * tech + 0.10 * heat))

        ts = _now()
        last_date = str(kline["date"].iloc[-1]) if len(kline) else ""
        state: dict = {"symbol": symbol, "evidence": [], "scores": {}}
        state = {**state, **attach_evidence(
            state,
            claim=f"技术面：近期价格{trend}",
            source_text=f"close={price}, ma5={ma5}, ma20={ma20}, rsi={rsi14}",
            source_url="internal:kline",
            ts=last_date,
        )}
        state = {**state, **attach_evidence(
            state,
            claim=f"资金面：近{total}条资讯",
            source_text=f"news count: {total}",
            source_url="internal:news-count",
            ts=scored_news[0]["ts"] if scored_news else "",
        )}
        if scored_news:
            state = {**state, **attach_evidence(
                state,
                claim=f"舆情：利好{bull}/利空{bear}/中性{neutral}",
                source_text=scored_news[0]["title"],
                source_url=scored_news[0]["url"] or "internal:news",
                ts=scored_news[0]["ts"],
            )}
        state["scores"] = {
            "technical": f"{trend}（{tech:.2f}）",
            "fund_flow": f"关注度{total}条",
            "sentiment": f"利好{bull}/利空{bear}/中性{neutral}",
        }
        report = generate_report(state)

        snapshot = {
            "symbol": symbol,
            "name": next(
                (r["name"] for r in self.list_watchlist() if r["symbol"] == symbol), ""
            ),
            "ts": ts,
            "price": price,
            "change_pct": round(change_pct, 2),
            "technical": {"trend": trend, "ma5": ma5, "ma20": ma20, "rsi": rsi14, "score": round(tech, 3)},
            "sentiment": {"score": round(sentiment, 3), "bull": bull, "bear": bear, "neutral": neutral, "total": total},
            "heat": round(heat, 2),
            "composite": composite,
            "composite_label": composite_label(composite),
            "report": report,
            "evidence": [
                {"claim": e.claim, "source_text": e.source_text, "source_url": e.source_url, "ts": e.ts}
                for e in state["evidence"]
            ],
            "news": scored_news,
        }
        self.store.save_run(symbol, ts, float(composite), snapshot)
        return snapshot

    # ---- 一键扫描 ----

    def scan(self) -> dict:
        """对全部自选股跑研究快照；单只失败不中断，错误进 errors。"""
        results: list[dict] = []
        errors: list[dict] = []
        for row in self.list_watchlist():
            try:
                results.append(self.research_snapshot(row["symbol"]))
            except Exception as exc:  # noqa: BLE001 - 单只失败隔离，错误上抛给前端
                errors.append({"symbol": row["symbol"], "error": str(exc)})
        payload = {"results": results, "errors": errors}
        ts = _now()
        self.store.save_scan(ts, payload)
        return {"ts": ts, **payload}

    def latest_snapshots(self) -> dict[str, dict]:
        """各标的最近一次快照（来自落库，不发任何请求）。"""
        return self.store.latest_run_per_symbol()


__all__ = ["Workbench", "composite_label", "FakeLLM"]
