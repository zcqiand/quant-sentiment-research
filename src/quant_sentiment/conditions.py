"""统一条件选股引擎——所有选股方案（含内置模板）都由「指标 + 条件」组合而成。

三层产品形态的底座：
- **现成方案**：PRESETS 四组合（高ROE+低PE / 高ROE中的低PB / 小市值+质量过滤 /
  防御型低波），阈值整理自公开回测复盘、不是建议；
- **自定义条件**：指标注册表 METRICS（31 个，五大类，每个带名称·口径·运算符·来源类型）
  + AND/OR（logic）+ NOT（negate 排除）+ 区间（between）+ 排名（rank top N%）；
- **策略回测**：纯 K线规则在历史 K 线上逐日回放（信号次日收盘入场、持有 N 日或止损）；
  含财务/估值条件的规则**拒绝回测**——历史横截面快照未实现，重放会引入未来数据泄漏。

数据纪律：缺失指标一律「不命中且标注数据缺失」，绝不当 0/正常值；slow 指标
（PE分位/扣非增速/上市满2年）先粗筛再逐股补数（两段式），按天缓存。结果仅供
研究参考，不构成买卖指令。
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
_MIN_TURNOVER_WAN = 3000.0  # 流动性门槛（万元）：K线扫描与回测 universe 都先过这道


def _num(v) -> float | None:
    try:
        f = float(v)
        return None if f != f else f  # NaN → 缺失
    except (TypeError, ValueError):
        return None


# ---- 指标注册表（v2：31 个，全部带口径说明） ----
# kind: row=候选池行直取 / kline=逐股K线计算 / slow=逐股慢速数据源（按天缓存）

_NUM_OPS = [">", ">=", "<", "<=", "between"]
_BOOL_OPS = ["eq"]
_TEXT_OPS = ["contains"]


def _m(name: str, category: str, caliber: str, kind: str, ops: list[str], unit: str = "") -> dict:
    return {"name": name, "category": category, "caliber": caliber,
            "kind": kind, "ops": ops, "unit": unit}


METRICS: dict[str, dict] = {
    # 基础信息
    "price": _m("现价", "基础信息", "腾讯/东财实时报价（元）", "row", _NUM_OPS, "元"),
    "mcap_yi": _m("总市值", "基础信息", "腾讯报价 f45 总市值", "row", _NUM_OPS, "亿"),
    "industry": _m("所属行业", "基础信息", "东财业绩报表「所处行业」列", "row", _TEXT_OPS),
    "float_mcap_yi": _m("流通市值", "基础信息", "腾讯报价 f44 流通市值（区别于总市值）", "row", _NUM_OPS, "亿"),
    # 估值
    "pe_ttm": _m("市盈率PE(TTM)", "估值", "滚动市盈率；亏损为负值——筛便宜股应配合 min=0 排除亏损",
                 "row", _NUM_OPS),
    "pb": _m("市净率PB", "估值", "腾讯报价 f46 市净率", "row", _NUM_OPS),
    "div_yield": _m("股息率(3年均)", "估值", "近3个年报每股分红均值/现价×100；股价大跌会推高——警惕价值陷阱",
                    "row", _NUM_OPS, "%"),
    "div_yield_latest": _m("股息率(最新年报)", "估值", "最新年报每股分红/现价×100", "row", _NUM_OPS, "%"),
    "pe_pct": _m("PE(TTM)近5年分位", "估值", "百度股市通逐股慢速；建议先加估值/流动性粗筛再用",
                 "slow", _NUM_OPS, "%"),
    # 财务
    "roe": _m("ROE(最新年报)", "财务", "东财业绩报表 净资产收益率（年报口径）", "row", _NUM_OPS, "%"),
    "roe_min3": _m("ROE(近3年报最低)", "财务", "近3个年报ROE最小值；任一年缺失=数据缺失", "row", _NUM_OPS, "%"),
    "roe_mean3": _m("ROE(近3年均值)", "财务", "近3个年报ROE算术平均", "row", _NUM_OPS, "%"),
    "growth": _m("净利润同比", "财务", "东财业绩报表 净利润同比增长（最新年报）", "row", _NUM_OPS, "%"),
    "revenue_growth": _m("营收同比", "财务", "东财业绩报表 营业收入同比增长（最新年报）", "row", _NUM_OPS, "%"),
    "deduct_growth": _m("扣非净利润同比", "财务", "东财F10 主要指标 KCFJCXSYJLR 自算同比，逐股慢速",
                        "slow", _NUM_OPS, "%"),
    "ocf_over_profit": _m("OCF/净利(3年合计)", "财务", "经营现金流净额/净利润 近3年报合计；>1 利润有现金背书；分母≤0=缺失",
                          "row", _NUM_OPS),
    "fcf_yi": _m("FCF代理(3年合计)", "财务", "经营+投资现金流净额 近3年报合计（含证券投资，非精确capex口径）",
                 "row", _NUM_OPS, "亿"),
    # 技术（K线，前复权日频）
    "above_ma20": _m("收盘站上MA20", "技术", "最新收盘 > 20日均线", "kline", _BOOL_OPS),
    "ma20_angle": _m("MA20角度", "技术", "atan(MA20日斜率%×100)；30°≈日涨0.58%", "kline", _NUM_OPS, "度"),
    "ret20": _m("近20日收益率", "技术", "收盘/20根前收盘-1", "kline", _NUM_OPS, "%"),
    "ret60": _m("近60日收益率", "技术", "收盘/60根前收盘-1", "kline", _NUM_OPS, "%"),
    "ret120": _m("近120日收益率", "技术", "收盘/120根前收盘-1", "kline", _NUM_OPS, "%"),
    "vol_ratio": _m("量比", "技术", "今日成交量/前5日均量", "kline", _NUM_OPS),
    "new_high60": _m("创60日新高", "技术", "收盘 ≥ 前60根最高收盘（不含当日）", "kline", _BOOL_OPS),
    "amount_yi": _m("当日成交额(K线)", "技术", "K线成交额（亿元）；回测可用的流动性口径", "kline", _NUM_OPS, "亿"),
    "avg_amount20_yi": _m("近20日日均成交额", "技术", "K线近20根成交额均值（亿元）；比单日成交额更能代表可交易性",
                          "kline", _NUM_OPS, "亿"),
    # 风险过滤
    "turnover_wan": _m("当日成交额", "风险过滤", "腾讯报价 f37（万元）；≥3000万 为主流流动性门槛",
                       "row", _NUM_OPS, "万"),
    "debt_ratio": _m("资产负债率", "风险过滤", "东财资产负债表（最新披露期）", "row", _NUM_OPS, "%"),
    "profit_yi": _m("净利润(最新年报)", "风险过滤", "东财业绩报表 净利润；配 >0 排除亏损股", "row", _NUM_OPS, "亿"),
    "vol20": _m("近20日波动率", "风险过滤", "近20根日收益率样本标准差（%，未年化）；越低越平稳，防御组合排序用",
                "kline", _NUM_OPS, "%"),
    "listed_2y": _m("上市满2年", "风险过滤", "K线≥480根（约2年交易日）推断，逐股慢速两段补数；1=满，0=次新",
                    "slow", _BOOL_OPS),
}

METRIC_CATEGORIES = ["基础信息", "估值", "财务", "技术", "风险过滤"]


# ---- 行指标取值（含派生口径） ----

def _cashflow_detail(row: dict) -> dict:
    """OCF/净利（3年合计）与 FCF 代理合计；分母≤0 → ratio=None（缺失，不当0）。"""
    ocf_map = row.get("ocf_hist") or {}
    periods = list(ocf_map.keys())[:3]
    ocf_total = sum(float(ocf_map.get(p, 0) or 0) for p in periods)
    profit_total = sum(float((row.get("profit_hist") or {}).get(p, 0) or 0) for p in periods)
    inv_total = sum(float((row.get("inv_hist") or {}).get(p, 0) or 0) for p in periods)
    ratio = ocf_total / profit_total if profit_total > 0 else None
    return {"ocf_total": ocf_total, "profit_total": profit_total,
            "ocf_over_profit": ratio, "fcf_total": ocf_total + inv_total}


def _hist3_stat(hist: dict | None, fn) -> float | None:
    """近3期统计量；期数不足或任一期缺失 → None。"""
    if not hist:
        return None
    vals = [_num(hist.get(p)) for p in list(hist.keys())[:3]]
    if len(vals) < 3 or any(v is None for v in vals):
        return None
    return round(fn(vals), 2)


_DERIVED = {
    "roe_min3": lambda r: _hist3_stat(r.get("roe_hist"), min),
    "roe_mean3": lambda r: _hist3_stat(r.get("roe_hist"), lambda v: sum(v) / len(v)),
    "ocf_over_profit": lambda r: _num(_cashflow_detail(r)["ocf_over_profit"]),
    "fcf_yi": lambda r: (lambda d: None if d["fcf_total"] is None else d["fcf_total"] / 1e8)(_cashflow_detail(r)),
    "profit_yi": lambda r: (None if _num(r.get("profit")) is None else _num(r.get("profit")) / 1e8),
}


def metric_value(row: dict, key: str, vals: dict | None = None) -> float | str | None:
    """指标取值：row 直取/派生；kline/slow 从预取值表 {code: {metric: value}} 拿。"""
    m = METRICS[key]
    if m["kind"] == "row":
        if key in _DERIVED:
            return _DERIVED[key](row)
        if m["ops"] == _TEXT_OPS:  # 文本指标（行业）原样返回
            return row.get(key)
        return _num(row.get(key))
    return _num(((vals or {}).get(row.get("code")) or {}).get(key))


# ---- 单条件求值 ----

def _fmt(v) -> str:
    if isinstance(v, str):
        return v
    if v is None:
        return "—"
    return f"{v:g}"


def _describe(c: dict, value) -> str:
    m = METRICS[c["metric"]]
    op = c["op"]
    if op == "between":
        return f"{m['name']} {_fmt(value)} ∈ [{_fmt(c.get('min'))}, {_fmt(c.get('max'))}]"
    op_text = {">": ">", ">=": "≥", "<": "<", "<=": "≤", "eq": "=", "contains": "含"}[op]
    if op == "eq":  # 布尔指标：显示 是/否 而不是 1/0
        yn = {1: "是", 0: "否"}
        return f"{m['name']}为{yn.get(float(c.get('value', 1)), c.get('value'))}"
    target = _fmt(c.get("value"))
    unit = m.get("unit") or ""
    return f"{m['name']} {_fmt(value)} {op_text} {target}{unit if unit not in ('%', '亿', '万') else ''}"


def eval_condition(c: dict, value) -> tuple[bool, bool, str]:
    """返回 (是否命中, 数据是否已知, 描述文本)。

    数据缺失：不命中、known=False——negate 也不命中（缺失不能当「通过排除」）。
    """
    m = METRICS[c["metric"]]
    name = m["name"]
    if value is None:
        return False, False, f"{name} 数据缺失"
    op = c["op"]
    if op == ">":
        hit = value > c["value"]
    elif op == ">=":
        hit = value >= c["value"]
    elif op == "<":
        hit = value < c["value"]
    elif op == "<=":
        hit = value <= c["value"]
    elif op == "between":
        hit = c["min"] <= value <= c["max"]
    elif op == "eq":
        hit = float(value) == float(c["value"])
    elif op == "contains":
        hit = str(c["value"]) in str(value)
    else:  # validate_rule 已挡，此处兜底
        return False, False, f"{name} 未知运算符 {op}"
    if c.get("negate"):
        hit = not hit
    text = ("非（排除）：" if c.get("negate") else "") + _describe(c, value) + ("✓" if hit else "✗")
    return hit, True, text


# ---- 规则校验 ----

def validate_rule(rule: dict) -> list[str]:
    """规则合法性检查，返回错误列表（空=合法）。"""
    errors: list[str] = []
    conds = rule.get("conditions") or []
    if not conds:
        errors.append("至少需要一条条件")
    if rule.get("logic", "all") not in ("all", "any"):
        errors.append(f"logic 须为 all/any，收到 {rule.get('logic')}")
    for c in conds:
        metric = c.get("metric")
        m = METRICS.get(metric)
        if m is None:
            errors.append(f"未知指标：{metric}")
            continue
        op = c.get("op")
        if op not in m["ops"]:
            errors.append(f"{m['name']} 不支持运算符 {op}（可用：{'/'.join(m['ops'])}）")
            continue
        if op == "between" and (c.get("min") is None or c.get("max") is None):
            errors.append(f"{m['name']} 的 between 条件需要 min 与 max")
        if op != "between" and c.get("value") is None:
            errors.append(f"{m['name']} 的条件缺少 value")
    rank = rule.get("rank")
    if rank:
        if rank.get("metric") not in METRICS:
            errors.append(f"排名指标未知：{rank.get('metric')}")
        top = rank.get("top_pct")
        if not top or not (0 < top <= 100):
            errors.append("排名 top_pct 须在 (0, 100] 内")
        if rank.get("order", "desc") not in ("desc", "asc"):
            errors.append("排名 order 须为 desc/asc")
    return errors


# ---- 组合筛选 ----

def eval_rows(rows: list[dict], rule: dict, vals: dict | None = None) -> list[dict]:
    """逐行求值全部条件：[{row, results, values, passed}]。"""
    logic = rule.get("logic", "all")
    rank = rule.get("rank")
    out = []
    for row in rows:
        results, values = [], {}
        for c in rule["conditions"]:
            v = metric_value(row, c["metric"], vals)
            hit, known, text = eval_condition(c, v)
            results.append({"metric": c["metric"], "value": v, "hit": hit,
                            "known": known, "text": text})
            values[c["metric"]] = v
        hits = [r["hit"] for r in results]
        passed = all(hits) if logic == "all" else any(hits)
        if rank:
            values[rank["metric"]] = metric_value(row, rank["metric"], vals)
        out.append({"row": row, "results": results, "values": values, "passed": passed})
    return out


_ITEM_FIELDS = ["code", "name", "industry", "price", "pe_ttm", "pb", "mcap_yi",
                "turnover_wan", "div_yield", "roe", "debt_ratio"]


def _select(evals: list[dict], rule: dict) -> list[dict]:
    """从已求值行里取通过者，应用排名（缺失值排最后），拼入选原因。"""
    passed = [e for e in evals if e["passed"]]
    rank = rule.get("rank")
    rank_reason = None
    if rank and passed:
        metric = rank["metric"]
        desc = rank.get("order", "desc") == "desc"
        known = [e for e in passed if e["values"].get(metric) is not None]
        unknown = [e for e in passed if e["values"].get(metric) is None]
        known.sort(key=lambda e: -e["values"][metric] if desc else e["values"][metric])
        ordered = known + unknown
        keep = max(1, math.ceil(len(ordered) * rank["top_pct"] / 100))
        m = METRICS[metric]
        rank_reason = f"排名前{rank['top_pct']:g}%（按{m['name']}{'降序' if desc else '升序'}）✓"
        selected = ordered[:keep]
    else:
        selected = passed
    items = []
    for e in selected:
        reasons = [r["text"] for r in e["results"] if r["hit"]]
        if rank_reason:
            reasons.append(rank_reason)
        item = {k: e["row"].get(k) for k in _ITEM_FIELDS}
        item.update({"values": e["values"], "reasons": reasons})
        items.append(item)
    return items


def screen(rows: list[dict], rule: dict, vals: dict | None = None) -> dict:
    """候选池行 × 规则 → {count, items}（纯函数，可测）。"""
    errors = validate_rule(rule)
    if errors:
        raise ValueError("；".join(errors))
    items = _select(eval_rows(rows, rule, vals), rule)
    return {"count": len(items), "items": items}


# ---- K线技术指标 ----

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


_KLINE_KEYS = ["above_ma20", "ma20_angle", "ret20", "ret60", "ret120",
               "vol_ratio", "new_high60", "amount_yi", "avg_amount20_yi", "vol20"]


def compute_kline_metrics(df: pd.DataFrame) -> dict:
    """标准 OHLCV(+amount) K线 → 技术指标字典；K线不足则对应指标为 None（不当 0）。"""
    out: dict = {k: None for k in _KLINE_KEYS}
    closes = [float(c) for c in df["close"]]
    vols = [float(v) for v in df["volume"]]
    n = len(closes)
    if n < 21:
        return out
    ma20 = sma(closes, 20)
    out["above_ma20"] = 1.0 if closes[-1] > ma20[-1] else 0.0
    out["ma20_angle"] = round(ma_angle_deg([m for m in ma20 if m is not None]), 1)
    out["ret20"] = round((closes[-1] / closes[-21] - 1) * 100, 2)
    if n >= 6:
        base = vols[-6:-1]
        out["vol_ratio"] = round(vols[-1] / (sum(base) / len(base)), 2) if sum(base) > 0 else None
    if n >= 61:
        out["ret60"] = round((closes[-1] / closes[-61] - 1) * 100, 2)
        out["new_high60"] = 1.0 if closes[-1] >= max(closes[-61:-1]) else 0.0
    if n >= 121:
        out["ret120"] = round((closes[-1] / closes[-121] - 1) * 100, 2)
    if "amount" in df.columns and n >= 20:
        amts = [_num(a) for a in df["amount"].iloc[-20:]]
        if all(a is not None for a in amts):
            out["avg_amount20_yi"] = round(sum(amts) / len(amts) / 1e8, 3)
    if n >= 21:
        rets = [closes[i] / closes[i - 1] - 1 for i in range(n - 20, n)]
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        out["vol20"] = round(var ** 0.5 * 100, 2)
    if "amount" in df.columns:
        amt = _num(df["amount"].iloc[-1])
        out["amount_yi"] = round(amt / 1e8, 3) if amt is not None else None
    return out


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


# ---- 规则可回测性（防未来数据泄漏） ----

def rule_backtestable(rule: dict) -> tuple[bool, str]:
    """只有纯 K线条件规则可历史回放；财务/估值/慢速条件的历史横截面未实现，
    重放会引入未来数据泄漏——诚实拒绝而不是给一个虚高的回测。"""
    bad = sorted({c["metric"] for c in rule["conditions"] if METRICS[c["metric"]]["kind"] != "kline"})
    if bad:
        names = "、".join(METRICS[k]["name"] for k in bad)
        return False, (
            f"规则含非K线条件（{names}）：财务/估值指标的历史横截面快照未实现，"
            "用今天的财务数据回放历史会引入未来数据泄漏——仅纯K线规则支持回测。"
            "可在回测面板用「趋势信号回测」验证执行面（入场/持有/止损纪律）。"
        )
    return True, ""


def _kline_signal(conds: list[dict], prefix: pd.DataFrame, code: str) -> bool:
    """前缀K线上重放全部 K线条件（无未来数据：只用 prefix 内的K线）。"""
    m = compute_kline_metrics(prefix)
    fake = {"code": code}
    return all(eval_condition(c, metric_value(fake, c["metric"], {code: m}))[0] for c in conds)


_MIN_BARS = {"above_ma20": 21, "ma20_angle": 26, "ret20": 21, "ret60": 61,
             "new_high60": 61, "ret120": 121, "vol_ratio": 6, "amount_yi": 1}


def _signal_start(conds: list[dict]) -> int:
    """回放起始下标 = 规则所需最长回看窗口（前置K线不足时指标为缺失不会误触发）。"""
    return max((_MIN_BARS.get(c["metric"], 21) for c in conds), default=21)


def _replay(df: pd.DataFrame, signal_fn, hold: int, stop: float,
            start: int | None = None) -> list[float]:
    """单股回放：信号成立次日收盘入场，持有 hold 日或触发止损离场，持仓期不重叠。"""
    n = len(df)
    trades: list[float] = []
    i = start if start is not None else 61
    while i < n - 2:
        if signal_fn(df.iloc[: i + 1].reset_index(drop=True)):
            entry = float(df["close"].iloc[i + 1])
            exit_j = min(i + 1 + hold, n - 1)
            for j in range(i + 2, exit_j + 1):
                if float(df["close"].iloc[j]) / entry - 1 <= stop:
                    exit_j = j
                    break
            trades.append(float(df["close"].iloc[exit_j]) / entry - 1)
            i = exit_j + 1
        else:
            i += 1
    return trades


def backtest_rule(rule: dict, klines: dict[str, pd.DataFrame],
                  hold: int = 20, stop: float = -0.08) -> dict:
    """纯K线规则回测：逐股回放合并统计。调用方先用 rule_backtestable 把关。"""
    ok, why = rule_backtestable(rule)
    if not ok:
        raise ValueError(why)
    conds = rule["conditions"]
    start = _signal_start(conds)
    trades: list[float] = []
    for code, df in klines.items():
        trades.extend(_replay(df, lambda p, c=code: _kline_signal(conds, p, c), hold, stop, start))
    stats = stats_from_trades(trades)
    return {
        "stats": stats,
        "verdict": strategy_verdict(stats),
        "trades": trades,
        "note": (
            f"回测口径：全部条件同日成立→次日收盘入场，持有{hold}日或{stop:.0%}止损，"
            "持仓期不重叠开仓；逐股回放后合并统计，K线为前复权。样本<20笔不可信。"
        ),
    }


# ---- 内置组合（现成方案；阈值为公开回测复盘整理，不是买卖建议） ----
# ST 与北交所已在候选池层面全池剔除（screener.build_rows）。

PRESETS = [
    {
        "key": "roe_pe",
        "name": "高ROE+低PE",
        "desc": "近3年ROE均值>20%，PE上限取该ROE均值（默认20），净利同比>0，剔强周期，"
                "上市满2年。公开回测（单券商，约至2019年）：等权年初调仓十年净值+246% vs 沪深300 +66%，"
                "超额主要来自消费类——周期股高ROE+低PE可能是景气见顶信号。建议每年/每半年调仓一次。",
        "rule": {
            "logic": "all",
            "conditions": [
                {"metric": "roe_mean3", "op": ">", "value": 20},
                {"metric": "pe_ttm", "op": "between", "min": 0, "max": 20},
                {"metric": "growth", "op": ">", "value": 0},
                {"metric": "listed_2y", "op": "eq", "value": 1},
                # 关键词与东财「所处行业」实际取值核对过（v5 live 验证 2026-10-20）：
                # 有色=工业金属/能源金属/贵金属/小金属/金属新材料，钢铁=普钢/特钢Ⅱ/冶钢原料
                # （不能用「金属」——「非金属材料Ⅱ」含「金属」二字会误伤建材）
                {"metric": "industry", "op": "contains", "value": "煤炭", "negate": True},
                {"metric": "industry", "op": "contains", "value": "工业金属", "negate": True},
                {"metric": "industry", "op": "contains", "value": "能源金属", "negate": True},
                {"metric": "industry", "op": "contains", "value": "贵金属", "negate": True},
                {"metric": "industry", "op": "contains", "value": "小金属", "negate": True},
                {"metric": "industry", "op": "contains", "value": "金属新材料", "negate": True},
                {"metric": "industry", "op": "contains", "value": "普钢", "negate": True},
                {"metric": "industry", "op": "contains", "value": "特钢", "negate": True},
                {"metric": "industry", "op": "contains", "value": "冶钢原料", "negate": True},
            ],
            "rank": None,
        },
    },
    {
        "key": "roe_pb",
        "name": "高ROE中的低PB",
        "desc": "ROE>12%，0<PB≤2，净利同比>0，负债率<60%（金融、地产除外）。"
                "高ROE低PB资产长期占优（券商研判）；风险是当前高ROE未必持续，周期行业易掉价值陷阱。",
        "rule": {
            "logic": "all",
            "conditions": [
                {"metric": "roe", "op": ">", "value": 12},
                {"metric": "pb", "op": "between", "min": 0, "max": 2},
                {"metric": "growth", "op": ">", "value": 0},
                {"metric": "debt_ratio", "op": "<", "value": 60},
                {"metric": "industry", "op": "contains", "value": "银行", "negate": True},
                {"metric": "industry", "op": "contains", "value": "保险", "negate": True},
                {"metric": "industry", "op": "contains", "value": "证券", "negate": True},
                {"metric": "industry", "op": "contains", "value": "房地产", "negate": True},
            ],
            "rank": None,
        },
    },
    {
        "key": "small_quality",
        "name": "小市值+质量过滤",
        "desc": "流通市值20-80亿，近20日日均成交额>0.3亿（买得进卖得出），0<PE≤40，ROE>5%，"
                "负债率<70%，上市满2年。小市值是A股长期有效因子；波动最大，务必分散持仓，"
                "可配合「历史验证」看持有60/120日表现。",
        "rule": {
            "logic": "all",
            "conditions": [
                {"metric": "float_mcap_yi", "op": "between", "min": 20, "max": 80},
                {"metric": "avg_amount20_yi", "op": ">", "value": 0.3},
                {"metric": "pe_ttm", "op": "between", "min": 0, "max": 40},
                {"metric": "roe", "op": ">", "value": 5},
                {"metric": "debt_ratio", "op": "<", "value": 70},
                {"metric": "listed_2y", "op": "eq", "value": 1},
            ],
            "rank": None,
        },
    },
    {
        "key": "low_vol",
        "name": "防御型(低估值+低波)",
        "desc": "0<PE≤15，0<PB≤1.5，负债率<50%，近20日波动率最低30%。"
                "低估值熊市抗跌，估值驱动的牛市（2015/2019）往往跑输；追求回撤小，不追求涨得多。",
        "rule": {
            "logic": "all",
            "conditions": [
                {"metric": "pe_ttm", "op": "between", "min": 0, "max": 15},
                {"metric": "pb", "op": "between", "min": 0, "max": 1.5},
                {"metric": "debt_ratio", "op": "<", "value": 50},
            ],
            "rank": {"metric": "vol20", "top_pct": 30, "order": "asc"},
        },
    },
]


# ---- 逐股补数（K线 / 慢速指标，带按天缓存） ----

def _stock_kline(code: str, days: int, cache_dir: str | None = None) -> pd.DataFrame:
    return fetch_kline(code, days=days, cache_dir=cache_dir)


def _tradable_rows(rows: list[dict]) -> list[dict]:
    """流动性门槛过滤 + 成交额降序（K线扫描/回测 universe 用）。"""
    tradable = [r for r in rows
                if isinstance(r.get("turnover_wan"), (int, float))
                and r["turnover_wan"] >= _MIN_TURNOVER_WAN]
    return sorted(tradable, key=lambda r: -r["turnover_wan"])


def _fetch_klines(codes: list[str], cache_dir: str | None,
                  bars: int = 400) -> dict[str, pd.DataFrame]:
    """并发逐股拉K线（默认400根：指标用尾部、回测用全量），单股失败不废整体。

    bars 可加大：历史验证要 asof 之前有足够前缀（listed_2y 需 480 根）。
    """

    def _one(code: str):
        try:
            return code, _stock_kline(code, bars, cache_dir)
        except Exception:  # noqa: BLE001
            return code, None

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = pool.map(_one, codes)
    return {code: df for code, df in results if df is not None}


def _pending_rows(evals: list[dict], rule: dict) -> list[dict]:
    """两段式补数的待补行：非慢条件已满足、慢条件还缺数据的行。"""
    slow_metrics = {c["metric"] for c in rule["conditions"]
                    if METRICS[c["metric"]]["kind"] == "slow"}
    if not slow_metrics:
        return []
    logic = rule.get("logic", "all")
    out = []
    for e in evals:
        unknown = [r for r in e["results"]
                   if r["metric"] in slow_metrics and not r["known"]]
        if not unknown or e["passed"]:
            continue  # 无待补 / 已通过
        definite = [r for r in e["results"] if r["metric"] not in slow_metrics]
        if logic == "all":
            if all(r["hit"] for r in definite):
                out.append(e)
        else:  # any：其余条件都没中的，慢条件中了就能过 → 也要补
            out.append(e)
    return out


def _merge_vals(vals: dict, codes: list[str], key: str, mapping: dict) -> None:
    for code in codes:
        v = mapping.get(code)
        if v is not None:
            vals.setdefault(code, {})[key] = v


def run_screen(rule: dict, cache_dir: str | None, refresh: bool = False,
               kline_limit: int = 300) -> dict:
    """筛选编排：行条件先筛 →（需要时）K线扫描 →（需要时）慢指标两段补数 → 终筛。"""
    errors = validate_rule(rule)
    if errors:
        raise ValueError("；".join(errors))
    rows = rows_cached(cache_dir, refresh)
    metrics_in_rule = {c["metric"] for c in rule["conditions"]}
    if rule.get("rank"):
        metrics_in_rule.add(rule["rank"]["metric"])
    kinds = {METRICS[k]["kind"] for k in metrics_in_rule}

    vals: dict = {}
    kline_scanned = 0
    if "kline" in kinds:
        universe = _tradable_rows(rows)[:kline_limit]
        klines = _fetch_klines([r["code"] for r in universe], cache_dir)
        vals = {code: compute_kline_metrics(df) for code, df in klines.items()}
        kline_scanned = len(vals)

    evals = eval_rows(rows, rule, vals)
    slow_fetched = 0
    if "slow" in kinds:
        pending = _pending_rows(evals, rule)
        codes = [e["row"]["code"] for e in pending]
        slow_fetched = len(codes)
        if codes:
            if "pe_pct" in metrics_in_rule:
                _merge_vals(vals, codes, "pe_pct", pe_percentile_cached(codes, cache_dir))
            if "deduct_growth" in metrics_in_rule:
                _merge_vals(vals, codes, "deduct_growth", deduct_growth_cached(codes, cache_dir))
            if "listed_2y" in metrics_in_rule:
                _merge_vals(vals, codes, "listed_2y", listed_2y_cached(codes, cache_dir))
            evals = eval_rows(rows, rule, vals)

    items = _select(evals, rule)
    review: list[str] = []
    for it in items:
        review.extend(manual_review_items(it))
    return {
        "asof": datetime.now().isoformat(timespec="seconds"),
        "universe": len(rows),
        "kline_scanned": kline_scanned,
        "slow_fetched": slow_fetched,
        "count": len(items),
        "items": items,
        "market_guard": market_guard(cache_dir),
        "manual_review": review,
    }


def run_backtest(rule: dict, cache_dir: str | None, kline_limit: int = 250,
                 hold: int = 20, stop: float = -0.08) -> dict:
    """回测编排：流动性门槛取前 kline_limit 只 → 拉K线 → 规则回放。"""
    ok, why = rule_backtestable(rule)
    if not ok:
        raise ValueError(why)
    rows = _tradable_rows(rows_cached(cache_dir))[:kline_limit]
    klines = _fetch_klines([r["code"] for r in rows], cache_dir)
    out = backtest_rule(rule, klines, hold, stop)
    out.update({
        "asof": datetime.now().isoformat(timespec="seconds"),
        "n_stocks": len(klines),
    })
    return out


# ---- 人工清洗与执行纪律 ----

def manual_review_items(row: dict) -> list[str]:
    """数据面覆盖不到的雷，固定输出人工核查清单（筛选结果≠买入清单）。"""
    return [
        f"{row['code']} {row['name']}：大股东质押比例是否>50%（F10·股权质押人工核）",
        f"{row['code']} {row['name']}：近3月减持计划/业绩预亏预告/监管处罚（公告人工核）",
    ]


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


# ---- 慢速指标源（百度PE分位 / F10扣非增速），按天缓存 ----

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


_LISTED_MIN_BARS = 480  # ≈2年A股交易日；K线根数不足即「上市不满2年」（次新）


def _safe_listed_2y(code: str) -> float | None:
    try:
        df = _stock_kline(code, 550)  # 550 > 480：拉满即可分辨满/不满2年
        return 1.0 if len(df) >= _LISTED_MIN_BARS else 0.0
    except Exception:  # noqa: BLE001 - 拉不到按缺失，不误判
        return None


def listed_2y_cached(codes: list[str], cache_dir: str | None) -> dict[str, float | None]:
    return _daily_cached("listed2y", codes, cache_dir, _safe_listed_2y)


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


__all__ = [
    "METRICS",
    "METRIC_CATEGORIES",
    "PRESETS",
    "metric_value",
    "eval_condition",
    "validate_rule",
    "eval_rows",
    "screen",
    "compute_kline_metrics",
    "rule_backtestable",
    "backtest_rule",
    "run_screen",
    "run_backtest",
    "stats_from_trades",
    "strategy_verdict",
    "sma",
    "ma_angle_deg",
    "trade_plan",
    "manual_review_items",
    "market_guard",
    "pe_percentile_cached",
    "deduct_growth_cached",
]
