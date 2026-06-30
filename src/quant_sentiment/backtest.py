"""金标评估：用人工金标评估 LLM 情绪判定（利好/利空）的 precision / recall。

把「情绪判定函数」当成分类器，逐条新闻回放：用 ``strategy(news_item)``
得到 LLM 判定标签（利好 / 利空 / 中性），再跟 ``gold_labels`` 里的人工
金标对齐。对「利好」类计算 precision = TP/(TP+FP)、recall = TP/(TP+FN)。

注意：本模块评估的是「LLM 情绪判定与人工金标的一致性」，属于研究观察
质量度量，不预测股价涨跌，也不构成任何交易信号。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from quant_sentiment.gateway import fetch_news


@dataclass
class BacktestResult:
    """评估结果：precision / recall（针对「利好」类） + 样本数。"""

    precision: float
    recall: float
    samples: int


def _news_key(news_item: dict) -> str:
    """新闻唯一键：优先 url，缺失时退回 title，与 sentiment 的证据引用对齐。"""
    return news_item.get("url") or news_item.get("title") or ""


def run_backtest(
    strategy: Callable[[dict], str],
    symbol: str,
    cache_dir: str,
    gold_labels: dict[str, str],
) -> BacktestResult:
    """逐条回放 ``strategy`` 在 ``symbol`` 新闻列表上的情绪判定质量。

    Args:
        strategy:     输入一条新闻 dict、返回 LLM 判定标签（利好/利空/中性）。
        symbol:       股票代码，用于定位 ``news_{symbol}.json``。
        cache_dir:    离线 fixture 目录。
        gold_labels:  人工金标，新闻键（url 优先，否则 title）→ 金标标签。

    Returns:
        :class:`BacktestResult`。仅评估在 ``gold_labels`` 中有金标的新闻；
        无金标的新闻跳过，不计入 samples。
    """
    news_list = fetch_news(symbol, cache_dir=cache_dir)

    tp = fp = fn = tn = 0
    for news_item in news_list:
        key = _news_key(news_item)
        if key not in gold_labels:
            continue  # 无人工金标，无法评估，跳过
        signal = strategy(news_item)  # LLM 判定：利好 / 利空 / 中性
        actual = gold_labels[key]     # 人工金标
        signal_pos = signal == "利好"
        actual_pos = actual == "利好"
        if signal_pos and actual_pos:
            tp += 1
        elif signal_pos and not actual_pos:
            fp += 1
        elif not signal_pos and actual_pos:
            fn += 1
        else:
            tn += 1

    samples = tp + fp + fn + tn
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    return BacktestResult(
        precision=precision,
        recall=recall,
        samples=samples,
    )


__all__ = ["BacktestResult", "run_backtest"]
