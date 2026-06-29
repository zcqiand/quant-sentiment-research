# quant-sentiment-research — 项目级上下文

A股舆情 + 技术面量化投研 LangGraph Agent（本书 xr-know-008 卷四案例仓之一）。

- 技术栈：Python 3.10+ / LangGraph 1.2.x / pandas / pyarrow / pydantic v2
- 真实行情数据来自 `akshare`（可选依赖，`pip install -e ".[live]"`）；测试无需 akshare、无需联网
- 测试用 `FakeLLM`，无需任何 API Key；运行：`pytest -q`（离线 fixture）
