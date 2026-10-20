"""功能A：历史选股表现分析——按当时数据筛选 + 持有20/60/120日收益统计。"""

import pandas as pd
import pytest
from datetime import date, timedelta

from quant_sentiment import hist_analysis as ha


def _kline(closes, vols=None, amounts=None, start="2024-01-01"):
    n = len(closes)
    vols = vols or [1000] * n
    data = {
        "date": pd.date_range(start, periods=n, freq="B").strftime("%Y-%m-%d"),
        "open": closes,
        "close": closes,
        "high": [c * 1.02 for c in closes],
        "low": [c * 0.98 for c in closes],
        "volume": vols,
    }
    if amounts is not None:
        data["amount"] = amounts
    return pd.DataFrame(data)


def _dates(n, start="2024-01-01"):
    return list(pd.date_range(start, periods=n, freq="B").strftime("%Y-%m-%d"))


RULE = {"logic": "all",
        "conditions": [{"metric": "above_ma20", "op": "eq", "value": 1}],
        "rank": {"metric": "ret20", "top_pct": 100, "order": "desc"}}

ROWS = [{"code": "600001", "name": "上涨股", "industry": "银行"},
        {"code": "600002", "name": "下跌股", "industry": "白酒"},
        {"code": "600003", "name": "短历史", "industry": "钢铁"}]


def _synth_klines():
    up = [10 + i for i in range(90)]
    down = [90 - i for i in range(90)]
    short = [10 + i for i in range(10)]
    return {"600001": _kline(up), "600002": _kline(down), "600003": _kline(short)}


# ---- 纪律门槛 ----

def test_refuses_unsupported_rule():
    rule = {"logic": "all", "conditions": [{"metric": "pe_pct", "op": "<", "value": 20}], "rank": None}
    with pytest.raises(ValueError, match="泄漏"):
        ha.analyze_hist(rule, "2024-06-01", _synth_klines(), ROWS)


# ---- 财务快照注入（公告日期门控的 point-in-time 值） ----

FUND = {"600001": {"roe": 22.0, "roe_hist": {"20251231": 22.0, "20241231": 21.0, "20231231": 20.0},
                   "growth": 12.0, "revenue_growth": 10.0, "industry": "白色家电",
                   "eps_ttm": 5.0, "bps": 10.0, "debt_ratio": 55.0},
        "600002": {"roe": None, "roe_hist": None, "growth": None, "revenue_growth": None,
                   "industry": None, "eps_ttm": None, "bps": None, "debt_ratio": None}}


def test_fin_condition_uses_snapshot_at_asof():
    # 600001 当时收盘 70（90根线性涨、asof=第60根）、eps_ttm=5 → 历史 PE=14 < 20 入选
    rule = {"logic": "all", "conditions": [{"metric": "pe_ttm", "op": "between", "min": 0, "max": 20}],
            "rank": None}
    out = ha.analyze_hist(rule, _dates(90)[59], _synth_klines(), ROWS, fundamentals=FUND)
    assert out["count"] == 1 and out["items"][0]["code"] == "600001"
    # 600002 快照全缺 → PE 缺失 → 不命中（缺失≠0）
    rule_hi = {"logic": "all", "conditions": [{"metric": "pe_ttm", "op": "between", "min": 0, "max": 10}],
               "rank": None}
    out_hi = ha.analyze_hist(rule_hi, _dates(90)[59], _synth_klines(), ROWS, fundamentals=FUND)
    assert out_hi["count"] == 0  # 14 > 10 不入选；600002 缺失不命中


def test_fin_condition_without_fundamentals_excludes_all():
    rule = {"logic": "all", "conditions": [{"metric": "pe_ttm", "op": "between", "min": 0, "max": 20}],
            "rank": None}
    out = ha.analyze_hist(rule, _dates(90)[59], _synth_klines(), ROWS)
    assert out["count"] == 0
    assert any("财务" in n or "快照" in n for n in out["notes"])


def test_industry_from_snapshot_not_current_row():
    # 当前池子行 industry=银行，历史快照=白色家电——排除条件应对快照生效
    rule = {"logic": "all",
            "conditions": [{"metric": "industry", "op": "contains", "value": "银行", "negate": True}],
            "rank": None}
    out = ha.analyze_hist(rule, _dates(90)[59], _synth_klines(), ROWS, fundamentals=FUND)
    codes = [it["code"] for it in out["items"]]
    assert "600001" in codes  # 当时是白色家电，不该被「剔银行」误伤


def test_listed_2y_point_in_time_from_prefix():
    # 500 根K线、asof 在第 480 根 → 前缀 480+ → 满 2 年；第 479 根则不满
    closes = [10 + i * 0.1 for i in range(500)]
    dates = _dates(500)
    rule = {"logic": "all", "conditions": [{"metric": "listed_2y", "op": "eq", "value": 1}], "rank": None}
    ok = ha.analyze_hist(rule, dates[479], {"600001": _kline(closes)}, ROWS[:1])
    assert ok["count"] == 1
    early = ha.analyze_hist(rule, dates[478], {"600001": _kline(closes)}, ROWS[:1])
    assert early["count"] == 0


def test_float_mcap_approx_scaled_by_price_ratio():
    rows = [{"code": "600001", "name": "上涨股", "industry": "家电",
             "float_mcap_yi": 100.0, "price": 20.0}]
    # 当时收盘 69 / 现价 20 → 历史流通市值 ≈ 100 × 3.45 = 345 亿
    rule = {"logic": "all",
            "conditions": [{"metric": "float_mcap_yi", "op": "between", "min": 300, "max": 400}],
            "rank": None}
    out = ha.analyze_hist(rule, _dates(90)[59], {"600001": _kline([10 + i for i in range(90)])},
                          rows, fundamentals=FUND)
    assert out["count"] == 1
    assert any("流通市值" in n and "近似" in n for n in out["notes"])


def test_asof_must_be_past():
    future = (date.today() + timedelta(days=1)).isoformat()
    with pytest.raises(ValueError, match="早于今天"):
        ha.analyze_hist(RULE, future, _synth_klines(), ROWS)


def test_asof_bad_format():
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        ha.analyze_hist(RULE, "2024/13/99", _synth_klines(), ROWS)


# ---- 筛选与前瞻收益 ----

def test_screen_at_history_and_forward_returns():
    dates = _dates(90)
    out = ha.analyze_hist(RULE, dates[59], _synth_klines(), ROWS)

    assert out["count"] == 1  # 下跌股不命中；短历史回看窗不足按缺失
    assert out["kline_missing"] == 1
    it = out["items"][0]
    assert it["code"] == "600001"
    # 入场=信号日次日收盘；ret20 = close[80]/close[60]-1（线性序列可手算）
    assert it["ret20"] == round((90 / 70 - 1) * 100, 2)
    assert it["ret60"] is None  # 序列只剩 29 根，不足 60
    assert it["ret120"] is None

    h20 = out["horizons"]["20"]
    assert h20["n"] == 1
    assert h20["mean"] == pytest.approx(it["ret20"])
    assert h20["win_rate"] == 1.0
    assert out["horizons"]["60"]["n"] == 0
    assert out["incomplete"]["60"] == 1  # 60/120 档因数据不足记缺失


def test_selection_uses_prefix_only():
    # 前段上涨（asof 当日站上MA20）、后段深跌——用全量算会漏选，用前缀才算对
    closes = [10 + i for i in range(70)] + [80 - 2 * i for i in range(1, 16)]
    dates = _dates(len(closes))
    out = ha.analyze_hist(RULE, dates[69], {"600001": _kline(closes)}, ROWS[:1])
    assert out["count"] == 1
    assert out["items"][0]["code"] == "600001"


def test_signal_on_last_bar_has_no_entry():
    dates = _dates(90)
    out = ha.analyze_hist(RULE, dates[89], _synth_klines(), ROWS)
    assert out["count"] == 1
    assert out["no_entry"] == 1
    assert out["items"][0]["ret20"] is None


# ---- 基准 ----

def test_benchmark_returns_same_windows():
    dates = _dates(100)
    bench = _kline([2000 + i for i in range(100)], start=dates[0])
    out = ha.analyze_hist(RULE, dates[59], _synth_klines(), ROWS, bench=bench)
    expect = round((2080 / 2060 - 1) * 100, 2)
    assert out["benchmark"]["20"] == pytest.approx(expect)
    h20 = out["horizons"]["20"]
    assert h20["excess_mean"] == pytest.approx(round(h20["mean"] - expect, 2))


# ---- 编排 ----

def test_run_hist_screen_orchestration(monkeypatch):
    dates = _dates(90)
    monkeypatch.setattr(ha, "rows_cached", lambda cache_dir: ROWS)
    monkeypatch.setattr(ha, "_fetch_klines", lambda codes, cache_dir, bars=400: _synth_klines())
    monkeypatch.setattr(ha, "_bench_kline", lambda: _kline([2000 + i for i in range(100)]))
    out = ha.run_hist_screen(RULE, dates[59], "cache/dir")
    assert out["count"] == 1
    assert out["n_stocks"] == 3
    assert out["horizons"]["20"]["n"] == 1
    assert any("幸存者" in n for n in out["notes"])


def test_run_hist_screen_refuses_before_fetch(monkeypatch):
    rule = {"logic": "all", "conditions": [{"metric": "pe_pct", "op": ">=", "value": 80}], "rank": None}
    called = {"rows": False}
    monkeypatch.setattr(ha, "rows_cached", lambda cache_dir: called.__setitem__("rows", True) or [])
    with pytest.raises(ValueError, match="泄漏"):
        ha.run_hist_screen(rule, "2024-06-01", "cache/dir")
    assert not called["rows"]  # 拒绝发生在拉数据之前


def test_run_hist_screen_passes_fundamentals_and_bars(monkeypatch):
    """含财务条件的规则走快照注入；listed_2y 规则自动加长 K线拉取窗。"""
    dates = _dates(500)
    captured = {}
    monkeypatch.setattr(ha, "rows_cached", lambda cache_dir: ROWS[:1])
    monkeypatch.setattr(ha, "_fetch_klines",
                        lambda codes, cache_dir, bars=400: captured.update(bars=bars) or {"600001": _kline([10 + i * 0.1 for i in range(500)])})
    monkeypatch.setattr(ha, "fetch_hist_fundamentals",
                        lambda asof, rule, cache_dir: captured.update(fund_called=True)
                        or (FUND, ["业绩报表 20221231 拉取失败——相关年报指标按缺失处理，建议重跑。"]))
    monkeypatch.setattr(ha, "_bench_kline", lambda: _kline([2000 + i for i in range(100)]))
    rule = {"logic": "all",
            "conditions": [{"metric": "listed_2y", "op": "eq", "value": 1},
                           {"metric": "roe_mean3", "op": ">", "value": 15}],
            "rank": None}
    out = ha.run_hist_screen(rule, dates[480], "cache/dir")
    assert captured["fund_called"] is True
    assert captured["bars"] >= 480  # listed_2y 需要 480 根前缀 + asof 至今的交易日
    assert out["count"] == 1  # roe_mean3=21 > 15 且前缀足 480 根
    assert any("20221231" in n for n in out["notes"])  # 拉取失败透出 notes，不许静默
