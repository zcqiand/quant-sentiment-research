"""LangGraph 状态机装配：START → 技术 → 资金 → 舆情 → 综述 → END。

``build_graph`` 把 ``llm`` / ``cache_dir`` 通过 ``functools.partial``
绑定到各审计节点（综述节点两者都不需要），串成一条线性的多波次审计流水线。
"""

from __future__ import annotations

import functools
from typing import Any

from langgraph.graph import END, START, StateGraph

from .nodes import fund_flow_node, sentiment_node, summarize_node, technical_node
from .state import QuantState

# 节点在图里的名字（与 add_node 的 key 保持一致）
_TECHNICAL = "technical"
_FUND_FLOW = "fund_flow"
_SENTIMENT = "sentiment"
_SUMMARIZE = "summarize"


def build_graph(llm: Any, cache_dir: str | None = None):
    """构造并编译多波次审计状态机。

    Parameters
    ----------
    llm
        满足 ``generate(prompt) -> str`` 接口的 LLM（FakeLLM 或真实适配器）。
        技术面/资金面节点为确定性计算不消费它；舆情节点逐条调用。
    cache_dir
        离线 fixture 目录；传给网关定位 parquet/json。生产可留空。

    Returns
    -------
    CompiledGraph
        可 ``invoke(initial_state)`` 的已编译图。
    """
    graph = StateGraph(QuantState)

    # partial 绑定依赖：审计节点拿到 (state,) 即可；综述节点无需任何依赖
    graph.add_node(_TECHNICAL, functools.partial(technical_node, llm=llm, cache_dir=cache_dir))
    graph.add_node(_FUND_FLOW, functools.partial(fund_flow_node, llm=llm, cache_dir=cache_dir))
    graph.add_node(_SENTIMENT, functools.partial(sentiment_node, llm=llm, cache_dir=cache_dir))
    graph.add_node(_SUMMARIZE, summarize_node)

    graph.add_edge(START, _TECHNICAL)
    graph.add_edge(_TECHNICAL, _FUND_FLOW)
    graph.add_edge(_FUND_FLOW, _SENTIMENT)
    graph.add_edge(_SENTIMENT, _SUMMARIZE)
    graph.add_edge(_SUMMARIZE, END)

    return graph.compile()


__all__ = ["build_graph"]
