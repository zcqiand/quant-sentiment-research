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
│   ├── hist_analysis.py  ← 历史选股表现分析（功能A：point-in-time 筛选 + 20/60/120日收益 vs 基准）
│   ├── fin_snapshot.py   ← 历史财务横截面快照（公告日期门控：yjbb/zcfz 按报告期整表）
│   ├── screener.py       ← 全市场候选池构建（财务三表×腾讯报价，行schema v4，6h TTL）
│   ├── gateway.py        ← K线/股名网关（东财主源+腾讯备援+熔断+TTL缓存，amount透传，离线fixture）
│   ├── store.py          ← SQLite（watchlist 人工池子 + rules 规则版本）
│   └── api/app.py        ← FastAPI（health/metrics/presets/screen/backtest/hist_screen/rules/watchlist/stocks）
├── frontend/             ← React（条件选股 Screener.jsx / 人工池子 ManualPool.jsx / 个股详情）
├── scripts/run_api.py    ← 后端启动
├── data/                 ← SQLite + 缓存（gitignore）
└── tests/
```

## 编码约定（口径改动须同步此处与前端 hint）

- **指标注册表**（31个，五大类）：kind=row（候选池行直取/派生）/ kline（逐股K线计算）/
  slow（逐股慢速：PE分位=百度、扣非增速=F10、上市满2年=K线≥480根推断）。
  每指标带名称·口径·运算符·单位；口径文案直接透出前端（悬停可见）。
  v5 新增：流通市值（qt f44，区别于总市值）、近20日日均成交额（K线amount均值）、
  近20日波动率（日收益样本标准差，未年化）、上市满2年（listed2y 按天缓存）。
- **条件求值纪律**：数据缺失 → 不命中 + 标注「数据缺失」，negate（排除）也不命中
  （缺失不能当「通过排除」）；PE 亏损为负——筛便宜股要配 min=0；股息率被股价下跌推高
  → 口径文案里警示价值陷阱。
- **组合方式**：logic=all/any（AND/OR）+ negate（NOT）+ between（区间）+ rank top_pct（排名，
  缺失值排最后）。
- **回测口径**：仅纯K线规则（rule_backtestable 把关，含财务/估值条件 → ValueError→422，
  理由=未来数据泄漏）；信号同日成立次日收盘入场、持有20日或-8%止损、持仓期不重叠；
  回放起始下标=规则所需最长回看窗口（_signal_start）；判定=样本≥20 + 夏普>1.0 +
  胜率盈亏比组合（>60%需≥1.5 / 50-60%需≥1.8 / 40-50%需≥2.5）。
- **历史选股表现分析（功能A，hist_analysis.py + fin_snapshot.py + POST /api/hist_screen）**：
  选历史日期，K线截至该日做 point-in-time 筛选（前缀K线算指标，_signal_start 回看窗不足
  按缺失），统计入选股持有 20/60/120 交易日收益率 vs 上证基准（同口径次日收盘入场）。
  **财务/估值条件已支持**（2026-10-20）：fin_snapshot 以「报告期×全市场整表」拉东财
  yjbb/zcfz 整表，逐股取 asof 时「已知」的最新报告期拼快照。**已知判定=双门控**：
  公告日期≤asof，或 asof 已过法定披露截止（年报次年4-30/一季报4-30/中报8-31/
  三季报10-31）——东财「最新公告日期」随事后更正**前移**（茅台2024年报现值
  2026-04-17），单靠它历史快照会集体蒸发（2026-10-20 事故，roe_hist 11320→86）。
  另两坑：to_json 必须 date_format="iso"（默认 epoch 把日期写成毫秒整数）；
  read_json 必须 dtype=str（「000333」会被推断成整数 333）。ROE/增速/行业=年报
  口径（镜像 screener 现行）、eps_ttm=年报EPS−上年同期累计+最新累计、bps=最新
  披露期每股净资产、负债率=zcfz 同款双门控；历史 PE/PB=当时收盘÷快照值（notes
  标注口径差异）；流通市值=当前流通股本×当时价格（近似，notes 标注）；listed_2y=
  前缀K线≥480 根（run_hist_screen 自动把 K线窗拉到 gap+480+130）。仍拒绝的指标
  （pe_pct/deduct_growth/股息率/现金流族）由 hist_supportable 列名拒绝
  （ValueError→422）。**年报表拉取失败必须透出 notes**（fetch_hist_fundamentals
  返回 (快照, 警告列表)，run_hist_screen 并入 notes）——静默跳过=瘸腿结果不自知。
  yjbb/zcfz 整表按天缓存 `data/yjbb_<报告期>_<日期>.json`；asof 必须早于今天；
  幸存者偏差/数据缺失/期限不足/no_entry 显式透出 notes。
  完整策略回测（资金分配/调仓/成本）= 第二阶段，未做。
- **两段式补数**：行条件先筛 → 存活者逐股拉K线（成交额前300，并发8）→ 慢指标只补
  「非慢条件已满足、慢条件缺数据」的行 → 终筛。慢指标按天缓存
  （`data/pe_pct_<日期>.json` / `deduct_growth_<日期>.json`）。
- **规则版本**：store.rules 同名保存 version+1、旧行保留、list 出每名最新版；
  删除=删全部版本。
- **缓存体系**：候选池行 v5 6h（`data/screen_rows_v5_<日期>.json`，v5=+流通市值）；
  K线 parquet 300s（**键含 days**：`kline_<sym>_<days>.parquet`——历史验证要 700+ 根，
  与 400 根共用键会被 tail 截短）；慢指标（pe_pct/deduct_growth/listed2y）/大盘防守按天；
  历史财务表按天（`data/yjbb_<报告期>_<日期>.json`/zcfz 同款）。
  **None 也被按天缓存（毒化）——换源后必须删当天缓存文件**。schema 换版必须换缓存文件名。
  cache_dir 漏传=静默失效，test_api 有 cache_dir 传递断言防回归。
- **内置组合**（4个，阈值为公开回测复盘整理非建议）：高ROE+低PE（ROE均值门槛定PE上限，
  剔煤炭/有色/钢铁，公开回测约至2019年超额显著但偏消费）/ 高ROE中的低PB（剔金融地产）/
  小市值+质量过滤（流通市值20-80亿+日均成交额+质量门槛）/ 防御型低波（低估值+低波排序前30%）。
  ST 与北交所在候选池层面全池剔除，组合无需再写条件。行业 contains 关键词已对
  东财「所处行业」实际取值核对（v5 live 2026-10-20）：该列是申万三级名——
  有色=工业金属/能源金属/贵金属/小金属/金属新材料，钢铁=普钢/特钢Ⅱ/冶钢原料，
  银行=银行Ⅱ；不能贪心用「有色」「钢铁」「金属」当关键词（零命中/误伤非金属材料Ⅱ）。
  申万行业表调整时须重新核对。
- **免责声明**：界面与 README 保留免责，不出现买卖指令；模板阈值标注「演示参数非建议」。
