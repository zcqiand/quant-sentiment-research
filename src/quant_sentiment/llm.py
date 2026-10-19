"""LLM 抽象与离线 FakeLLM。

真实节点会接入 LangChain 的 ``ChatModel``；本仓测试用 ``FakeLLM``
按脚本顺序返回固定字符串，从而在无 API Key、无网络环境下驱动
LangGraph 的状态机演进（与 sql-self-healer / saas-cs-agent 仓的
FakeLLM 接口一致）。
"""

from __future__ import annotations


class FakeLLM:
    """按脚本顺序返回的假 LLM。

    每次 ``generate`` 弹出脚本下一项；脚本耗尽后，所有后续调用都返回
    脚本的最后一项（模拟「情绪判定收敛到稳定输出」的终态）。
    """

    def __init__(self, script: list[str]) -> None:
        if not script:
            raise ValueError("FakeLLM.script 不能为空：至少需要一个占位输出")
        self._script: list[str] = list(script)
        self._cursor: int = 0

    def generate(self, prompt: str) -> str:  # noqa: ARG002 - prompt 仅作签名占位
        """返回脚本下一项；耗尽后返回最后一项。"""
        if self._cursor < len(self._script):
            item = self._script[self._cursor]
            self._cursor += 1
            return item
        return self._script[-1]


def make_llm():
    """LLM 工厂：有 Key（LLM_* / MINIMAX_API_KEY / OPENAI / ANTHROPIC）走真实端点，
    无 Key 回退 ``FakeLLM``——保持「无 Key、无网络」可跑的默认形态。
    装配细则见 ``llm_live.make_llm_from_env``。
    """
    from .llm_live import make_llm_from_env

    live = make_llm_from_env()
    if live is not None:
        return live
    return FakeLLM(script=['{"label":"中性","confidence":0.3}'])


__all__ = ["FakeLLM", "make_llm"]
