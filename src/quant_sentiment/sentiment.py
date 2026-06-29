"""舆情情绪打分器。

输入一条新闻（``{title, content?, url?, ts?}``），用 LLM 判定其对
A股标的的情绪倾向（利好 / 利空 / 中性）并给出置信度。

设计要点：
- 用 pydantic 校验 LLM 返回的 JSON，避免脏数据污染下游。
- 任何解析/校验失败都降级为低置信度的「中性」，绝不抛异常打断流水线
  ——后续 grounding 节点会据此把证据强度下调。
"""

from __future__ import annotations

import json
import re
from typing import Literal, Protocol

from pydantic import BaseModel, ValidationError


class _LLMLike(Protocol):
    """最小 LLM 接口（FakeLLM 与真实 ChatModel 适配器都满足）。"""

    def generate(self, prompt: str) -> str: ...


class SentimentScore(BaseModel):
    """单条新闻的情绪判定结果。

    - ``label``：利好 / 利空 / 中性。
    - ``confidence``：0.0~1.0，模型自报的置信度。
    - ``evidence_ref``：可追溯的证据引用（新闻 url 或标题），供后续证据链使用。
    """

    label: Literal["利好", "利空", "中性"]
    confidence: float
    evidence_ref: str = ""


_FALLBACK = SentimentScore(label="中性", confidence=0.3)


def _build_prompt(news_item: dict) -> str:
    title = news_item.get("title", "")
    content = news_item.get("content", "")
    return (
        "你是 A 股舆情分析助手。请判断下列新闻对相关上市公司的情绪倾向。\n"
        "只返回一个 JSON 对象，不要附带任何解释或 Markdown 代码块。\n"
        '格式：{"label":"利好|利空|中性","confidence":0.0到1.0之间的浮点数}\n\n'
        f"新闻标题：{title}\n"
        f"新闻正文：{content}\n"
    )


def _strip_code_fence(text: str) -> str:
    """去掉 LLM 偶尔包裹的 ```json ... ``` 代码块。"""
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    return m.group(1) if m else text


def _extract_json_object(text: str) -> str:
    """从可能含杂质的输出里抠出第一个 ``{...}``。"""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return match.group(0) if match else text


def score_sentiment(news_item: dict, llm: _LLMLike) -> SentimentScore:
    """对单条新闻打情绪分。

    解析或校验失败时返回 ``SentimentScore(label="中性", confidence=0.3)``。
    """
    prompt = _build_prompt(news_item)
    try:
        raw = llm.generate(prompt)
    except Exception:
        return _FALLBACK.model_copy(update={"evidence_ref": news_item.get("url", news_item.get("title", ""))})

    candidate = _extract_json_object(_strip_code_fence(raw))
    try:
        data = json.loads(candidate)
    except (json.JSONDecodeError, TypeError):
        return _FALLBACK.model_copy(update={"evidence_ref": news_item.get("url", news_item.get("title", ""))})

    try:
        score = SentimentScore.model_validate(data)
    except ValidationError:
        return _FALLBACK

    # 补全证据引用（LLM 通常不主动返回）
    if not score.evidence_ref:
        score = score.model_copy(
            update={"evidence_ref": news_item.get("url", news_item.get("title", ""))}
        )
    return score


__all__ = ["SentimentScore", "score_sentiment"]
