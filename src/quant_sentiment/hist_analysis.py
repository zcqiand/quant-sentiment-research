"""功能A：历史选股表现分析（point-in-time 筛选 + 前瞻收益统计）。

用户选一个历史日期，软件用**当时可得**的数据筛选股票，统计入选股持有
20/60/120 个交易日的收益率，并对照同期市场基准。

诚实纪律（与 conditions 回测同源）：
- K线用截至历史日的前缀；财务/估值指标走 fin_snapshot 公告日期门控的历史快照
  （公告日 ≤ 历史日才计入）——没有历史化的指标由 hist_supportable 拒绝；
- 入场 = 信号日次日收盘（与回测纪律一致）；
- 回看窗不足的 K线按「数据缺失」处理，不当 0、不误判；
- 幸存者偏差（股票池是今天仍在市的）、期限不足、无分红无成本、历史PE/PB口径，
  全部显式透出。
"""
from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pandas as pd

from .conditions import (
    METRICS,
    _fetch_klines,
    _signal_start,
    _tradable_rows,
    compute_kline_metrics,
    fetch_market_kline,
    screen,
    validate_rule,
)
from .fin_snapshot import fetch_hist_fundamentals, hist_supportable
from .screener import rows_cached

HORIZONS = (20, 60, 120)

_LISTED_2Y_BARS = 480  # 与 conditions.listed_2y 同一口径（约2年交易日）


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
                 rows: list[dict], bench: pd.DataFrame | None = None,
                 fundamentals: dict[str, dict] | None = None) -> dict:
    """纯函数部分：历史截面筛选 + 前瞻收益统计。klines={code: 全量日K}。

    fundamentals={code: 快照}（fin_snapshot.build_snapshots 产物，含 eps_ttm/bps）
    时，PE/PB=当时收盘÷快照值、流通市值=当前流通股本×当时价格（近似，notes 标注）。
    """
    errors = validate_rule(rule)
    if errors:
        raise ValueError("；".join(errors))
    ok, why = hist_supportable(rule)
    if not ok:
        raise ValueError(why)
    ts = _parse_asof(asof)

    conds = rule["conditions"]
    need = _signal_start(conds)
    metrics = {c["metric"] for c in conds}
    if rule.get("rank"):
        metrics.add(rule["rank"]["metric"])
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
        vals[code]["listed_2y"] = 1.0 if len(prefix) >= _LISTED_2Y_BARS else 0.0
        closes = [float(c) for c in df["close"]]
        row = dict(meta.get(code, {}))
        snap = (fundamentals or {}).get(code) or {}
        # 历史行覆盖：行业/财务用公告门控快照，PE/PB=当时收盘÷快照EPS/BPS
        for k in ("industry", "roe", "roe_hist", "growth", "revenue_growth", "debt_ratio"):
            if k in snap:
                row[k] = snap[k]
        if snap.get("eps_ttm") is not None and closes[i] > 0:
            row["pe_ttm"] = round(closes[i] / snap["eps_ttm"], 2)
        if snap.get("bps") is not None and closes[i] > 0:
            row["pb"] = round(closes[i] / snap["bps"], 2)
        if ("float_mcap_yi" in metrics and row.get("float_mcap_yi") is not None
                and row.get("price") and row["price"] > 0):
            row["float_mcap_yi"] = round(row["float_mcap_yi"] * closes[i] / row["price"], 2)
        row["code"] = code
        row.setdefault("name", "")
        row["price"] = closes[i]
        universe.append(row)
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
    fin_metrics = metrics & {"pe_ttm", "pb", "roe", "roe_mean3", "roe_min3",
                             "growth", "revenue_growth", "debt_ratio", "industry"}
    if fundamentals and fin_metrics:
        notes.append("财务/估值指标为历史快照：公告日≤所选日期、或已过法定披露截止"
                     "（年报次年4-30/中报8-31等）才计入；ROE/增速为年报口径，"
                     "历史PE/PB=当时收盘÷历史EPS/BPS估算，与实时口径略有差异。")
    elif fin_metrics:
        notes.append("本结果未注入财务快照——含财务/估值条件的股票全部按数据缺失处理（不命中）。")
    if fundamentals and "float_mcap_yi" in metrics:
        notes.append("历史流通市值为近似值：当前流通股本×当时价格，股本变动未还原。")
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
    """编排：纪律门 → 候选池 → 财务快照（公告门控）→ 加长K线窗 → 历史截面分析。"""
    _parse_asof(asof)  # 日期先验，别拉完数据才报格式错
    ok, why = hist_supportable(rule)
    if not ok:
        raise ValueError(why)
    metrics = {c["metric"] for c in rule["conditions"]}
    if rule.get("rank"):
        metrics.add(rule["rank"]["metric"])
    # K线窗 = asof 至今的交易日 + 规则所需最长回看（listed_2y 需 480 根前缀）+ 前瞻缓冲
    gap = int(np.busday_count(_parse_asof(asof).date(), date.today()))
    extra = _LISTED_2Y_BARS if "listed_2y" in metrics else max(_signal_start(rule["conditions"]), 21)
    bars = gap + extra + max(HORIZONS)
    rows = rows_cached(cache_dir)
    universe = _tradable_rows(rows)[:kline_limit]
    klines = _fetch_klines([r["code"] for r in universe], cache_dir, bars=bars)
    fundamentals: dict[str, dict] | None = None
    fund_warns: list[str] = []
    if any(METRICS[m]["kind"] == "row" for m in metrics):
        fundamentals, fund_warns = fetch_hist_fundamentals(asof, rule, cache_dir)
    try:
        bench = _bench_kline()
    except Exception:  # noqa: BLE001 — 基准拉不到不废整体，基准列记缺失
        bench = None
    out = analyze_hist(rule, asof, klines, rows, bench, fundamentals)
    out["notes"].extend(fund_warns)  # 表拉取失败透出结果，不许静默瘸腿
    out["n_stocks"] = len(klines)
    out["ran_at"] = datetime.now().isoformat(timespec="seconds")
    return out
