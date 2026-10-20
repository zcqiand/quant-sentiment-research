# quant-sentiment-research — 仓库工作约定（供 Claude Code）

独立项目（不受 suite 门禁）：**个人选股工作台**——A 股选股，简简单单就一件事：把选股做好。

## 项目定位

机器池子（因子交叉筛选 + 策略回测 + 人工清洗清单）+ 人工池子（自选跟踪）。
核心干货三条：因子交叉运算、策略量化回测、（Phase 3）筹码与资金微观结构。
产品观：「选股软件不是帮你看现在的，而是帮你用历史大数据买概率的」。
所有输出为研究参考，**不构成买卖指令**（免责保留）。

## 铁律

- **TDD**：新模块先写失败测试 → 确认失败 → 实现 → 确认绿 → commit。
- **mock-friendly**：`pip install -e ".[dev]" && pytest -q` 必须在无 Key、无 Docker、无网下全绿。
- **零伪代码**：禁止 `pass` 占位、`TODO` 占位，每段代码必须可运行。
- **无历史包袱**（2026-10-19 用户拍板）：该改就改，没用的删；不做「只增不改」式的博物馆保留。
- **只做选股**（2026-10-20 用户拍板）：舆情/新闻/LLM/金标回测面已整体移除，别再加回来。

## 技术栈

- 后端：Python 3.10+ / FastAPI + uvicorn / pydantic v2 / pandas / SQLite(stdlib)
- 前端：React 18 + Vite 5 + ECharts 5（npm 走 registry.npmmirror.com）
- 数据：AkShare（东财 datacenter + 腾讯 qt + 百度股市通；本机代理若对 eastmoney
  断流，NO_PROXY 加 `.eastmoney.com,gtimg.cn,baidu.com`）

## 端口

- api=8610（`python scripts/run_api.py`；Windows 下脚本已切 SelectorEventLoop——uvicorn
  proactor accept 崩溃指纹）
- web dev=5610（`cd frontend && npm run dev`；vite proxy `/api` → 8610）

## 验收

```bash
pip install -e ".[dev]" && pytest -q     # 后端全量，离线无 Key 全绿
cd frontend && npm run build             # 前端可构建
# live 烟测（需网）：
python scripts/run_api.py               # 起后端 → GET /api/strategy/value 验证真实链路
```

## 目录结构

```text
quant-sentiment-research/
├── src/quant_sentiment/
│   ├── gateway.py        ← K线/股名网关（东财主源+腾讯备援+熔断+TTL缓存，离线fixture）
│   ├── screener.py       ← 全市场候选池构建（财务三表×腾讯报价，行schema v3，6h TTL）
│   ├── strategies.py     ← 选股策略引擎（因子交叉/回测/排除项/交易计划/大盘防守）
│   ├── store.py          ← SQLite 人工池子（watchlist）
│   └── api/app.py        ← FastAPI（health/watchlist/strategy/stocks）
├── frontend/             ← React 双池前端（机器池子/人工池子/个股详情）
├── scripts/run_api.py    ← 后端启动
├── data/                 ← SQLite + 缓存（gitignore）
└── tests/
```

## 编码约定（口径改动须同步此处与前端 hint）

- **模板A 稳健价值**：近3年报 ROE 全>15 · 扣非净利增速>20（东财 F10 主要指标
  KCFJCXSYJLR 同比，缺失回退 yjbb 净利润同比并在 growth_source 标注）· 现金流背书
  （OCF/净利 3年合计>1 且 FCF 代理=经营+投资现金流 3年合计>0）· PE(TTM) 近5年分位<20
  （百度股市通；原用 PB 指标，百度源 PB 返回 None 不可用，2026-10-20 换 PE）。
  四因子硬交叉全过才入池；便宜因子先筛，双因子存活(约100只)全量逐股请求、按天缓存。
- **模板B 动量突破**：收盘>MA20 · MA20 角度>30°（角度=atan(日斜率%×100)，30°≈日涨0.58%）
  · 创60日新高（前60根不含当日）· 量比>2（今日量/5日均量）· 成交额≥3000万（qt f37 万元）。
  候选池按成交额取前 250 只逐股拉 K 线（400 根，信号用尾部、回测用全量）。
- **回测判定**：样本≥20笔 + 夏普>1.0（每笔均值/波动×√12）+ 胜率盈亏比组合
  （>60%需≥1.5 / 50-60%需≥1.8 / 40-50%需≤40%不过；阈值 _payoff_required）。
  模板A 回测口径=站上60日线入场持有240日（估值分位无法历史重建，backtest_note 声明）；
  模板B=四条件成立次日入场持有20日，持仓期不重叠。
- **排除项**：ST 已在池构建剔除；成交额<3000万=不可交易；质押/减持/预亏/监管
  数据面未覆盖 → manual_review_items 固定输出人工核查清单（机器池子≠买入清单）。
- **执行纪律**：trade_plan=30%底仓+30%突破加仓 / -7.5%或破20日线止损（stop_price）/
  +15%减半+10日线移动止盈 / 大盘破20日线只减不加（market_guard，sh000001 按天缓存）。
- **缓存体系**：候选池行 v3 6h（`data/screen_rows_v3_<日期>.json`）；K线 parquet 300s；
  PB分位/扣非增速/大盘防守按天。cache_dir 漏传=静默失效（进程内计时+真发网络请求是指纹），
  test_api 有 `test_strategy_endpoint_uses_app_cache_dir` 防回归。
- **免责声明**：界面与 README 保留免责，不出现买卖指令。
