"""LangGraph 审计节点：多波次证据采集 + 综述汇总。

每个节点都是 ``f(state, ...) -> dict`` 的纯函数：

- **不修改输入 state**，只返回一个 partial dict（与上游 state 浅合并）。
- 通过 ``attach_evidence`` 把证据累加进返回的 ``evidence`` 列表；
  维度评分同步合并到返回 dict 的 ``scores`` 键。
- 全部为**研究只读**：不产出任何买卖建议（buy/sell/加仓/减仓等信号）。

节点清单：

- ``technical_node``   —— 技术面：K 线首尾收盘价对比，判定上行/下行趋势。
- ``fund_flow_node``   —— 资金面：以近端资讯条数作为资金关注度代理。
- ``sentiment_node``   —— 舆情面：逐条新闻 LLM 打分，聚合出整体情绪标签。
- ``summarize_node``   —— 综述：把 symbol + 三维评分 + 证据数拼成报告字符串。
"""

from __future__ import annotations

from typing import Any

from .gateway import fetch_kline, fetch_news
from .grounding import attach_evidence, validate_report
from .sentiment import score_sentiment


def technical_node(state: dict, llm: Any, cache_dir: str | None = None) -> dict:
    """技术面审计。

    拉取最近 30 个交易日 K 线，比较末位 vs 首位收盘价，给出趋势（上行/下行），
    并把该论断作为一条证据入链。``llm`` 参数为接口对齐保留（本节点为确定性计算，
    不调用 LLM）。
    """
    del llm  # 接口对齐：技术面是确定性计算，不消费 LLM
    df = fetch_kline(state["symbol"], days=30, cache_dir=cache_dir)
    closes = df["close"].tolist()
    trend = "上行" if closes[-1] > closes[0] else "下行"
    # 末位日期作为证据时间戳；缺 date 列则留空
    ts = ""
    if "date" in df.columns and len(df) > 0:
        ts = str(df["date"].iloc[-1])
    partial = attach_evidence(
        state,
        claim=f"技术面：近期价格{trend}",
        source_text=f"kline closes: {closes}",
        source_url="internal:kline",
        ts=ts,
    )
    scores = dict(state.get("scores", {}))
    scores["technical"] = trend
    partial["scores"] = scores
    return partial


def fund_flow_node(state: dict, llm: Any, cache_dir: str | None = None) -> dict:
    """资金面审计。

    拉取近端资讯列表，以**资讯条数**作为资金关注度（热度）的简单代理：
    条数越多，说明市场对该标的的资金关注越高。``llm`` 参数为接口对齐保留。
    """
    del llm  # 接口对齐：资金面代理为确定性计算，不消费 LLM
    news = fetch_news(state["symbol"], cache_dir=cache_dir)
    flow_label = f"关注度{len(news)}条"  # 条数即资金热度代理
    partial = attach_evidence(
        state,
        claim=f"资金面：近{len(news)}条资讯",
        source_text=f"news count: {len(news)}",
        source_url="internal:news-count",
        ts=news[0].get("ts", "") if news and news[0].get("ts") else "",
    )
    scores = dict(state.get("scores", {}))
    scores["fund_flow"] = flow_label
    partial["scores"] = scores
    return partial


def sentiment_node(state: dict, llm: Any, cache_dir: str | None = None) -> dict:
    """舆情面审计。

    逐条新闻调 ``score_sentiment`` 打分，聚合出整体情绪标签
    （多/空票数相同时取首条，避免随机性）。整体标签作为一条证据入链。
    """
    news = fetch_news(state["symbol"], cache_dir=cache_dir)
    if not news:
        aggregate_label = "中性"
        source_text = ""
        source_url = "internal:news-empty"
        ts = ""
    else:
        scores_list = [score_sentiment(item, llm) for item in news]
        # 多数表决；并列时取首条标签，保证可复现
        counts: dict[str, int] = {}
        for s in scores_list:
            counts[s.label] = counts.get(s.label, 0) + 1
        top_count = max(counts.values())
        top_labels = [lbl for lbl, c in counts.items() if c == top_count]
        aggregate_label = top_labels[0] if len(top_labels) == 1 else scores_list[0].label
        first = news[0]
        source_text = str(first.get("title", ""))
        source_url = str(first.get("url", "")) or "internal:news"
        ts = str(first.get("ts", "")) if first.get("ts") else ""

    partial = attach_evidence(
        state,
        claim=f"舆情：{aggregate_label}",
        source_text=source_text,
        source_url=source_url,
        ts=ts,
    )
    scores = dict(state.get("scores", {}))
    scores["sentiment"] = aggregate_label
    partial["scores"] = scores
    return partial


def summarize_node(state: dict) -> dict:
    """综述节点：把 symbol + 三维评分 + 证据数拼成一段研究简报。

    报告**只做事实陈述**，不含任何买卖建议。``validate_report`` 在证据已挂载
    的前提下恒为 True——审计节点在前序波次已写入证据链。
    """
    symbol = state.get("symbol", "")
    scores = state.get("scores", {})
    evidence = state.get("evidence", [])
    technical = scores.get("technical", "未知")
    fund_flow = scores.get("fund_flow", "未知")
    sentiment = scores.get("sentiment", "未知")

    report = (
        f"标的 {symbol} 多波次审计简报："
        f"技术面 {technical}；资金面 {fund_flow}；舆情 {sentiment}；"
        f"证据 {len(evidence)} 条。"
        f"（本简报仅陈述研究事实，不构成任何投资建议。）"
    )
    new_state = dict(state)
    new_state["report"] = report
    # 防幻觉门控：审计节点已挂证据，此处恒为 True；保持防御性断言
    assert validate_report(new_state) is True, "综述阶段证据缺失，违反 grounding 门控"
    return {"report": report}


__all__ = [
    "technical_node",
    "fund_flow_node",
    "sentiment_node",
    "summarize_node",
]
