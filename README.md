# 股票个人工作台（quant-sentiment-research）

A 股舆情 + 技术面量化投研工作台。**早上开盘前一键扫描自选股**：
舆情 × 技术面 × 资金热度合成分排序 → 点进个股看 K 线/新闻情绪/证据链 →
金标回测验证情绪判定质量。输出研究关注度排序，**非买卖指令**。

## 快速开始

```bash
# 后端
pip install -e ".[dev,live]"     # dev=测试，live=akshare 实时行情
pytest -q                        # 全量测试（FakeLLM，无 Key 无网全绿）
python scripts/run_api.py        # 起 API，http://127.0.0.1:8610

# 前端（新终端）
cd frontend
npm install                      # 走 npmmirror
npm run dev                      # http://localhost:5610
```

LLM：默认读 `MINIMAX_API_KEY`（本机 `.claude/settings.local.json` 注入），
模型 MiniMax-M3；无 Key 回退 FakeLLM（流程可跑，打分无意义）。
配置细则见 [.env.example](.env.example)。

## 用法（盘前流程）

1. **加自选**：看板顶部输入 6 位代码（如 600000）
2. **⚡ 一键盘前扫描**：逐只拉实时 K 线 + 新闻，MiniMax-M3 逐条舆情打分（首次较慢，
   新闻打分有 SQLite 缓存，次日只对新新闻花 token）
3. **按合成分排序**：composite = 100×(0.45 舆情 + 0.45 技术 + 0.10 热度)，±100；
   标签：重点关注 / 关注 / 观望 / 谨慎 / 回避研究
4. **点进个股**：K 线（MA5/20+成交量）、技术指标、新闻情绪列表、证据链与研究简报
5. **金标回测**（可选）：`data/gold_<代码>.json` 放人工金标
   `{"新闻url或标题": "利好|利空|中性"}`，回测页看 LLM 判定的 precision/recall
6. **选股器**：白马价值 TOP20（PE<20 + ROE>15% + 负债率<50% + 连续3年OCF为正）与
   高股息防守 TOP20（股息率>5% + PB<1.5 + 盈利为正 + 连续3年OCF为正），
   一键加自选 → 进盘前流程；候选池按天缓存，点「强制刷新」重拉
7. **买入指数 TOP20**：五步判断高 ROE 股——持续性（3~5年ROE稳不稳）/ 杠杆驱动
   （负债率泡没泡出来）/ 估值（PEG + PE近五年分位）/ 现金流（OCF vs 净利润）/
   行业属性（强周期防"周期顶陷阱"），五维分项可见，逐股解释打分理由

## 功能特性

- **金融数据网关**：AkShare 实时 + 离线 fixture 双态，标准 OHLCV 输出
- **语义情绪打分**：LLM 逐条判定利好/利空/中性，SQLite 缓存防重复消费
- **合成分排序**：舆情 45% + 技术面 45%（趋势/MA20/RSI）+ 资金热度 10%
- **证据链防幻觉**：每条结论带来源，grounding 门控
- **多模型路由**：LLM 装配链 `LLM_*` → `MINIMAX_*` → `OPENAI/ANTHROPIC` → FakeLLM
- **金标回测**：情绪判定当分类器，precision/recall 评估
- **价值选股器**：白马价值 / 高股息防守 / 买入指数三策略 TOP20，东财财务报表
  × 腾讯批量行情 × 百度估值历史，候选池按天缓存（push2his 拉黑期不受影响）

## 技术栈

| 层 | 技术 |
| :--- | :--- |
| 后端 | Python 3.10+ · LangGraph · FastAPI · pydantic v2 · pandas · SQLite |
| 前端 | React 18 · Vite 5 · ECharts 5 |
| LLM | MiniMax-M3（OpenAI 兼容），`<think>` 思维链自动剥离 |
| 数据 | AkShare 实时 / 离线 fixture |

## 快速链接

- [功能规格文档.md](功能规格文档.md) — 功能名称、描述与验收标准
- [CLAUDE.md](CLAUDE.md) — 开发约定与编码规范

## 免责声明

本工具仅为个人研究与教学示例，所有输出（含合成分与标签）不构成任何投资建议；
买卖决策请独立判断，风险自负。
