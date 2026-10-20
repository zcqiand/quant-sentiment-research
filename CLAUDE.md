# quant-sentiment-research — 仓库工作约定（供 Claude Code）

独立项目（不受 suite 门禁）：股票个人工作台——A 股舆情 + 技术面量化投研（LangGraph）。

## 项目定位

**个人自用股票交易工作台**：早上开盘前一键扫描自选股，看舆情+技术面+资金热度合成分排序，
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
│   ├── screener.py       ← 价值选股器（白马价值/高股息防守 TOP20，候选池按天缓存）
│   ├── buy_index.py      ← 买入指数（五步框架：持续性/杠杆/PEG+分位/现金流/行业）
│   ├── workbench.py      ← 工作台编排（快照/合成分/一键扫描）
│   └── api/app.py        ← FastAPI 路由（health/watchlist/scan/stocks/screener/backtest）
├── frontend/             ← React 交易工作台前端（看板/个股详情/金标回测）
├── scripts/run_api.py    ← 后端启动
├── data/                 ← SQLite + 金标文件（gitignore）
└── tests/
```

## 编码约定

- **合成分口径**（改动须同步前端 hint 文案）：composite = 100×(0.45×舆情 + 0.45×技术 + 0.10×热度)；
  标签 ≥60 重点关注 / ≥30 关注 / >-30 观望 / >-60 谨慎 / 其余 回避研究。
- **选股器口径**（改动须同步 screener.CALIBER 常量与前端 hint）：白马价值 =
  0<PE(TTM)<20 + ROE(最近年报加权)>15% + 负债率(最近中报)<50% + 连续3年年报OCF>0，
  叠加**决策层**（buy_index.decision_enrich，榜单=初筛池非买入指令）：三检验
  最新季报净利增速>15% / PE五年分位<40% / 站上60日线且MA60向上 + 四警报
  （周期顶/后视镜/昙花一现/价值陷阱），按检验通过数重排；高股息防守 = 股息率(近三年年报每股股利均值/现价)>5% + 分红不塌
  （最新年度每股股利 ≥ 三年均值的 70%，剔除分红崩塌股/一次性特别分红的均值幻觉）+
  PB<1.5 + PE(TTM)>0 + 连续3年年报OCF>0（最近3个年报），均值股息率降序，
  行带 div_yield_latest（最新年度股息率）供前端双列对照。候选池行
  `data/screen_rows_v2_<日期>.json`（近5年报 ROE/净利/OCF 历史 + 增速）
  按 6h TTL 缓存，东财 datacenter 财务表（push2his 拉黑不受影响）+ 腾讯 qt 批量报价。
- **买入指数口径**（buy_index.py，改动须同步 WEIGHTS 与前端五维展示）：五维各 0~1
  权重归一——持续性.25（3~5年ROE均值+最低值，昙花一现压0.2）/ 杠杆.15（负债率）/
  PEG.15（PE/净利润增速）+ 分位.10（PE近五年分位）/ 现金流.20（OCF/净利润，任一年
  为负归零）/ 行业.15（EM2016 关键词：强周期.2/中性.6/弱周期1.0）。逐股数据
  （百度估值历史 + F10 行业）只拉预筛前 60 只：分位按天缓存、行业 30 天缓存。
- **合规免责**：输出为研究关注度排序，界面与简报保留免责声明，不出现买卖指令。
- **MiniMax-M3 指纹**：响应内联 `<think>…</think>`，llm_live.strip_think 统一剥离；
  `MINIMAX_MODEL` 若是 image-01 之类图像模型不能用于文本。
