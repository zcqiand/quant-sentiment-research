"""选股策略引擎——机器池子的核心：因子交叉 → 人工清洗 → 回测 → 交易计划 → 大盘防守。

5步SOP落地（逻辑→因子→筛选+清洗→回测→执行风控）：

- **模板A 稳健价值**（value）：近3年报 ROE 全>15 · 扣非净利增速>20（F10 取，
  缺失回退净利润同比并标注）· 现金流因子（OCF/净利 3年合计>1 且 FCF 代理
  = 经营+投资现金流 3年合计>0）· PE(TTM) 近5年分位<20（原用 PB 分位，百度源
  该指标不可用，换 PE）。四因子硬交叉，全过才入池。
- **模板B 动量突破**（momentum）：收盘>MA20 · MA20 角度>30° · 创60日新高 ·
  量比>2。四条件同时成立才入池（腾讯/东财 K线，动量因子纯函数可测）。
- **回测**：入场规则在历史 K 线逐日回放 → 逐笔收益 → 胜率/盈亏比/最大回撤/
  夏普；判定阈值 夏普>1.0 且 胜率盈亏比组合达标（>60%需≥1.5 / 50-60%需≥1.8 /
  40-50%需≥2.5），样本<20 笔不可信直接不过。
- **人工清洗**：流动性（成交额<3000万剔除）+ 数据面覆盖不到的雷（质押>50%/
  减持/监管处罚/预亏预告）固定输出人工核查清单——机器池子出来不是买入清单。
- **交易计划**：30%底仓+30%突破加仓 · -7.5%或破20日线无条件止损 · +15%减半+
  10日线移动止盈 · 大盘跌破20日线只减不加。

口径声明：yjbb 业绩表无扣非增速列，扣非增速走东财 F10 主要指标逐股取（只拉
短名单）；FCF 代理用 xjll「投资性现金流-现金流量净额」（含证券投资，非精确
capex 口径）。选股结果仅供研究参考，不构成买卖指令。
"""

from __future__ import annotations

import json
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path

import httpx
import pandas as pd

from quant_sentiment.gateway import fetch_kline
from quant_sentiment.screener import rows_cached

_F10_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
_DAY_TTL = 12 * 3600
_MOMENTUM_TOP = 250  # 动量策略按成交额取前 N 只做K线扫描
_MIN_TURNOVER_WAN = 3000.0  # 日均成交额门槛（万元）
_PB_PCT_MAX = 20.0
_ROE_MIN = 15.0
_GROWTH_MIN = 20.0

VALUE_NAME = "模板A · 稳健价值"
VALUE_CALIBER = (
    "近3年报ROE全>15% · 扣非净利增速>20%(F10,缺失回退净利润同比) · "
    "OCF/净利3年合计>1 且 FCF代理(经营+投资现金流)3年合计>0 · PE(TTM)近5年分位<20% · "
    "成交额≥3000万 · 四因子硬交叉全过才入池（估值分位原用PB，百度源PB指标不可用，2026-10-20换PE）"
)
MOMENTUM_NAME = "模板B · 动量突破"
MOMENTUM_CALIBER = (
    "收盘>MA20 · MA20角度>30°(日斜率0.58%) · 创60日新高 · 量比>2 · "
    "成交额≥3000万 · 四条件同时成立才入池；主力资金净流入为 Phase 3，先人工核查"
)


# ---- 因子纯函数：现金流 ----

def cashflow_factor(row: dict) -> tuple[bool, dict]:
    """利润的现金流背书：OCF/净利（3年合计）>1 且 FCF 代理 3年合计>0。"""
    ocf_map = row.get("ocf_hist") or row.get("ocf", {})
    periods = list(ocf_map.keys())[:3]
    ocf_total = sum(float(ocf_map.get(p, 0) or 0) for p in periods)
    profit_total = sum(float(row.get("profit_hist", {}).get(p, 0) or 0) for p in periods)
    inv_total = sum(float(row.get("inv_hist", {}).get(p, 0) or 0) for p in periods)
    ratio = ocf_total / profit_total if profit_total > 0 else 0.0
    fcf_total = ocf_total + inv_total
    detail = {
        "ocf_total": round(ocf_total, 2),
        "profit_total": round(profit_total, 2),
        "ocf_over_profit": round(ratio, 2),
        "fcf_total": round(fcf_total, 2),
    }
    return ratio > 1.0 and fcf_total > 0, detail


# ---- 因子纯函数：动量 ----

def sma(values: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    for i in range(n - 1, len(values)):
        out[i] = sum(values[i - n + 1 : i + 1]) / n
    return out


def ma_angle_deg(ma: list[float], lookback: int = 5) -> float:
    """MA 斜率角度：atan(日斜率%×100)。30° ≈ 日涨 0.58%（月线级别陡峭）。"""
    if len(ma) < lookback + 1 or ma[-1] is None or ma[-1] <= 0 or ma[-1 - lookback] in (None, 0):
        return 0.0
    slope_pct = (ma[-1] - ma[-1 - lookback]) / lookback / ma[-1] * 100
    return math.degrees(math.atan(slope_pct))


def momentum_hits(df: pd.DataFrame) -> dict:
    """动量四条件：above_ma20 / angle(度) / high60 / volume_ratio 及各自 hit。"""
    closes = [float(c) for c in df["close"]]
    vols = [float(v) for v in df["volume"]]
    if len(closes) < 61:
        return {"above_ma20": False, "angle": 0.0, "high60": False, "volume_ratio": 0.0,
                "angle_ok": False, "volume_ok": False}
    ma20 = sma(closes, 20)
    angle = ma_angle_deg([m for m in ma20 if m is not None])
    prev_high = max(closes[-61:-1])
    base = vols[-6:-1]
    vol_ratio = vols[-1] / (sum(base) / len(base)) if sum(base) > 0 else 0.0
    return {
        "above_ma20": closes[-1] > ma20[-1],
        "angle": round(angle, 1),
        "high60": closes[-1] >= prev_high,
        "volume_ratio": round(vol_ratio, 2),
        "angle_ok": angle > 30,
        "volume_ok": vol_ratio > 2,
    }


def momentum_ok(hits: dict) -> bool:
    return bool(hits["above_ma20"] and hits["high60"] and hits["angle_ok"] and hits["volume_ok"])


# ---- 回测统计与判定 ----

def stats_from_trades(trades: list[float]) -> dict:
    """逐笔收益 → 胜率/盈亏比/最大回撤/夏普（每笔均值/波动×√12，约月频年化）。"""
    n = len(trades)
    if n == 0:
        return {"n": 0, "win_rate": None, "payoff": None, "max_dd": None, "sharpe": None}
    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]
    win_rate = len(wins) / n
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
    payoff = avg_win / avg_loss if avg_loss > 0 else float("inf")
    equity, peak, max_dd = 1.0, 1.0, 0.0
    for t in trades:
        equity *= 1 + t
        peak = max(peak, equity)
        max_dd = min(max_dd, equity / peak - 1)
    mean = sum(trades) / n
    var = sum((t - mean) ** 2 for t in trades) / n
    sharpe = mean / (var ** 0.5) * math.sqrt(12) if var > 0 else 0.0
    return {
        "n": n,
        "win_rate": round(win_rate, 3),
        "payoff": round(payoff, 2) if payoff != float("inf") else 99.0,
        "max_dd": round(max_dd, 3),
        "sharpe": round(sharpe, 2),
    }


def _payoff_required(win_rate: float) -> float:
    """胜率对应的最小盈亏比：>60%→1.5 / 50-60%→1.8 / 40-50%→2.5 / ≤40% 不过。"""
    if win_rate > 0.6:
        return 1.5
    if win_rate > 0.5:
        return 1.8
    if win_rate > 0.4:
        return 2.5
    return float("inf")


def strategy_verdict(stats: dict) -> dict:
    """回测判定：样本≥20 + 夏普>1.0 + 胜率盈亏比组合达标。"""
    if not stats.get("n") or stats["n"] < 20:
        return {"ok": False, "text": f"样本不足（{stats.get('n', 0)}笔<20），回测不可信"}
    if (stats.get("sharpe") or 0) <= 1.0:
        return {"ok": False, "text": f"夏普{stats['sharpe']}≤1.0，风险调整后收益不够"}
    wr, po = stats["win_rate"], stats["payoff"]
    need = _payoff_required(wr)
    if po is None or po < need:
        return {"ok": False, "text": f"胜率{wr:.0%}需盈亏比≥{need}，实际{po}"}
    return {"ok": True, "text": f"夏普{stats['sharpe']} · 胜率{wr:.0%} · 盈亏比{po}（达标≥{need}）"}


# ---- 回测回放 ----

def backtest_momentum(df: pd.DataFrame, hold: int = 20, stop: float = -0.08) -> list[float]:
    """动量规则逐日回放：信号成立次日收盘入场，持有 hold 日或触发止损离场。"""
    trades: list[float] = []
    n = len(df)
    i = 60
    while i < n - 2:
        if momentum_ok(momentum_hits(df.iloc[: i + 1])):
            entry = float(df["close"].iloc[i + 1])
            exit_j = min(i + 1 + hold, n - 1)
            for j in range(i + 2, exit_j + 1):
                if float(df["close"].iloc[j]) / entry - 1 <= stop:
                    exit_j = j
                    break
            trades.append(float(df["close"].iloc[exit_j]) / entry - 1)
            i = exit_j + 1  # 持仓期内不重叠开仓
        else:
            i += 1
    return trades


def backtest_trend(df: pd.DataFrame, ma_n: int = 60, hold: int = 240, stop: float = -0.08) -> list[float]:
    """价值策略回测口径：站上 MA_n 后次日入场（趋势过滤，估值分位无法历史重建，
    回测不含估值因子——只验证「入场后拿得住/止损纪律」这条执行面）。"""
    closes = [float(c) for c in df["close"]]
    if len(closes) < ma_n + 2:
        return []
    ma = sma(closes, ma_n)
    trades: list[float] = []
    i = ma_n
    while i < len(closes) - 2:
        if ma[i] is not None and closes[i] > ma[i]:
            entry = closes[i + 1]
            exit_j = min(i + 1 + hold, len(closes) - 1)
            for j in range(i + 2, exit_j + 1):
                if closes[j] / entry - 1 <= stop:
                    exit_j = j
                    break
            trades.append(closes[exit_j] / entry - 1)
            i = exit_j + 1
        else:
            i += 1
    return trades


# ---- 排除项与人工清洗 ----

def liquidity_ok(row: dict) -> bool:
    """成交额门槛：当日成交额≥3000万（无数据=不可交易，剔除）。"""
    t = row.get("turnover_wan")
    return isinstance(t, (int, float)) and t >= _MIN_TURNOVER_WAN


def manual_review_items(row: dict) -> list[str]:
    """数据面覆盖不到的雷，固定输出人工核查清单（机器池子≠买入清单）。"""
    return [
        f"{row['code']} {row['name']}：大股东质押比例是否>50%（F10·股权质押人工核）",
        f"{row['code']} {row['name']}：近3月减持计划/业绩预亏预告/监管处罚（公告人工核）",
    ]


# ---- 交易计划与大盘防守 ----

def trade_plan(price: float) -> dict:
    stop_price = round(price * 0.925, 2)
    return {
        "position": "30%底仓 + 30%突破加仓",
        "stop": f"-7.5%或收盘跌破20日线，无条件止损（现价{price:.2f}→{stop_price}）",
        "stop_price": stop_price,
        "take_profit": "+15%减半仓；余仓10日线移动止盈（收盘跌破次日卖出）",
        "market_guard": "大盘跌破20日线：只减不加，空仓等待",
    }


def fetch_market_kline(symbol: str = "sh000001") -> pd.DataFrame:
    """大盘指数日K（腾讯源）。"""
    import akshare as ak

    return ak.stock_zh_index_daily_tx(symbol=symbol)


def market_guard(cache_dir: str | None) -> dict:
    """大盘防守开关：收盘是否站上20日线（按天缓存）。"""
    if cache_dir:
        path = Path(cache_dir)
        path.mkdir(parents=True, exist_ok=True)
        cache_file = path / f"market_guard_{date.today().isoformat()}.json"
        if cache_file.exists():
            return json.loads(cache_file.read_text(encoding="utf-8"))
    try:
        df = fetch_market_kline()
        closes = [float(c) for c in df["close"]]
        ma20 = sma(closes, 20)[-1]
        close = closes[-1]
        above = close > ma20
        out = {
            "close": round(close, 2),
            "ma20": round(ma20, 2),
            "above_ma20": above,
            "text": f"大盘收盘{close:.0f}，{'在20日线上方可正常做多' if above else '跌破20日线——只减不加，空仓等待'}",
        }
    except Exception:  # noqa: BLE001 - 大盘数据不可用不阻塞选股
        out = {"close": None, "ma20": None, "above_ma20": None, "text": "大盘数据不可用，防守开关需人工看盘"}
    if cache_dir and out["above_ma20"] is not None:
        (Path(cache_dir) / f"market_guard_{date.today().isoformat()}.json").write_text(
            json.dumps(out, ensure_ascii=False), encoding="utf-8"
        )
    return out


# ---- 逐股补数（短名单，带按天缓存） ----

def _stock_kline(code: str, days: int, cache_dir: str | None = None) -> pd.DataFrame:
    return fetch_kline(code, days=days, cache_dir=cache_dir)


def fetch_pe_percentile(symbol: str) -> float | None:
    """百度股市通近五年 PE(TTM) 分位（越低越便宜）。

    原用「市净率(PB)」指标，实测百度源该指标返回 None（akshare 解析崩），
    2026-10-20 换 PE(TTM)——同一接口实测可用。
    """
    import akshare as ak

    hist = ak.stock_zh_valuation_baidu(symbol=symbol, indicator="市盈率(TTM)", period="近五年")
    vals = [float(v) for v in hist["value"] if v is not None]
    if len(vals) < 200:
        return None
    current = vals[-1]
    return round(sum(1 for v in vals if v <= current) / len(vals) * 100, 1)


def pe_percentile_cached(codes: list[str], cache_dir: str | None) -> dict[str, float | None]:
    return _daily_cached("pe_pct", codes, cache_dir, _safe_pe)


def deduct_growth_cached(codes: list[str], cache_dir: str | None) -> dict[str, float | None]:
    return _daily_cached("deduct_growth", codes, cache_dir, _safe_deduct)


def _daily_cached(prefix: str, codes: list[str], cache_dir: str | None, fn) -> dict:
    if not cache_dir:
        return {c: fn(c) for c in codes}
    path = Path(cache_dir)
    path.mkdir(parents=True, exist_ok=True)
    cache_file = path / f"{prefix}_{date.today().isoformat()}.json"
    cached: dict = {}
    if cache_file.exists():
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
    for code in codes:
        if code not in cached:
            try:
                cached[code] = fn(code)
            except Exception:  # noqa: BLE001 - 单股失败不废整体
                cached[code] = None
            cache_file.write_text(json.dumps(cached, ensure_ascii=False), encoding="utf-8")
    return cached


def _safe_pe(code: str) -> float | None:
    try:
        return fetch_pe_percentile(code)
    except Exception:  # noqa: BLE001
        return None


def _safe_deduct(code: str) -> float | None:
    try:
        return _fetch_deduct_growth(code)
    except Exception:  # noqa: BLE001
        return None


def _fetch_deduct_growth(symbol: str) -> float | None:
    """东财 F10 主要指标：扣非净利润最新报告期同比增速（%）。"""
    suffix = "SH" if symbol.startswith("6") else "SZ"
    resp = httpx.get(
        _F10_URL,
        params={
            "reportName": "RPT_F10_FINANCE_MAINFINADATA",
            "columns": "SECUCODE,REPORT_DATE,KCFJCXSYJLR",
            "filter": f'(SECUCODE="{symbol}.{suffix}")',
            "pageSize": "500",
            "sortColumns": "REPORT_DATE",
            "sortTypes": "-1",
            "source": "HSF10",
            "client": "PC",
        },
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=10,
    )
    resp.raise_for_status()
    data = (resp.json().get("result") or {}).get("data") or []
    if not data:
        return None
    latest_period = str(data[0]["REPORT_DATE"])[:10].replace("-", "")
    year_ago = f"{int(latest_period[:4]) - 1}{latest_period[4:]}"
    vals = {str(d["REPORT_DATE"])[:10].replace("-", ""): d["KCFJCXSYJLR"] for d in data}
    cur, prev = vals.get(latest_period), vals.get(year_ago)
    if cur is None or prev in (None, 0):
        return None
    return round((float(cur) - float(prev)) / abs(float(prev)) * 100, 1)


# ---- 模板A 因子交叉 ----

def value_factors(row: dict, pe_pct: float | None, deduct_growth: float | None) -> dict:
    """四因子硬交叉：ROE持续 / 扣非增速 / 现金流背书 / 估值分位。"""
    roe_hist = [float(v) for v in list(row.get("roe_hist", {}).values())[:3]]
    roe_ok = len(roe_hist) == 3 and all(v > _ROE_MIN for v in roe_hist)
    if deduct_growth is not None:
        growth_val, source = deduct_growth, "扣非净利润同比（F10）"
    else:
        growth_val, source = row.get("growth"), "净利润同比（扣非缺失回退）"
    growth_ok = growth_val is not None and growth_val > _GROWTH_MIN
    cash_ok, cash_detail = cashflow_factor(row)
    pe_ok = pe_pct is not None and pe_pct < _PB_PCT_MAX
    return {
        "roe_ok": roe_ok,
        "roe_hist": roe_hist,
        "growth_ok": growth_ok,
        "growth_value": growth_val,
        "growth_source": source,
        "cash_ok": cash_ok,
        "cash_detail": cash_detail,
        "pe_ok": pe_ok,
        "pe_pct": pe_pct,
        "passed": sum([roe_ok, growth_ok, cash_ok, pe_ok]),
    }


# ---- 策略门面 ----

STRATEGIES = {
    "value": {"name": VALUE_NAME, "caliber": VALUE_CALIBER},
    "momentum": {"name": MOMENTUM_NAME, "caliber": MOMENTUM_CALIBER},
}


def _aggregate(trades_per_stock: list[list[float]]) -> dict:
    flat = [t for trades in trades_per_stock for t in trades]
    stats = stats_from_trades(flat)
    return {"stats": stats, "verdict": strategy_verdict(stats)}


def run_strategy(key: str, cache_dir: str | None, refresh: bool = False) -> dict:
    """机器池子门面：key = value / momentum。回测摘要+因子命中表+人工清洗清单。"""
    if key not in STRATEGIES:
        raise ValueError(f"未知策略：{key}")
    rows = rows_cached(cache_dir, refresh)
    tradable = [r for r in rows if liquidity_ok(r)]
    guard = market_guard(cache_dir)

    if key == "value":
        items, trades = _run_value(tradable, cache_dir)
        note = (
            "回测口径：站上60日线次日入场，持有240日或-8%止损。估值分位无法历史重建，"
            "回测不含估值因子——只验证入场后的持有与止损纪律；因子交叉本身未经历史交叉验证，"
            "样本股少时结论仅供参考。"
        )
    else:
        items, trades = _run_momentum(tradable, cache_dir)
        note = "回测口径：四条件同日成立次日入场，持有20日或-8%止损，持仓期不重叠开仓。"

    review: list[str] = []
    for it in items:
        review.extend(manual_review_items(it))
    return {
        "key": key,
        "name": STRATEGIES[key]["name"],
        "asof": datetime.now().isoformat(timespec="seconds"),
        "universe": len(rows),
        "tradable": len(tradable),
        "caliber": STRATEGIES[key]["caliber"],
        "count": len(items),
        "items": items,
        "backtest": _aggregate(trades),
        "backtest_note": note,
        "market_guard": guard,
        "manual_review": review,
    }


def _run_value(tradable: list[dict], cache_dir: str | None) -> tuple[list[dict], list[list[float]]]:
    """模板A：便宜因子先筛（ROE/现金流/流动性），存活者全量逐股拉 PB分位+扣非增速
    （双因子存活通常<100只，逐股请求按天缓存，一天只花一次）。"""
    cheap = []
    for r in tradable:
        roe_hist = [float(v) for v in list(r.get("roe_hist", {}).values())[:3]]
        if len(roe_hist) == 3 and all(v > _ROE_MIN for v in roe_hist):
            cash_ok, detail = cashflow_factor(r)
            if cash_ok:
                cheap.append({**r, "cash_detail": detail})
    cheap.sort(key=lambda r: -r["mcap_yi"])  # 大市值先算：流动性好、数据全
    short = cheap

    pe_map = pe_percentile_cached([r["code"] for r in short], cache_dir)
    dg_map = deduct_growth_cached([r["code"] for r in short], cache_dir)

    items: list[dict] = []
    trades: list[list[float]] = []
    for r in short:
        fac = value_factors(r, pe_map.get(r["code"]), dg_map.get(r["code"]))
        if fac["passed"] < 4:
            continue
        item = {
            "code": r["code"], "name": r["name"], "price": r["price"], "pe_ttm": r["pe_ttm"],
            "pb": r["pb"], "mcap_yi": r["mcap_yi"], "div_yield": r["div_yield"],
            "factors": fac, "plan": trade_plan(r["price"]),
        }
        try:
            kline = _stock_kline(r["code"], 400, cache_dir)
            trades.append(backtest_trend(kline))
        except Exception:  # noqa: BLE001 - 单股K线缺不影响榜单
            trades.append([])
        items.append(item)
    items.sort(key=lambda it: (-it["factors"]["passed"], it["factors"]["pe_pct"] if it["factors"]["pe_pct"] is not None else 999))
    return items, trades


def _run_momentum(tradable: list[dict], cache_dir: str | None) -> tuple[list[dict], list[list[float]]]:
    """模板B：成交额前250只逐股拉K线，四条件同时成立才入池。"""
    pool_rows = sorted(tradable, key=lambda r: r["turnover_wan"], reverse=True)[:_MOMENTUM_TOP]

    def _scan(r: dict) -> tuple[dict, list[float]] | None:
        try:
            kline = _stock_kline(r["code"], 400, cache_dir)
        except Exception:  # noqa: BLE001 - 单股K线缺不影响整体
            return None
        hits = momentum_hits(kline)
        if not momentum_ok(hits):
            return None
        item = {
            "code": r["code"], "name": r["name"], "price": r["price"], "pe_ttm": r["pe_ttm"],
            "pb": r["pb"], "mcap_yi": r["mcap_yi"], "turnover_wan": r["turnover_wan"],
            "hits": hits, "plan": trade_plan(r["price"]),
        }
        return item, backtest_momentum(kline)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = [out for out in pool.map(_scan, pool_rows) if out]
    items = [it for it, _ in results]
    items.sort(key=lambda it: -it["hits"]["angle"])
    return items, [tr for _, tr in results]


__all__ = [
    "run_strategy",
    "cashflow_factor",
    "momentum_hits",
    "momentum_ok",
    "ma_angle_deg",
    "sma",
    "stats_from_trades",
    "strategy_verdict",
    "backtest_momentum",
    "backtest_trend",
    "liquidity_ok",
    "manual_review_items",
    "trade_plan",
    "market_guard",
    "value_factors",
    "pe_percentile_cached",
    "deduct_growth_cached",
    "STRATEGIES",
]
