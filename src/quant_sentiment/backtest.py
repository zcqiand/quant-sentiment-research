"""金标回测：用历史 K 线评估「预测涨跌」策略的 precision / recall。

把策略当成二分类器（1=预测涨，0=预测跌），逐根 K 线回放：
用 ``closes[:i]`` 让策略出信号，再跟 ``closes[i]`` vs ``closes[i-1]`` 的真实涨跌对齐。
对「上涨」类计算 precision = TP/(TP+FP)、recall = TP/(TP+FN)。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List

from quant_sentiment.gateway import fetch_kline


@dataclass
class BacktestResult:
    """回测结果：precision / recall（针对「上涨」类） + 样本数。"""

    precision: float
    recall: float
    samples: int


def run_backtest(
    strategy: Callable[[List[float]], int],
    symbol: str,
    cache_dir: str,
    start: str = "",
    end: str = "",
) -> BacktestResult:
    """离线回放 ``strategy`` 在 ``symbol`` 历史 K 线上的表现。

    Args:
        strategy: 输入「截至上一根的收盘价序列」、返回 1(预测涨)/0(预测跌)。
        symbol:   股票代码，用于定位 ``kline_{symbol}.parquet``。
        cache_dir: 离线 fixture 目录。
        start:    保留参数（当前未做日期过滤，留作后续扩展）。
        end:      保留参数。

    Returns:
        :class:`BacktestResult`。
    """
    df = fetch_kline(symbol, days=300, cache_dir=cache_dir)
    closes: List[float] = df["close"].tolist()

    tp = fp = fn = tn = 0
    # 从 i=1 开始：需要 closes[i-1] 做真实涨跌判断，且至少 1 根历史给策略
    for i in range(1, len(closes)):
        signal = strategy(closes[:i])  # 1=预测涨, 0=预测跌
        actual = 1 if closes[i] > closes[i - 1] else 0
        if signal == 1 and actual == 1:
            tp += 1
        elif signal == 1 and actual == 0:
            fp += 1
        elif signal == 0 and actual == 1:
            fn += 1
        else:
            tn += 1

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    return BacktestResult(
        precision=precision,
        recall=recall,
        samples=len(closes) - 1,
    )


__all__ = ["BacktestResult", "run_backtest"]
