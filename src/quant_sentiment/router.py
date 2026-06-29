"""多模型路由：按任务复杂度选 LLM 档位（lite / flagship / mock）。

- simple  → lite       （轻量任务，便宜快）
- hard    → flagship   （复杂推理，强模型）
- 其它（unknown / 无 Key 等）→ mock（FakeLLM，零成本占位）

这是「成本 vs 能力」的折中：不是所有子任务都需要旗舰模型。
"""

from __future__ import annotations


def route_model(task_complexity: str) -> str:
    """按任务复杂度返回模型档位。

    Args:
        task_complexity: ``"simple"`` / ``"hard"`` / 其它（含 ``"unknown"``）。

    Returns:
        ``"lite"`` / ``"flagship"`` / ``"mock"``。
    """
    if task_complexity == "simple":
        return "lite"
    if task_complexity == "hard":
        return "flagship"
    # unknown / 无 Key / 其它一律降级到 mock，避免误用昂贵模型
    return "mock"


__all__ = ["route_model"]
