# quant-sentiment-research

A股舆情 + 技术面量化投研（LangGraph，输出研究简报非买卖指令）。

本书 xr-know-008 卷四案例仓之一。仓库随章节迭代：本任务只含仓骨架、
AkShare 离线网关（K 线 / 新闻）、以及基于 LLM 的情绪打分器，后续任务
逐步补齐 state / grounding / nodes / graph / router / report / backtest。

## 合规免责

本仓库产出仅作技术研究与教学示例，不构成任何证券投资建议或买卖指令；
据此操作风险自担，作者不承担任何责任。

## 章节映射（xr-know-008 卷四）
| 章 | 模块 |
|---|---|
| 29 金融数据网关 | gateway.py |
| 30 语义情绪打分 | sentiment.py |
| 31 多波次投研状态机 | graph.py, nodes.py |
| 32 证据链防幻觉 | grounding.py |
| 33 多模型路由与成本 | router.py |
| 34 金标回测评估 | backtest.py, report.py |
