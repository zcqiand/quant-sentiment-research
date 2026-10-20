"""买入指数测试：五维评分纯函数 + 行业归类 + 权重归一，离线全绿。"""

import pytest

import quant_sentiment.buy_index as bi


# ---- 1 持续性 ----

def test_dim_roe_stable_high():
    assert bi.dim_roe([22.0, 21.0, 19.0, 20.0, 18.0]) == 1.0  # 均值>=20 且 最低>=15


def test_dim_roe_moderate_stable():
    assert bi.dim_roe([16.0, 17.0, 15.5, 16.5, 12.5]) == 0.9  # 均值>=15 最低>=12


def test_dim_roe_one_year_spike():
    # 平时 5%，某年暴增 30% —— 昙花一现，压到 0.2 以下
    score = bi.dim_roe([30.0, 5.0, 4.0, 6.0, 5.0])
    assert score <= 0.2


def test_dim_roe_unstable_high_mean():
    assert bi.dim_roe([25.0, 24.0, 23.0, 22.0, 6.0]) == 0.45  # 均值高但某年跌破10


def test_dim_roe_low():
    assert bi.dim_roe([8.0, 9.0, 7.0]) == 0.2
    assert bi.dim_roe([3.0, 2.0, 4.0]) == 0.0


def test_dim_roe_insufficient_data():
    assert bi.dim_roe([20.0, 19.0]) is None  # 不足3年无法判断持续性


# ---- 2 杠杆 ----

def test_dim_debt():
    assert bi.dim_debt(25.0) == 1.0
    assert bi.dim_debt(40.0) == 0.85
    assert bi.dim_debt(55.0) == 0.5
    assert bi.dim_debt(65.0) == 0.25
    assert bi.dim_debt(80.0) == 0.0
    assert bi.dim_debt(None) is None


# ---- 3 估值 PEG ----

def test_dim_peg_growth():
    assert bi.dim_peg(20.0, 40.0) == 1.0  # PEG=0.5
    assert bi.dim_peg(20.0, 20.0) == 0.85  # PEG=1.0
    assert bi.dim_peg(30.0, 20.0) == 0.6  # PEG=1.5
    assert bi.dim_peg(40.0, 20.0) == 0.35  # PEG=2.0
    assert bi.dim_peg(60.0, 20.0) == 0.1  # PEG=3.0


def test_dim_peg_stalled_growth():
    assert bi.dim_peg(10.0, -5.0) == 0.15  # 增长失速
    assert bi.dim_peg(10.0, 0.0) == 0.15
    assert bi.dim_peg(-8.0, 30.0) == 0.1  # 亏损股 PEG 无意义


# ---- 3b 历史分位 ----

def test_dim_percentile():
    assert bi.dim_percentile(15) == 1.0
    assert bi.dim_percentile(40) == 0.85
    assert bi.dim_percentile(60) == 0.6
    assert bi.dim_percentile(75) == 0.35
    assert bi.dim_percentile(90) == 0.1
    assert bi.dim_percentile(None) is None


# ---- 4 现金流 ----

def test_dim_cash_strong():
    assert bi.dim_cash([130, 120, 110], [100, 100, 90]) == 1.0  # 均值 1.24


def test_dim_cash_negative_year():
    assert bi.dim_cash([100, -50, 80], [90, 90, 90]) == 0.0  # 任一年为负直接 0


def test_dim_cash_grades():
    assert bi.dim_cash([100, 100, 100], [100, 100, 100]) == 0.85  # 1.0
    assert bi.dim_cash([70, 70, 70], [100, 100, 100]) == 0.65  # 0.7
    assert bi.dim_cash([40, 40, 40], [100, 100, 100]) == 0.4  # 0.4
    assert bi.dim_cash([10, 10, 10], [100, 100, 100]) == 0.2  # 0.1


# ---- 5 行业 ----

def test_classify_industry():
    assert bi.classify_industry("金融-银行-股份制与城商行") == "neutral"
    assert bi.classify_industry("食品饮料-白酒") == "defensive"
    assert bi.classify_industry("医药生物-中药") == "defensive"
    assert bi.classify_industry("公用事业-电力") == "defensive"
    assert bi.classify_industry("黑色金属-钢铁") == "cyclical"
    assert bi.classify_industry("煤炭-焦炭") == "cyclical"
    assert bi.classify_industry("交通运输-航运") == "cyclical"
    assert bi.classify_industry("基础化工-氟化工") == "cyclical"
    assert bi.classify_industry("金融-证券") == "cyclical"
    assert bi.classify_industry("某未知行业") == "neutral"


def test_dim_industry():
    assert bi.dim_industry("食品饮料-白酒") == 1.0
    assert bi.dim_industry("金融-银行-股份制与城商行") == 0.6
    assert bi.dim_industry("黑色金属-钢铁") == 0.2
    assert bi.dim_industry(None) == 0.6


# ---- 合计 ----

def test_buy_index_total_renormalizes():
    dims = {"roe": 1.0, "debt": 0.85, "peg": 0.85, "percentile": None, "cash": 0.85, "industry": 1.0}
    total = bi.buy_index_total(dims)
    # 无分位时权重归一：(0.25+0.15+0.15+0.20+0.15) 权重 = 0.90
    expected = 100 * (0.25 + 0.15 * 0.85 + 0.15 * 0.85 + 0.20 * 0.85 + 0.15) / 0.90
    assert total == pytest.approx(expected, abs=0.2)  # 实现侧 round 到 1 位小数


def test_buy_label():
    assert bi.buy_label(80) == "适合买入研究"
    assert bi.buy_label(70) == "较适合研究"
    assert bi.buy_label(55) == "一般"
    assert bi.buy_label(40) == "偏弱"
    assert bi.buy_label(20) == "回避研究"


# ---- 白马决策层：一问三看三检验 ----

def test_latest_quarter_period():
    from datetime import date

    assert bi.latest_quarter_period(date(2026, 10, 20)) == "20260630"  # 三季报10/31才披完
    assert bi.latest_quarter_period(date(2026, 11, 1)) == "20260930"
    assert bi.latest_quarter_period(date(2026, 9, 1)) == "20260630"
    assert bi.latest_quarter_period(date(2026, 5, 1)) == "20251231"  # 年报4/30披完
    assert bi.latest_quarter_period(date(2026, 4, 30)) == "20250930"


def _wr(**kw):
    """构造一行白马榜条目（roe_hist 键近→远）。"""
    base = {
        "code": "600001", "name": "甲", "roe": 18.0, "pe_ttm": 15.0,
        "roe_hist": {"2025": 18.0, "2024": 17.5, "2023": 17.0, "2022": 18.5, "2021": 16.0},
        "growth": 20.0,
    }
    base.update(kw)
    return base


_GOOD_TREND = {"ok": True, "above": True, "rising": True, "above_ma250": True}


def test_decision_eval_all_pass():
    out = bi.decision_eval(_wr(), 20.0, _GOOD_TREND, 30.0, "食品饮料-白酒")
    assert out["checks"] == {"growth": True, "valuation": True, "trend": True}
    assert out["passed"] == 3
    assert "全过" in out["verdict"]
    assert out["warnings"] == []


def test_decision_eval_growth_fail_and_rearview_warning():
    out = bi.decision_eval(_wr(), -3.0, _GOOD_TREND, 30.0, "食品饮料-白酒")
    assert out["checks"]["growth"] is False
    assert out["passed"] == 2
    assert any(w["kind"] == "rearview" for w in out["warnings"])  # 增速为负=后视镜警报


def test_decision_eval_missing_data_not_fail_pass():
    out = bi.decision_eval(_wr(), None, None, None, None)  # 全缺数据：不算过也不算假警报
    assert out["checks"] == {"growth": None, "valuation": None, "trend": None}
    assert out["passed"] == 0


def test_decision_eval_warnings_kinds():
    # 周期顶：强周期行业 + ROE 处于 5 年高位
    cyc = _wr(industry_input=True, roe=30.0,
              roe_hist={"2025": 30.0, "2024": 12.0, "2023": 11.0, "2022": 12.5, "2021": 11.5})
    out = bi.decision_eval(cyc, 20.0, _GOOD_TREND, 30.0, "贵金属-黄金")
    assert any(w["kind"] == "cycle_top" for w in out["warnings"])

    # 昙花一现：5 年 ROE 最低 < 10
    flash = _wr(roe_hist={"2025": 25.0, "2024": 8.0, "2023": 6.0, "2022": 7.5, "2021": 7.0})
    out = bi.decision_eval(flash, 20.0, _GOOD_TREND, 30.0, "食品饮料-白酒")
    assert any(w["kind"] == "flash" for w in out["warnings"])

    # 价值陷阱：PE < 10 且年报增速为负
    trap = _wr(pe_ttm=8.0, growth=-5.0)
    out = bi.decision_eval(trap, 20.0, _GOOD_TREND, 30.0, "食品饮料-白酒")
    assert any(w["kind"] == "value_trap" for w in out["warnings"])


def test_decision_enrich_resorts_by_passed(tmp_path, monkeypatch):
    """决策层重排：三检全过的排前面；崩塌增速股被降位+打警报。"""
    import pandas as pd

    clean = _wr(code="600001", name="干净")
    sick = _wr(code="600002", name="病号", roe=25.0,
               roe_hist={"2025": 25.0, "2024": 24.0, "2023": 24.5, "2022": 25.5, "2021": 24.0})

    monkeypatch.setattr(bi, "percentiles_cached", lambda codes, cache_dir: {c: 30.0 for c in codes})
    monkeypatch.setattr(bi, "industry_cached", lambda pairs, cache_dir: {c: "食品饮料-白酒" for c, _ in pairs})
    monkeypatch.setattr(bi, "quarter_growth_cached",
                        lambda codes, cache_dir: {"600001": 20.0, "600002": -5.0})
    kline = pd.DataFrame({"close": [100.0 + i for i in range(300)]})
    monkeypatch.setattr("quant_sentiment.gateway.fetch_kline",
                        lambda symbol, days=300, cache_dir=None: kline)

    out = bi.decision_enrich([sick, clean], str(tmp_path))
    assert out[0]["code"] == "600001"  # 干净股（增速20→检验过）排前
    assert out[0]["passed"] == 3
    assert out[1]["warnings"]  # 病号：增速-5 → growth 检验不过 + 后视镜警报
    assert out[1]["checks"]["growth"] is False
