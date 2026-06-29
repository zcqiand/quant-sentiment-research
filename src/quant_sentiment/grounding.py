"""证据链 grounding：防幻觉门控。

- attach_evidence:   向 state 追加一条 Evidence（不可变，返回 partial state）
- validate_report:   防幻觉门控——报告非空但零证据 → 拒绝
"""

from __future__ import annotations

from .state import Evidence


def attach_evidence(
    state: dict,
    claim: str,
    source_text: str,
    source_url: str,
    ts: str,
) -> dict:
    """构建 Evidence 并返回 partial state（仅含 evidence 键），不修改输入 state。

    用法（LangGraph node 中）::

        return attach_evidence(state, claim, src, url, ts)

    返回的 dict 会与上游 state 做浅合并，从而把新证据累加到 state["evidence"]。
    """
    ev = Evidence(
        claim=claim,
        source_text=source_text,
        source_url=source_url,
        ts=ts,
    )
    return {"evidence": state.get("evidence", []) + [ev]}


def validate_report(state: dict) -> bool:
    """防幻觉门控。

    - 报告非空（有结论）但证据数为 0 → 拒绝（False）
    - 报告为空，或报告背后有 ≥1 条证据 → 通过（True）
    """
    if state.get("report") and len(state.get("evidence", [])) == 0:
        return False
    return True
