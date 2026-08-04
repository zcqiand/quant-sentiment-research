# A股舆情量化投研

A 股舆情 + 技术面量化投研（LangGraph），输出研究简报非买卖指令。配套《Codex 从入门到项目实践》卷四。

## 快速开始

```bash
pip install -e ".[dev]"    # 安装依赖（dev 包含测试）
pytest -q                   # 跑全部测试（FakeLLM，无需 API Key）
```

可选实时行情：`pip install -e ".[live]"`（需 akshare）。

## 功能特性

- **金融数据网关**：AkShare 离线 fixture，K 线 / 新闻数据
- **语义情绪打分**：基于 LLM 的舆情分析
- **多波次投研状态机**：LangGraph graph 管理研究流程
- **证据链防幻觉**：grounding 模块
- **多模型路由与成本**：router 模块
- **金标回测评估**：backtest / report 模块

## 技术栈

| 技术             | 版本       |
| :--------------- | :--------- |
| Python           | 3.10+      |
| LangGraph        | 1.2.x      |
| pandas / pyarrow | 最新稳定版 |
| pydantic         | v2         |
| 测试框架         | pytest 8.x |

> 依赖版本与 `version-lock.json` 的 `version_lock` 一致，不引入 lock 外的库。

## 配套书籍及章节映射

| 章 | 主题             | 对应源文件                     |
| :- | :--------------- | :----------------------------- |
| 29 | 金融数据网关     | `gateway.py`                 |
| 30 | 语义情绪打分     | `sentiment.py`               |
| 31 | 多波次投研状态机 | `graph.py`, `nodes.py`     |
| 32 | 证据链防幻觉     | `grounding.py`               |
| 33 | 多模型路由与成本 | `router.py`                  |
| 34 | 金标回测评估     | `backtest.py`, `report.py` |

## 快速链接

- [功能规格文档.md](功能规格文档.md) — 功能名称、描述与验收标准
- [CLAUDE.md](CLAUDE.md) — 开发约定与编码规范
