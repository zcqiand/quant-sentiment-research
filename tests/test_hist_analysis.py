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

def test_refuses_financial_rule():
    rule = {"logic": "all", "conditions": [{"metric": "pe_ttm", "op": "<", "value": 20}], "rank": None}
    with pytest.raises(ValueError, match="泄漏"):
        ha.analyze_hist(rule, "2024-06-01", _synth_klines(), ROWS)


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
    monkeypatch.setattr(ha, "_fetch_klines", lambda codes, cache_dir: _synth_klines())
    monkeypatch.setattr(ha, "_bench_kline", lambda: _kline([2000 + i for i in range(100)]))
    out = ha.run_hist_screen(RULE, dates[59], "cache/dir")
    assert out["count"] == 1
    assert out["n_stocks"] == 3
    assert out["horizons"]["20"]["n"] == 1
    assert any("幸存者" in n for n in out["notes"])


def test_run_hist_screen_refuses_before_fetch(monkeypatch):
    rule = {"logic": "all", "conditions": [{"metric": "roe", "op": ">=", "value": 10}], "rank": None}
    called = {"rows": False}
    monkeypatch.setattr(ha, "rows_cached", lambda cache_dir: called.__setitem__("rows", True) or [])
    with pytest.raises(ValueError, match="泄漏"):
        ha.run_hist_screen(rule, "2024-06-01", "cache/dir")
    assert not called["rows"]  # 拒绝发生在拉数据之前
