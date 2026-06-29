"""Agent 状态机定义：Evidence 证据条目 + QuantState LangGraph 全局状态。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, TypedDict


@dataclass
class Evidence:
    """单条证据：claim(论断) + 出处文本 + 出处 URL + 时间戳。"""

    claim: str
    source_text: str
    source_url: str
    ts: str


class QuantState(TypedDict):
    """LangGraph 全局状态。

    - symbol:      股票代码（如 "600000"）
    - evidence:    已采集的证据链 list[Evidence]
    - scores:      各维度评分 dict（technical / fund_flow / sentiment ...）
    - report:      最终结论文本
    - model_tier:  LLM 档位（"lite" / "pro" ...）
    """

    symbol: str
    evidence: List[Evidence]
    scores: dict
    report: str
    model_tier: str
