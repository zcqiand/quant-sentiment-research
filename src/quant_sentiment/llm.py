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
    """Demo LLM 工厂。

    无 API Key 时返回 ``FakeLLM``，让流程在「无 Key、无网络」环境下
    也能跑起来（本书案例仓的默认形态）。

    生产用法：把这里的 ``pass`` 占位换成真实集成——例如把 LangChain 的
    ``ChatModel`` 包一层适配器，使其符合 ``generate(prompt) -> str`` 的接口。
    """
    import os

    if os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY"):
        pass  # 占位——真实集成见书章节
    return FakeLLM(script=['{"label":"中性","confidence":0.3}'])


__all__ = ["FakeLLM", "make_llm"]
