"""功能A：历史选股表现分析（point-in-time 筛选 + 前瞻收益统计）。

用户选一个历史日期，软件用**当时可得**的数据（K线截至该日）筛选股票，
统计入选股持有 20/60/120 个交易日的收益率，并对照同期市场基准。

诚实纪律（与 conditions 回测同源）：
- 仅纯 K线规则——财务/估值指标的历史横截面快照未实现，重放即未来数据泄漏，
  rule_backtestable 拒绝；
- 入场 = 信号日次日收盘（与回测纪律一致）；
- 回看窗不足的 K线按「数据缺失」处理，不当 0、不误判；
- 幸存者偏差（股票池是今天仍在市的）、期限不足、无分红无成本，全部显式透出。
"""
from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from .conditions import (
    _fetch_klines,
    _signal_start,
    _tradable_rows,
    compute_kline_metrics,
    fetch_market_kline,
    rule_backtestable,
    screen,
    validate_rule,
)
from .screener import rows_cached

HORIZONS = (20, 60, 120)


def _bench_kline() -> pd.DataFrame:
    """基准指数日K（上证 sh000001），编排层测试 monkeypatch 此桩。"""
    return fetch_market_kline()


def _parse_asof(asof: str) -> pd.Timestamp:
    try:
        ts = pd.Timestamp(asof)
    except Exception:  # noqa: BLE001
        raise ValueError("历史日期格式应为 YYYY-MM-DD") from None
    if ts > pd.Timestamp(date.today()):
        raise ValueError("历史日期必须早于今天——未来日期没有前瞻收益可统计")
    return ts.normalize()


def _ret_pct(closes: list[float], entry_i: int, hold: int) -> float | None:
    """entry_i 收盘买入、持有 hold 个交易日的收益率（%）；数据不足返回 None。"""
    j = entry_i + hold
    if j >= len(closes):
        return None
    base = closes[entry_i]
    if base <= 0:
        return None
    return round((closes[j] / base - 1) * 100, 2)


def _horizon_stats(rets: list[float], bench: dict | None) -> dict:
    n = len(rets)
    if n == 0:
        return {"n": 0, "mean": None, "median": None, "win_rate": None, "excess_mean": None}
    mean = round(sum(rets) / n, 2)
    srt = sorted(rets)
    median = round(srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2, 2)
    win_rate = round(sum(1 for r in rets if r > 0) / n, 3)
    excess = round(mean - bench["mean"], 2) if bench and bench.get("mean") is not None else None
    return {"n": n, "mean": mean, "median": median, "win_rate": win_rate, "excess_mean": excess}


def analyze_hist(rule: dict, asof: str, klines: dict[str, pd.DataFrame],
                 rows: list[dict], bench: pd.DataFrame | None = None) -> dict:
    """纯函数部分：历史截面筛选 + 前瞻收益统计。klines={code: 全量日K}。"""
    errors = validate_rule(rule)
    if errors:
        raise ValueError("；".join(errors))
    ok, why = rule_backtestable(rule)
    if not ok:
        raise ValueError(why)
    ts = _parse_asof(asof)

    conds = rule["conditions"]
    need = _signal_start(conds)
    meta = {r["code"]: r for r in rows}

    universe: list[dict] = []
    vals: dict = {}
    kline_missing = 0
    forward: dict[str, dict] = {}

    for code, df in klines.items():
        dates = pd.to_datetime(df["date"]).dt.tz_localize(None)
        mask = (dates <= ts).to_numpy()
        if not mask.any():
            kline_missing += 1  # 该日之前无K线（次新/未上市）
            continue
        i = int(mask.nonzero()[0][-1])
        if i + 1 < need:
            kline_missing += 1  # 回看窗不足 → 指标缺失，不误判（缺失≠0）
            continue
        prefix = df.iloc[: i + 1].reset_index(drop=True)
        vals[code] = compute_kline_metrics(prefix)
        closes = [float(c) for c in df["close"]]
        row = meta.get(code, {})
        universe.append({"code": code, "name": row.get("name", ""),
                         "industry": row.get("industry"), "price": closes[i]})
        e = i + 1
        if e >= len(closes):
            # 信号日已是当时最后一根K线：无次日收盘可入场（入选后计入 no_entry）
            forward[code] = {"entry_close": None, "ret20": None, "ret60": None, "ret120": None}
            continue
        forward[code] = {"entry_close": closes[e],
                         **{f"ret{h}": _ret_pct(closes, e, h) for h in HORIZONS}}

    sel = screen(universe, rule, vals)
    items = []
    for it in sel["items"]:
        f = forward.get(it["code"], {})
        items.append({"code": it["code"], "name": it["name"], "price": it.get("price"),
                      **{k: f.get(k) for k in ("entry_close", "ret20", "ret60", "ret120")}})
    no_entry = sum(1 for it in items if it["entry_close"] is None)

    # 基准：同一 asof、同一「次日收盘入场 + 持有 h 日」口径
    bench_rets: dict[str, float | None] = {}
    if bench is not None and len(bench):
        bdates = pd.to_datetime(bench["date"]).dt.tz_localize(None)
        bmask = (bdates <= ts).to_numpy()
        if bmask.any():
            j = int(bmask.nonzero()[0][-1]) + 1
            bc = [float(c) for c in bench["close"]]
            bench_rets = {str(h): _ret_pct(bc, j, h) for h in HORIZONS}

    horizons: dict[str, dict] = {}
    for h in HORIZONS:
        key = f"ret{h}"
        rets = [it[key] for it in items if it[key] is not None]
        b = {"mean": bench_rets.get(str(h))} if bench_rets else None
        horizons[str(h)] = _horizon_stats(rets, b)
    incomplete = {str(h): sum(1 for it in items if it[f"ret{h}"] is None) for h in HORIZONS}

    notes = [
        "股票池为今日仍在市的标的，未含已退市/长停个股（幸存者偏差），整体结果偏乐观。",
        "仅统计价格收益，未计交易成本、滑点与分红；入选≠买入建议。",
    ]
    if kline_missing:
        notes.append(f"{kline_missing} 只在所选日期前K线不足（次新/未上市/无数据），按数据缺失处理，未计入筛选。")
    if no_entry:
        notes.append(f"{no_entry} 只信号日已是当时最后一根K线，无次日收盘可入场，收益记缺失。")
    if any(v for v in incomplete.values()):
        notes.append("部分标的持有期未满 20/60/120 交易日，该档收益记缺失（见各档 n 与 incomplete）。")

    return {
        "asof": ts.strftime("%Y-%m-%d"),
        "universe": len(klines),
        "count": len(items),
        "kline_missing": kline_missing,
        "no_entry": no_entry,
        "incomplete": incomplete,
        "benchmark": bench_rets or {str(h): None for h in HORIZONS},
        "horizons": horizons,
        "items": items,
        "notes": notes,
    }


def run_hist_screen(rule: dict, asof: str, cache_dir: str | None,
                    kline_limit: int = 300) -> dict:
    """编排：先过纪律门 → 候选池 → 流动性前 kline_limit 拉K线 → 历史截面分析。"""
    _parse_asof(asof)  # 日期先验，别拉完数据才报格式错
    ok, why = rule_backtestable(rule)
    if not ok:
        raise ValueError(why)
    rows = rows_cached(cache_dir)
    universe = _tradable_rows(rows)[:kline_limit]
    klines = _fetch_klines([r["code"] for r in universe], cache_dir)
    try:
        bench = _bench_kline()
    except Exception:  # noqa: BLE001 — 基准拉不到不废整体，基准列记缺失
        bench = None
    out = analyze_hist(rule, asof, klines, rows, bench)
    out["n_stocks"] = len(klines)
    out["ran_at"] = datetime.now().isoformat(timespec="seconds")
    return out
