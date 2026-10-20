# quant-sentiment-research — 仓库工作约定（供 Claude Code）

独立项目（不受 suite 门禁）：**个人选股工作台**——A 股选股，简简单单就一件事：把选股做好。

## 项目定位

统一条件选股引擎（conditions.py）：所有选股方案（含内置模板）都由「指标 + 条件」
组合而成，不做每方案一套硬编码。三层产品形态：现成方案（3模板一键跑）→
自定义条件（AND/OR/排除/区间/排名）→ 策略回测（纯K线规则历史回放）；
规则保存带版本。产品观：「选股软件不是帮你看现在的，而是帮你用历史大数据买概率的」。
所有输出为研究参考，**不构成买卖指令**（免责保留）。

## 铁律

- **TDD**：新模块先写失败测试 → 确认失败 → 实现 → 确认绿 → commit。
- **mock-friendly**：`pip install -e ".[dev]" && pytest -q` 必须在无 Key、无 Docker、无网下全绿，
  且不真发网络请求（测试里 market_guard/K线/慢指标必须 monkeypatch）。
- **零伪代码**：禁止 `pass` 占位、`TODO` 占位，每段代码必须可运行。
- **无历史包袱**（2026-10-19 用户拍板）：该改就改，没用的删。
- **只做选股**（2026-10-20 用户拍板）：舆情/新闻/LLM 已删别加回来；
  **条件选股是唯一选股形态**（2026-10-20 二次拍板：双模板机器池子太复杂，推倒）。

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
python scripts/run_api.py               # 起后端 → GET /api/presets → POST /api/screen 验证真实链路
```

## 目录结构

```text
quant-sentiment-research/
├── src/quant_sentiment/
│   ├── conditions.py     ← 统一条件引擎（指标注册表/条件求值/组合筛选/K线指标/规则回测/编排）
│   ├── screener.py       ← 全市场候选池构建（财务三表×腾讯报价，行schema v4，6h TTL）
│   ├── gateway.py        ← K线/股名网关（东财主源+腾讯备援+熔断+TTL缓存，amount透传，离线fixture）
│   ├── store.py          ← SQLite（watchlist 人工池子 + rules 规则版本）
│   └── api/app.py        ← FastAPI（health/metrics/presets/screen/backtest/rules/watchlist/stocks）
├── frontend/             ← React（条件选股 Screener.jsx / 人工池子 ManualPool.jsx / 个股详情）
├── scripts/run_api.py    ← 后端启动
├── data/                 ← SQLite + 缓存（gitignore）
└── tests/
```

## 编码约定（口径改动须同步此处与前端 hint）

- **指标注册表**（27个，五大类）：kind=row（候选池行直取/派生）/ kline（逐股K线计算）/
  slow（逐股慢速：PE分位=百度、扣非增速=F10）。每指标带名称·口径·运算符·单位；
  口径文案直接透出前端（悬停可见）。
- **条件求值纪律**：数据缺失 → 不命中 + 标注「数据缺失」，negate（排除）也不命中
  （缺失不能当「通过排除」）；PE 亏损为负——筛便宜股要配 min=0；股息率被股价下跌推高
  → 口径文案里警示价值陷阱。
- **组合方式**：logic=all/any（AND/OR）+ negate（NOT）+ between（区间）+ rank top_pct（排名，
  缺失值排最后）。
- **回测口径**：仅纯K线规则（rule_backtestable 把关，含财务/估值条件 → ValueError→422，
  理由=未来数据泄漏）；信号同日成立次日收盘入场、持有20日或-8%止损、持仓期不重叠；
  回放起始下标=规则所需最长回看窗口（_signal_start）；判定=样本≥20 + 夏普>1.0 +
  胜率盈亏比组合（>60%需≥1.5 / 50-60%需≥1.8 / 40-50%需≥2.5）。
- **两段式补数**：行条件先筛 → 存活者逐股拉K线（成交额前300，并发8）→ 慢指标只补
  「非慢条件已满足、慢条件缺数据」的行 → 终筛。慢指标按天缓存
  （`data/pe_pct_<日期>.json` / `deduct_growth_<日期>.json`）。
- **规则版本**：store.rules 同名保存 version+1、旧行保留、list 出每名最新版；
  删除=删全部版本。
- **缓存体系**：候选池行 v4 6h（`data/screen_rows_v4_<日期>.json`）；K线 parquet 300s；
  慢指标/大盘防守按天。**None 也被按天缓存（毒化）——换源后必须删当天缓存文件**。
  cache_dir 漏传=静默失效，test_api 有 cache_dir 传递断言防回归。
- **免责声明**：界面与 README 保留免责，不出现买卖指令；模板阈值标注「演示参数非建议」。
