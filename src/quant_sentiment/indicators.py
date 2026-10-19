"""技术指标计算：MA / RSI / MACD / 技术面合成分。

纯函数、无外部依赖（输入 list[float]，输出 list/float），
供工作台快照与前端图表共同使用。
"""

from __future__ import annotations


def ma(closes: list[float], n: int) -> list[float | None]:
    """简单移动平均；窗口未满时对应位置为 None。"""
    result: list[float | None] = [None] * len(closes)
    for i in range(n - 1, len(closes)):
        result[i] = sum(closes[i - n + 1 : i + 1]) / n
    return result


def rsi(closes: list[float], n: int = 14) -> float | None:
    """RSI（简单均值法）：需要 n+1 个点；无下跌时给 100，无波动给 50。"""
    if len(closes) < n + 1:
        return None
    window = closes[-(n + 1) :]
    diffs = [window[i + 1] - window[i] for i in range(n)]
    gains = [max(d, 0.0) for d in diffs]
    losses = [max(-d, 0.0) for d in diffs]
    avg_gain = sum(gains) / n
    avg_loss = sum(losses) / n
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def _ema(values: list[float], n: int) -> list[float]:
    """标准 EMA：种子为首值，alpha = 2/(n+1)。"""
    alpha = 2.0 / (n + 1.0)
    out = [values[0]]
    for x in values[1:]:
        out.append(alpha * x + (1.0 - alpha) * out[-1])
    return out


def macd(closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    """MACD：dif = EMA_fast - EMA_slow；dea = EMA_signal(dif)；hist = dif - dea。

    返回三个与输入等长的列表；数据量不足以同时支撑 fast/slow 时各项为全 None。
    """
    if len(closes) < slow:
        none_list: list[float | None] = [None] * len(closes)
        return {"dif": none_list, "dea": list(none_list), "hist": list(none_list)}
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    dif = [f - s for f, s in zip(ema_fast, ema_slow)]
    dea = _ema(dif, signal)
    hist = [d - e for d, e in zip(dif, dea)]
    return {"dif": dif, "dea": dea, "hist": hist}


def technical_score(closes: list[float]) -> float:
    """技术面合成分，值域 [-1, 1]。

    - 趋势（末位 vs 首位收盘）：±0.4
    - 末位收盘 vs MA20：±0.3（数据不足 MA20 时该项为 0）
    - RSI 修正：>70 过热 -0.3；<30 超卖 +0.3；其余 (50-rsi)/50*0.15
    """
    if not closes:
        return 0.0
    trend = 0.0
    if closes[-1] > closes[0]:
        trend = 0.4
    elif closes[-1] < closes[0]:
        trend = -0.4

    vs_ma = 0.0
    ma20 = ma(closes, 20)[-1] if len(closes) >= 20 else None
    if ma20 is not None:
        vs_ma = 0.3 if closes[-1] > ma20 else -0.3

    rsi_value = rsi(closes)
    rsi_adj = 0.0
    if rsi_value is not None:
        if rsi_value > 70:
            rsi_adj = -0.3
        elif rsi_value < 30:
            rsi_adj = 0.3
        else:
            rsi_adj = (50.0 - rsi_value) / 50.0 * 0.15

    return max(-1.0, min(1.0, trend + vs_ma + rsi_adj))


__all__ = ["ma", "rsi", "macd", "technical_score"]
