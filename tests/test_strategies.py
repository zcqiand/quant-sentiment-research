"""选股策略引擎测试：因子纯函数 + 回测统计 + 排除项 + 交易计划，离线全绿。"""

import math

import pandas as pd
import pytest

from quant_sentiment import strategies as st


def _kline(closes, vols=None, start="2024-01-01"):
    """合成日K：date/open/close/high/low/volume。"""
    n = len(closes)
    vols = vols or [1000] * n
    dates = pd.date_range(start, periods=n, freq="B").strftime("%Y-%m-%d")
    return pd.DataFrame(
        {
            "date": dates,
            "open": closes,
            "close": closes,
            "high": [c * 1.02 for c in closes],
            "low": [c * 0.98 for c in closes],
            "volume": vols,
        }
    )


def _value_row(**kw):
    base = {
        "code": "600001", "name": "甲", "price": 10.0, "turnover_wan": 20000.0,
        "pe_ttm": 15.0, "pb": 1.5, "mcap_yi": 200.0, "roe": 18.0, "debt_ratio": 40.0,
        "ocf": {"20251231": 12.0, "20241231": 11.0, "20231231": 10.0},
        "inv_hist": {"20251231": -3.0, "20241231": -3.0, "20231231": -3.0},
        "profit": 10.0, "profit_hist": {"20251231": 10.0, "20241231": 9.0, "20231231": 8.0},
        "roe_hist": {"20251231": 18.0, "20241231": 17.0, "20231231": 16.0},
        "growth": 25.0,
        "dps": {"20251231": 0.5, "20241231": 0.5, "20231231": 0.5}, "div_yield": 5.0,
    }
    base.update(kw)
    return base


# ---- 因子：现金流（FCF 代理） ----

def test_cashflow_factor_pass():
    """OCF/净利 3年合计>1 且 近3年 FCF(经营+投资) 合计>0 = 真金白银。"""
    ok, detail = st.cashflow_factor(_value_row())
    assert ok
    assert detail["ocf_over_profit"] == pytest.approx(33.0 / 27.0, abs=0.01)
    assert detail["fcf_total"] == pytest.approx(24.0)


def test_cashflow_factor_fails_when_profit_not_backed():
    row = _value_row(ocf={"20251231": 4.0, "20241231": 4.0, "20231231": 4.0},
                     profit=10.0, profit_hist={"20251231": 10.0, "20241231": 9.0, "20231231": 8.0})
    ok, detail = st.cashflow_factor(row)
    assert not ok  # OCF/净利 0.4 —— 利润没有现金流背书


def test_cashflow_factor_fails_when_investing_burns_all_cash():
    row = _value_row(inv_hist={"20251231": -20.0, "20241231": -20.0, "20231231": -20.0})
    ok, detail = st.cashflow_factor(row)
    assert not ok  # FCF 合计 -39：经营现金流全被投资烧穿


# ---- 因子：动量突破（纯函数，K线进） ----

def test_ma_angle_flat_is_zero():
    ma = [10.0] * 30
    assert st.ma_angle_deg(ma) == pytest.approx(0.0, abs=0.5)


def test_ma_angle_steep_rise_over_30():
    ma = [10.0 * (1.006 ** i) for i in range(30)]  # 日涨0.6% → 角度>30°
    assert st.ma_angle_deg(ma) > 30


def test_momentum_hits_breakout():
    closes = [10 * 1.007 ** i for i in range(61)]  # 日涨0.7% → MA20角度>30°
    vols = [1000] * 60 + [3000]
    hits = st.momentum_hits(_kline(closes, vols))
    assert hits["above_ma20"] is True
    assert hits["high60"] is True
    assert hits["volume_ratio"] == pytest.approx(3.0)
    assert st.momentum_ok(hits)


def test_momentum_hits_rejects_downtrend():
    closes = [30 * 0.99 ** i for i in range(60)]
    hits = st.momentum_hits(_kline(closes))
    assert hits["above_ma20"] is False
    assert hits["high60"] is False
    assert not st.momentum_ok(hits)


# ---- 回测统计 ----

def test_stats_from_trades():
    stats = st.stats_from_trades([0.10, -0.05, 0.20, -0.04, 0.15])
    assert stats["n"] == 5
    assert stats["win_rate"] == pytest.approx(0.6)
    assert stats["payoff"] == pytest.approx(0.15 / 0.045, rel=0.01)
    assert stats["max_dd"] < 0  # 有回撤
    assert stats["sharpe"] != 0


def test_stats_empty_trades():
    stats = st.stats_from_trades([])
    assert stats["n"] == 0
    assert stats["win_rate"] is None


def test_strategy_verdict_thresholds():
    """夏普>1.0；胜率>60%需盈亏比≥1.5，50-60%≥1.8，40-50%≥2.5。"""
    assert st.strategy_verdict({"n": 30, "sharpe": 1.2, "win_rate": 0.65, "payoff": 1.6})["ok"]
    assert not st.strategy_verdict({"n": 30, "sharpe": 1.2, "win_rate": 0.65, "payoff": 1.2})["ok"]
    assert not st.strategy_verdict({"n": 30, "sharpe": 0.5, "win_rate": 0.65, "payoff": 2.0})["ok"]
    assert st.strategy_verdict({"n": 30, "sharpe": 1.1, "win_rate": 0.45, "payoff": 2.8})["ok"]
    assert not st.strategy_verdict({"n": 30, "sharpe": 1.1, "win_rate": 0.45, "payoff": 2.0})["ok"]
    assert st.strategy_verdict({"n": 30, "sharpe": 1.1, "win_rate": 0.55, "payoff": 1.9})["ok"]
    assert not st.strategy_verdict({"n": 5, "sharpe": 3.0, "win_rate": 0.8, "payoff": 3.0})["ok"]  # 样本<20不可信
    assert st.strategy_verdict({"n": 0, "sharpe": None, "win_rate": None, "payoff": None})["ok"] is False


# ---- 模拟交易回测（入场规则→逐笔收益） ----

def test_run_backtest_momentum_on_trend():
    """持续上升趋势+周期性放量：动量规则应产生多为正收益的交易。"""
    closes = [10 * 1.007 ** i for i in range(200)]
    vols = [3000 if i % 20 == 0 else 800 for i in range(200)]  # 周期放量触发入场
    trades = st.backtest_momentum(_kline(closes, vols), hold=10)
    assert len(trades) >= 3
    stats = st.stats_from_trades(trades)
    assert stats["win_rate"] > 0.5  # 单边上行里突破买入 majority 赚钱


def test_backtest_stop_loss_caps_loss():
    """触发了止损的交易，单笔亏损不应超过止损线太多（滑点容差）。"""
    up = [10 * 1.007 ** i for i in range(75)]
    down = [up[-1] * 0.97 ** i for i in range(1, 31)]  # 见顶后日跌3%（跨过-8%止损线）
    closes = up + down
    vols = [1000] * 70 + [3000] + [1000] * 34  # 唯一放量点在顶前
    trades = st.backtest_momentum(_kline(closes, vols), hold=20, stop=-0.08)
    assert trades, "应至少产生一笔交易"
    assert min(trades) >= -0.12  # -8% 止损 + 跳空容差


# ---- 排除项与人工清洗 ----

def test_liquidity_gate():
    assert st.liquidity_ok(_value_row()) is True
    assert st.liquidity_ok(_value_row(turnover_wan=2000.0)) is False
    assert st.liquidity_ok(_value_row(turnover_wan=None)) is False  # 无成交额数据=不可交易


def test_manual_review_items():
    """质押/减持/监管/预亏 数据面未覆盖 → 人工清洗清单固定输出。"""
    items = st.manual_review_items(_value_row())
    assert any("质押" in t for t in items)
    assert any("减持" in t for t in items)


# ---- 交易计划 ----

def test_trade_plan_fields():
    plan = st.trade_plan(price=10.0)
    assert plan["position"] == "30%底仓 + 30%突破加仓"
    assert "7.5%" in plan["stop"] or "止损" in plan["stop"]
    assert "15%" in plan["take_profit"]
    assert plan["stop_price"] == pytest.approx(9.25)
    assert "20日线" in plan["market_guard"]


# ---- 价值因子（模板A交叉） ----

def test_value_factors_all_pass():
    fac = st.value_factors(_value_row(), pe_pct=12.0, deduct_growth=22.0)
    assert fac["roe_ok"] and fac["growth_ok"] and fac["cash_ok"] and fac["pe_ok"]
    assert fac["passed"] == 4


def test_value_factors_pe_percentile_high_fails():
    fac = st.value_factors(_value_row(), pe_pct=85.0, deduct_growth=22.0)
    assert not fac["pe_ok"]
    assert fac["passed"] == 3


def test_value_factors_deduct_growth_fallback():
    """扣非增速缺失（F10 无数据）→ 回退净利润同比增速并在 detail 标注口径。"""
    fac = st.value_factors(_value_row(), pe_pct=12.0, deduct_growth=None)
    assert fac["growth_ok"] is True
    assert fac["growth_source"] == "净利润同比（扣非缺失回退）"


# ---- 策略门面 ----

def test_run_strategy_value(monkeypatch, tmp_path):
    from quant_sentiment import screener

    monkeypatch.setattr(screener, "rows_cached", lambda cache_dir, refresh=False: [_value_row()])
    monkeypatch.setattr(st, "rows_cached", screener.rows_cached)
    monkeypatch.setattr(st, "pe_percentile_cached", lambda codes, cache_dir: {"600001": 12.0})
    monkeypatch.setattr(st, "deduct_growth_cached", lambda codes, cache_dir: {"600001": 22.0})
    monkeypatch.setattr(st, "_stock_kline", lambda code, days, cache_dir=None: _kline([10 + 0.01 * i for i in range(300)]))
    monkeypatch.setattr(st, "market_guard", lambda cache_dir: {"above_ma20": True, "text": "大盘在20日线上"})

    body = st.run_strategy("value", str(tmp_path))
    assert body["key"] == "value"
    assert body["count"] == 1
    item = body["items"][0]
    assert item["factors"]["passed"] == 4
    assert item["plan"]["position"]
    assert body["market_guard"]["above_ma20"] is True
    assert body["backtest"]["stats"]["n"] >= 1  # 趋势回测有成交
    assert "回测" in body["backtest_note"]


def test_run_strategy_momentum(monkeypatch, tmp_path):
    from quant_sentiment import screener

    closes = [10 * 1.007 ** i for i in range(300)]
    vols = [1000] * 299 + [3000]
    monkeypatch.setattr(screener, "rows_cached", lambda cache_dir, refresh=False: [_value_row()])
    monkeypatch.setattr(st, "rows_cached", screener.rows_cached)
    monkeypatch.setattr(st, "_stock_kline", lambda code, days, cache_dir=None: _kline(closes, vols))
    monkeypatch.setattr(st, "market_guard", lambda cache_dir: {"above_ma20": False, "text": "大盘跌破20日线"})

    body = st.run_strategy("momentum", str(tmp_path))
    assert body["key"] == "momentum"
    assert body["count"] == 1
    item = body["items"][0]
    assert item["hits"]["above_ma20"] is True
    assert body["market_guard"]["above_ma20"] is False  # 防守开关透出


def test_run_strategy_unknown_key():
    with pytest.raises(ValueError):
        st.run_strategy("nope", None)
