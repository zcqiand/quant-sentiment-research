# quant-sentiment-research — 仓库工作约定（供 Claude Code）

独立项目（不受 suite 门禁）：A 股个人盘前工作台——舆情 + 技术面量化投研（LangGraph）。

## 项目定位

**个人自用盘前工作台**：早上开盘前一键扫描自选股，看舆情+技术面+资金热度合成分排序，
点进个股看 K 线/新闻情绪/证据链，用金标回测验证情绪判定质量。输出研究关注度排序，
**不产出买卖指令**（合规免责保留）。

## 铁律

- **TDD**：新模块先写失败测试 → 确认失败 → 实现 → 确认绿 → commit。
- **mock-friendly**：`pip install -e ".[dev]" && pytest -q` 必须在无 Key、无 Docker、无网下全绿。
- **零伪代码**：禁止 `pass` 占位、`TODO` 占位，每段代码必须可运行。
- **无历史包袱**（2026-10-19 用户拍板）：该改就改，没用的删；不做「只增不改」式的博物馆保留。
- **舆情打分必走缓存**：新闻打分按（url|title）键落 SQLite，同一新闻只花一次 token。

## 技术栈

- 后端：Python 3.10+ / LangGraph 1.2+ / FastAPI + uvicorn / pydantic v2 / pandas / SQLite(stdlib)
- 前端：React 18 + Vite 5 + ECharts 5（npm 走 registry.npmmirror.com）
- LLM：MiniMax-M3（OpenAI 兼容端点 `api.minimaxi.com/v1`；Key 从 `MINIMAX_API_KEY` env 读，
  由本机 `.claude/settings.local.json` 注入）；无 Key 回退 FakeLLM
- 数据：AkShare 实时（eastmoney 直连；本机代理若对 eastmoney 断流，NO_PROXY 加 `.eastmoney.com`）

## 端口

- api=8610（`python scripts/run_api.py`；Windows 下脚本已切 SelectorEventLoop——uvicorn
  proactor accept 崩溃指纹）
- web dev=5610（`cd frontend && npm run dev`；vite proxy `/api` → 8610）

## 验收

```bash
pip install -e ".[dev]" && pytest -q     # 后端全量，离线无 Key 全绿
cd frontend && npm run build             # 前端可构建
# live 烟测（可选，需 Key+网）：
python scripts/run_api.py               # 起后端 → 前端/ curl POST /api/scan 验证真实链路
```

## 目录结构

```text
quant-sentiment-research/
├── src/quant_sentiment/
│   ├── gateway.py        ← 金融数据网关（标准 OHLCV + 新闻，离线/在线双态）
│   ├── indicators.py     ← MA/RSI/MACD/技术面合成分（纯函数）
│   ├── sentiment.py      ← 语义情绪打分（LLM）
│   ├── graph.py/nodes.py ← LangGraph 多波次审计状态机（库路径）
│   ├── grounding.py      ← 证据链防幻觉
│   ├── router.py         ← 模型路由
│   ├── backtest.py       ← 金标回测（precision/recall）
│   ├── report.py         ← 研究简报渲染
│   ├── llm.py/llm_live.py← LLM 工厂（env 装配 + FakeLLM 回退 + <think> 剥离）
│   ├── store.py          ← SQLite（watchlist/打分缓存/快照/扫描历史）
│   ├── workbench.py      ← 工作台编排（快照/合成分/一键扫描）
│   └── api/app.py        ← FastAPI 路由（health/watchlist/scan/stocks/backtest）
├── frontend/             ← React 盘前工作台（看板/个股详情/金标回测）
├── scripts/run_api.py    ← 后端启动
├── data/                 ← SQLite + 金标文件（gitignore）
└── tests/
```

## 编码约定

- **合成分口径**（改动须同步前端 hint 文案）：composite = 100×(0.45×舆情 + 0.45×技术 + 0.10×热度)；
  标签 ≥60 重点关注 / ≥30 关注 / >-30 观望 / >-60 谨慎 / 其余 回避研究。
- **合规免责**：输出为研究关注度排序，界面与简报保留免责声明，不出现买卖指令。
- **MiniMax-M3 指纹**：响应内联 `<think>…</think>`，llm_live.strip_think 统一剥离；
  `MINIMAX_MODEL` 若是 image-01 之类图像模型不能用于文本。
