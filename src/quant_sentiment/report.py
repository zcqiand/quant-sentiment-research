"""研究简报生成器：把 QuantState 渲染成人类可读的研究 BRIEF。

**重要合规约束**（见测试 test_report_has_no_buy_sell_signal）：
- 简报仅作舆情与技术面分析，**绝不**出现「买入」「卖出」等指令性词汇；
- 末尾必须附带免责声明。
"""

from __future__ import annotations

from typing import Any

from quant_sentiment.state import Evidence

_DISCLAIMER = "免责声明：本简报仅为舆情与技术面分析，不构成任何投资建议。"


def _render_scores(scores: dict[str, Any]) -> str:
    """把 scores dict 渲染成「维度：取值」列表，空则给占位。"""
    if not scores:
        return "（暂无打分）"
    lines = [f"- {k}：{v}" for k, v in scores.items()]
    return "\n".join(lines)


def _render_evidence(evidence: list[Evidence]) -> str:
    """把证据链渲染成带来源的要点列表。"""
    if not evidence:
        return "（暂无证据）"
    lines: list[str] = []
    for idx, ev in enumerate(evidence, start=1):
        lines.append(
            f"{idx}. {ev.claim}（来源：{ev.source_text}，{ev.source_url}，{ev.ts}）"
        )
    return "\n".join(lines)


def generate_report(state: dict) -> str:
    """根据 QuantState 生成研究简报文本。

    Args:
        state: 至少含 ``symbol``；可选 ``scores``、``evidence``。

    Returns:
        多行纯文本简报，末尾含免责声明；**不含**「买入」「卖出」字样。
    """
    symbol = state.get("symbol", "未知标的")
    scores = state.get("scores", {}) or {}
    evidence = state.get("evidence", []) or []

    parts = [
        f"# 研究简报：{symbol}",
        "",
        "## 多维评分",
        _render_scores(scores),
        "",
        "## 证据链",
        _render_evidence(evidence),
        "",
        "---",
        _DISCLAIMER,
    ]
    return "\n".join(parts)


__all__ = ["generate_report"]
