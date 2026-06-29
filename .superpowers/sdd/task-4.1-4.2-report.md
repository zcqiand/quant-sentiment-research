# Task 4.1 + 4.2 实施报告 — quant-sentiment-research

仓骨架 + AkShare 离线网关 + 情绪打分器。TDD 红→绿，全测试绿。

## 文件清单

| 文件 | 说明 |
| ---- | ---- |
| `.gitignore` | Python/缓存/编辑器忽略；含 `data/cache/` |
| `pyproject.toml` | 主依赖 langchain/langgraph/pydantic/pandas/pyarrow；akshare 走 `[live]` extra；`pythonpath=["src"]` |
| `README.md` | 仓简介 + xr-know-008 卷四案例仓定位 + 合规免责 |
| `CLAUDE.md` | 项目级上下文：技术栈 / akshare 可选 / `pytest -q` 离线 |
| `.env.example` | 无需 API Key 提示 |
| `src/quant_sentiment/__init__.py` | 空 |
| `src/quant_sentiment/gateway.py` | `_OFFLINE` 开关 + `set_offline` + `fetch_kline`/`fetch_news`（离线 fixture / 在线 akshare 双路径，pandas 懒加载） |
| `src/quant_sentiment/llm.py` | `FakeLLM`（与 sql-self-healer / saas-cs-agent 接口一致）+ `make_llm` 工厂 |
| `src/quant_sentiment/sentiment.py` | `SentimentScore`(pydantic v2) + `score_sentiment`，解析失败降级中性(0.3) |
| `tests/__init__.py` | 空 |
| `tests/test_gateway.py` | 离线 kline/news fixture 读取（2 测试） |
| `tests/test_sentiment.py` | JSON 解析 + 坏 JSON 降级（2 测试） |

## TDD 循环

### Task 4.1 — gateway + llm
- **RED**：`tests/test_gateway.py` → `ModuleNotFoundError: No module named 'quant_sentiment.gateway'`（1 error during collection）
- **GREEN**：实现 `gateway.py` + `llm.py` → `2 passed in 0.39s`

### Task 4.2 — sentiment
- **RED**：`tests/test_sentiment.py` → `ModuleNotFoundError: No module named 'quant_sentiment.sentiment'`（1 error during collection）
- **GREEN**：实现 `sentiment.py` → `2 passed in 0.01s`

## 全套结果

```
$ python -m pytest -q
....                                                                     [100%]
4 passed in 0.40s
```

环境：Python 3.10.6 / pandas 2.3.3 / pyarrow 24.0.0 / pydantic 2.8.2 / pytest 9.1.1。
akshare 未安装（验证 `[live]` extra 真为可选），langchain/langgraph 已在环境但本任务代码未 import。

## Commit

```
695c07f feat(quant): 仓骨架 + AkShare 离线网关 + 情绪打分器
```

未 push（按要求）。

## 关注点 / Concerns

1. **`_OFFLINE` 是模块级全局**。`set_offline(True)` 会影响同进程后续所有 gateway 调用。当前测试未显式 reset（`test_*_offline_from_cache` 依赖前置 `set_offline(True)`）。后续若新增在线测试需在每个测试 teardown 里 `set_offline(False)`，或改用 `monkeypatch`/fixture 隔离。已纳入 risk 记忆，后续任务 4.x 接 nodes/graph 时注意。
2. **在线分支未经实跑**（按约束无网络/无 akshare）。`fetch_kline` 的 akshare 列名映射（`收盘→close`）与 `fetch_news` 的 `stock_news_em` 列名映射是基于 akshare 文档的字段假设，真实集成时可能需微调；离线路径已被 fixture 测试覆盖。
3. **`sentiment.py` 的 LLM prompt 要求纯 JSON**，但真实 LLM 常裹代码块/解释；已加 `_strip_code_fence` + `_extract_json_object` 两层容错，未单独写测试（行为已由 fallback 兜底），后续 grounding 任务可补鲁棒性测试。
4. **范围克制**：未建 state/grounding/nodes/graph/router/report/backtest（按要求留给后续任务）。
