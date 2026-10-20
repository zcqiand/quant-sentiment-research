"""条件选股引擎测试：指标注册表 / 条件求值 / 组合筛选 / K线指标 / 规则回测，离线全绿。

统一条件引擎：所有选股方案（含内置模板）都由「指标 + 条件」组合而成，
不做每方案一套硬编码。数据缺失的指标一律「不命中且标注」，不当正常值。
"""

import math

import pandas as pd
import pytest

from quant_sentiment import conditions as cond


def _kline(closes, vols=None, amounts=None, start="2024-01-01"):
    """合成日K：date/open/close/high/low/volume[/amount]。"""
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


def _row(**kw):
    """候选池行 fixture（v4 schema 关键字段）。"""
    base = {
        "code": "600001", "name": "甲", "industry": "银行", "price": 10.0,
        "turnover_wan": 20000.0, "pe_ttm": 15.0, "pb": 1.5, "mcap_yi": 200.0,
        "roe": 18.0, "debt_ratio": 40.0,
        "ocf_hist": {"20251231": 12.0, "20241231": 11.0, "20231231": 10.0},
        "inv_hist": {"20251231": -3.0, "20241231": -3.0, "20231231": -3.0},
        "profit": 10.0, "profit_hist": {"20251231": 10.0, "20241231": 9.0, "20231231": 8.0},
        "roe_hist": {"20251231": 18.0, "20241231": 17.0, "20231231": 16.0},
        "growth": 25.0, "revenue_growth": 12.0,
        "dps": {"20251231": 0.5, "20241231": 0.5, "20231231": 0.5},
        "div_yield": 5.0, "div_yield_latest": 5.0,
    }
    base.update(kw)
    return base


# ---- 指标注册表 ----

def test_metric_registry_shape():
    """31 个指标、五大类、每个都带口径说明与来源类型。"""
    assert len(cond.METRICS) == 31
    cats = {m["category"] for m in cond.METRICS.values()}
    assert cats == {"基础信息", "估值", "财务", "技术", "风险过滤"}
    for key, m in cond.METRICS.items():
        assert m["name"] and m["caliber"], key
        assert m["kind"] in {"row", "kline", "slow"}, key
        assert m["ops"], key


def test_metric_registry_kinds():
    assert cond.METRICS["pe_ttm"]["kind"] == "row"
    assert cond.METRICS["above_ma20"]["kind"] == "kline"
    assert cond.METRICS["pe_pct"]["kind"] == "slow"
    assert cond.METRICS["deduct_growth"]["kind"] == "slow"


def test_metric_registry_v5_metrics():
    """四大组合所需新指标：流通市值 / 上市满2年 / 近20日日均成交额 / 近20日波动率。"""
    assert cond.METRICS["float_mcap_yi"]["kind"] == "row"
    assert cond.METRICS["listed_2y"]["kind"] == "slow"
    assert cond.METRICS["avg_amount20_yi"]["kind"] == "kline"
    assert cond.METRICS["vol20"]["kind"] == "kline"


# ---- 行指标取值（含派生口径） ----

def test_metric_value_row_basic():
    vals = cond.metric_value(_row(), "pe_ttm", {})
    assert vals == 15.0
    assert cond.metric_value(_row(), "industry", {}) == "银行"


def test_metric_value_derived():
    row = _row()
    assert cond.metric_value(row, "roe_min3", {}) == 16.0  # 近3年报最低
    assert cond.metric_value(row, "roe_mean3", {}) == pytest.approx(17.0)
    assert cond.metric_value(row, "profit_yi", {}) == pytest.approx(10.0 / 1e8)  # 元 → 亿
    assert cond.metric_value(row, "ocf_over_profit", {}) == pytest.approx(33.0 / 27.0, abs=0.01)
    assert cond.metric_value(row, "fcf_yi", {}) == pytest.approx(24.0 / 1e8, abs=1e-12)  # 元 → 亿


def test_metric_value_missing_data_returns_none():
    """缺失不当正常值：roe_hist 只有2年 → roe_min3=None。"""
    row = _row(roe_hist={"20251231": 18.0, "20241231": 17.0})
    assert cond.metric_value(row, "roe_min3", {}) is None
    assert cond.metric_value(_row(debt_ratio=None), "debt_ratio", {}) is None


def test_metric_value_from_vals_map():
    """kline/slow 指标从预取值表拿。"""
    vals = {"600001": {"above_ma20": 1.0, "pe_pct": 12.0}}
    assert cond.metric_value(_row(), "above_ma20", vals) == 1.0
    assert cond.metric_value(_row(), "pe_pct", vals) == 12.0
    assert cond.metric_value(_row(), "pe_pct", {}) is None


# ---- 单条件求值 ----

def test_eval_ops_numeric():
    hit, known, _ = cond.eval_condition({"metric": "pe_ttm", "op": "<", "value": 20}, 15.0)
    assert hit and known
    hit, known, _ = cond.eval_condition({"metric": "pe_ttm", "op": ">=", "value": 20}, 15.0)
    assert not hit and known
    hit, _, _ = cond.eval_condition({"metric": "roe", "op": "between", "min": 10, "max": 20}, 18.0)
    assert hit
    hit, _, _ = cond.eval_condition({"metric": "roe", "op": "between", "min": 10, "max": 20}, 25.0)
    assert not hit


def test_eval_ops_bool_and_text():
    hit, _, _ = cond.eval_condition({"metric": "above_ma20", "op": "eq", "value": 1}, 1.0)
    assert hit
    hit, _, _ = cond.eval_condition({"metric": "industry", "op": "contains", "value": "银"}, "银行")
    assert hit
    hit, _, _ = cond.eval_condition({"metric": "industry", "op": "contains", "value": "银"}, "白酒")
    assert not hit


def test_eval_negate_is_exclusion():
    """negate=排除条件：命中变不命中；用于「排除银行」。"""
    c = {"metric": "industry", "op": "contains", "value": "银", "negate": True}
    hit, _, _ = cond.eval_condition(c, "白酒")
    assert hit
    hit, _, _ = cond.eval_condition(c, "银行")
    assert not hit


def test_eval_missing_value_not_hit_even_negated():
    """数据缺失：不命中；negate 也不命中（缺失不能当「通过排除」）。"""
    c = {"metric": "pe_pct", "op": "<", "value": 20}
    hit, known, _ = cond.eval_condition(c, None)
    assert not hit and not known
    hit, known, _ = cond.eval_condition({**c, "negate": True}, None)
    assert not hit and not known


# ---- 规则校验 ----

def test_validate_rule_ok():
    rule = {
        "logic": "all",
        "conditions": [
            {"metric": "pe_ttm", "op": "between", "min": 0, "max": 20},
            {"metric": "roe", "op": ">=", "value": 10},
        ],
        "rank": {"metric": "div_yield", "top_pct": 30, "order": "desc"},
    }
    assert cond.validate_rule(rule) == []


def test_validate_rule_errors():
    errs = cond.validate_rule({"conditions": [{"metric": "nope", "op": ">", "value": 1}]})
    assert any("nope" in e for e in errs)
    errs = cond.validate_rule({"conditions": [{"metric": "roe", "op": "??"}]})
    assert any("op" in e or "运算符" in e for e in errs)
    errs = cond.validate_rule({"conditions": [{"metric": "roe", "op": "between", "min": 1}]})
    assert any("between" in e for e in errs)
    errs = cond.validate_rule({"conditions": [], "rank": {"metric": "nope", "top_pct": 10}})
    assert any("nope" in e for e in errs)


# ---- 组合筛选：AND / OR / 排名 / 入选原因 ----

def _rows_three():
    return [
        _row(),  # 甲：便宜高息银行
        _row(code="600002", name="乙", pe_ttm=50.0, div_yield=0.5, industry="白酒"),  # 贵
        _row(code="600003", name="丙", pe_ttm=10.0, div_yield=8.0, industry="银行", debt_ratio=None),
    ]


def test_screen_and_logic_with_reasons():
    rule = {
        "logic": "all",
        "conditions": [
            {"metric": "pe_ttm", "op": "between", "min": 0, "max": 20},
            {"metric": "div_yield", "op": ">=", "value": 3},
        ],
    }
    out = cond.screen(_rows_three(), rule)
    assert out["count"] == 2  # 甲、丙
    item = out["items"][0]
    assert len(item["reasons"]) == 2 and all("✓" in r for r in item["reasons"])
    assert item["values"]["pe_ttm"] == 15.0


def test_screen_any_logic():
    rule = {
        "logic": "any",
        "conditions": [
            {"metric": "pe_ttm", "op": "<", "value": 12},
            {"metric": "div_yield", "op": ">=", "value": 6},
        ],
    }
    out = cond.screen(_rows_three(), rule)
    # 甲：pe15 不<12，div5 不>=6 → 不中；乙全不中；丙 pe10<12 中
    assert [i["code"] for i in out["items"]] == ["600003"]


def test_screen_rank_top_pct():
    """排名条件：过滤后按指标排序取前 N%，缺失值排最后。"""
    rule = {
        "conditions": [{"metric": "pe_ttm", "op": "between", "min": 0, "max": 20}],
        "rank": {"metric": "div_yield", "top_pct": 50, "order": "desc"},
    }
    out = cond.screen(_rows_three(), rule)
    # 甲(5%)、丙(8%) 过滤，前50%=1只 → 丙（8%更高）
    assert out["count"] == 1
    assert out["items"][0]["code"] == "600003"
    assert any("排名" in r for r in out["items"][0]["reasons"])


def test_screen_rank_missing_goes_last():
    rows = [_row(), _row(code="600003", name="丙", div_yield=8.0)]
    rule = {
        "conditions": [{"metric": "pe_ttm", "op": ">=", "value": 0}],
        "rank": {"metric": "div_yield", "top_pct": 50, "order": "desc"},
    }
    out = cond.screen(rows, rule)
    assert out["items"][0]["code"] == "600003"  # 甲 div_yield 正常但丙更高；乙缺→最后
    # 甲 div_yield=5.0 存在；换成缺失场景：
    rows2 = [_row(div_yield=None), _row(code="600003", name="丙", div_yield=8.0)]
    out2 = cond.screen(rows2, rule)
    assert out2["count"] == 1 and out2["items"][0]["code"] == "600003"


def test_screen_exclusion_via_negate():
    rule = {
        "conditions": [
            {"metric": "pe_ttm", "op": "between", "min": 0, "max": 20},
            {"metric": "industry", "op": "contains", "value": "银", "negate": True},
        ],
    }
    out = cond.screen(_rows_three(), rule)
    assert out["count"] == 0  # 甲丙都是银行被排除，乙 PE 不达标


# ---- K线技术指标 ----

def test_compute_kline_metrics_breakout():
    closes = [10 * 1.007 ** i for i in range(61)]
    vols = [1000] * 60 + [3000]
    amounts = [5e7] * 61
    m = cond.compute_kline_metrics(_kline(closes, vols, amounts))
    assert m["above_ma20"] == 1.0
    assert m["new_high60"] == 1.0
    assert m["vol_ratio"] == pytest.approx(3.0)
    assert m["ret60"] > 0
    assert m["ma20_angle"] > 30
    assert m["amount_yi"] == pytest.approx(0.5, abs=0.01)  # 5e7 元 = 0.5亿


def test_compute_kline_metrics_downtrend():
    closes = [30 * 0.99 ** i for i in range(130)]
    m = cond.compute_kline_metrics(_kline(closes))
    assert m["above_ma20"] == 0.0
    assert m["new_high60"] == 0.0
    assert m["ret60"] < 0
    assert m["ret120"] < 0


def test_compute_kline_metrics_short_series_returns_none():
    """K线不足（<21根）→ 技术指标全 None，不当 0。"""
    m = cond.compute_kline_metrics(_kline([10.0] * 15))
    assert m["above_ma20"] is None
    assert m["ret60"] is None


def test_compute_kline_metrics_no_amount_column():
    m = cond.compute_kline_metrics(_kline([10 * 1.007 ** i for i in range(61)]))
    assert m["amount_yi"] is None


# ---- 规则可回测性（防未来数据泄漏） ----

def test_rule_backtestable_kline_only():
    rule = {"conditions": [{"metric": "above_ma20", "op": "eq", "value": 1},
                           {"metric": "amount_yi", "op": ">=", "value": 0.3}]}
    ok, why = cond.rule_backtestable(rule)
    assert ok


def test_rule_backtestable_rejects_fundamental():
    """财务/估值/慢速条件依赖报告期横截面快照，历史重放会引入未来数据——拒绝回测。"""
    rule = {"conditions": [{"metric": "pe_ttm", "op": "<", "value": 20},
                           {"metric": "above_ma20", "op": "eq", "value": 1}]}
    ok, why = cond.rule_backtestable(rule)
    assert not ok and "泄漏" in why or not ok


# ---- 规则回测（信号次日收盘入场，持有N日或止损） ----

def test_backtest_rule_trend_uptrend():
    rule = {"conditions": [{"metric": "above_ma20", "op": "eq", "value": 1},
                           {"metric": "new_high60", "op": "eq", "value": 1}]}
    closes = [10 * 1.005 ** i for i in range(200)]
    klines = {"600001": _kline(closes)}
    out = cond.backtest_rule(rule, klines, hold=10)
    assert out["stats"]["n"] >= 3
    assert out["stats"]["win_rate"] > 0.5  # 单边上行多数交易赚钱
    assert out["verdict"]


def test_backtest_rule_stop_loss_caps_loss():
    rule = {"conditions": [{"metric": "new_high60", "op": "eq", "value": 1}]}
    up = [10 * 1.007 ** i for i in range(75)]
    down = [up[-1] * 0.97 ** i for i in range(1, 31)]
    closes = up + down
    df = _kline(closes)
    out = cond.backtest_rule(rule, {"600001": df}, hold=20, stop=-0.08)
    assert out["stats"]["n"] >= 1
    assert out["trades"] and min(out["trades"]) >= -0.12  # -8% 止损 + 跳空容差


# ---- 内置模板 ----

def test_presets_valid_and_runnable():
    """4 个组合都是合法规则，且能在候选池行上直接跑。"""
    assert len(cond.PRESETS) == 4
    assert [p["key"] for p in cond.PRESETS] == ["roe_pe", "roe_pb", "small_quality", "low_vol"]
    for p in cond.PRESETS:
        assert cond.validate_rule(p["rule"]) == [], p["name"]
        out = cond.screen(_rows_three(), p["rule"])
        assert "count" in out and "items" in out


def test_preset_all_fundamental_not_backtestable():
    """四个组合都含财务/估值条件 → 均不可回测（诚实声明）；历史验证同门拒绝。"""
    for p in cond.PRESETS:
        ok, why = cond.rule_backtestable(p["rule"])
        assert not ok and "泄漏" in why, p["key"]


def test_preset_roe_pe_shape():
    """组合1 高ROE+低PE：ROE均值门槛定PE上限、净利同比为正、剔周期行业、上市满2年。"""
    by_key = {p["key"]: p for p in cond.PRESETS}
    rule = by_key["roe_pe"]["rule"]
    metrics = {c["metric"] for c in rule["conditions"]}
    assert {"roe_mean3", "pe_ttm", "growth", "listed_2y"} <= metrics
    excl = [c for c in rule["conditions"] if c.get("negate")]
    assert {c["metric"] for c in excl} == {"industry"}
    # 关键词必须与东财「所处行业」实际取值命中（v5 live 验证）：申万三级名，
    # 有色=工业金属/能源金属/贵金属/小金属/金属新材料，钢铁=普钢/特钢/冶钢原料
    kws = {c["value"] for c in excl}
    assert {"煤炭", "工业金属", "能源金属", "贵金属", "小金属", "金属新材料",
            "普钢", "特钢", "冶钢原料"} <= kws
    pe = next(c for c in rule["conditions"] if c["metric"] == "pe_ttm")
    assert pe["op"] == "between" and pe["min"] == 0


def test_preset_exclude_keywords_match_real_industries():
    """剔除关键词逐个对 v5 行业实际取值核对——「有色」「钢铁」在东财列里零命中，禁止回潮。"""
    real = {"煤炭开采", "工业金属", "能源金属", "贵金属", "小金属", "金属新材料",
            "普钢", "特钢Ⅱ", "冶钢原料", "银行Ⅱ", "保险Ⅱ", "证券Ⅱ",
            "房地产开发", "房地产服务", "白色家电", "非金属材料Ⅱ"}
    excl_all = set()
    for p in cond.PRESETS:
        excl_all |= {c["value"] for c in p["rule"]["conditions"]
                     if c.get("negate") and c["metric"] == "industry"}
    for kw in excl_all:
        assert any(kw in v for v in real), f"剔除关键词「{kw}」在任何真实行业上都零命中"


def test_preset_roe_pb_shape():
    """组合2 高ROE低PB：ROE>12、0<PB<2、净利同比为正、负债率<60、剔金融地产。"""
    by_key = {p["key"]: p for p in cond.PRESETS}
    rule = by_key["roe_pb"]["rule"]
    conds = {(c["metric"], c.get("negate", False)): c for c in rule["conditions"]}
    assert conds[("roe", False)]["value"] == 12
    pb = conds[("pb", False)]
    assert pb["op"] == "between" and pb["min"] == 0 and pb["max"] == 2
    assert conds[("debt_ratio", False)]["value"] == 60
    assert ("industry", True) in conds  # 剔除金融地产


def test_preset_small_quality_shape():
    """组合3 小市值+质量：流通市值20-80亿、日均成交额>0.3亿、0<PE<40、ROE>5、负债率<70。"""
    by_key = {p["key"]: p for p in cond.PRESETS}
    rule = by_key["small_quality"]["rule"]
    conds = {c["metric"]: c for c in rule["conditions"]}
    assert conds["float_mcap_yi"]["op"] == "between"
    assert conds["float_mcap_yi"]["min"] == 20 and conds["float_mcap_yi"]["max"] == 80
    assert conds["avg_amount20_yi"]["value"] == 0.3
    assert conds["pe_ttm"]["min"] == 0 and conds["pe_ttm"]["max"] == 40
    assert conds["roe"]["value"] == 5
    assert conds["debt_ratio"]["value"] == 70
    assert "listed_2y" in conds


def test_preset_low_vol_shape():
    """组合4 防御低波：0<PE<15、0<PB<1.5、负债率<50，按近20日波动率升序取前30%。"""
    by_key = {p["key"]: p for p in cond.PRESETS}
    rule = by_key["low_vol"]["rule"]
    conds = {c["metric"]: c for c in rule["conditions"]}
    assert conds["pe_ttm"]["min"] == 0 and conds["pe_ttm"]["max"] == 15
    assert conds["pb"]["min"] == 0 and conds["pb"]["max"] == 1.5
    assert conds["debt_ratio"]["value"] == 50
    assert rule["rank"] == {"metric": "vol20", "top_pct": 30, "order": "asc"}


# ---- v5 新K线指标：近20日日均成交额 / 近20日波动率 ----

def test_kline_metrics_avg_amount20_and_vol20():
    closes = [100 * (1 + (0.01 if i % 2 else -0.01)) for i in range(60)]
    amounts = [1e8] * 40 + [2e8] * 20
    m = cond.compute_kline_metrics(_kline(closes, amounts=amounts))
    assert m["avg_amount20_yi"] == pytest.approx(2.0)  # 近20日全是 2e8 → 2 亿
    rets = [closes[i] / closes[i - 1] - 1 for i in range(len(closes) - 19, len(closes))]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    assert m["vol20"] == pytest.approx(math.sqrt(var) * 100, abs=0.01)


def test_kline_metrics_avg_amount20_and_vol20_missing():
    m = cond.compute_kline_metrics(_kline([10 + i for i in range(15)]))  # <20/21 根
    assert m["avg_amount20_yi"] is None
    assert m["vol20"] is None
    m2 = cond.compute_kline_metrics(_kline([10 + i for i in range(60)]))  # 无 amount 列
    assert m2["avg_amount20_yi"] is None
    assert m2["vol20"] is not None  # 波动率只依赖收盘价


# ---- v5 新慢指标：上市满2年（K线根数推断） ----

def test_listed_2y_cached(monkeypatch, tmp_path):
    monkeypatch.setattr(cond, "_stock_kline",
                        lambda code, days, cache_dir=None: _kline([10] * days))
    out = cond.listed_2y_cached(["600001", "600002"], str(tmp_path))
    assert out["600001"] == 1  # 550 根 ≥ 480 → 满2年
    monkeypatch.setattr(cond, "_stock_kline",
                        lambda code, days, cache_dir=None: _kline([10] * 300))
    out = cond.listed_2y_cached(["600003"], str(tmp_path))
    assert out["600003"] == 0  # 300 根 < 480 → 上市不满2年

    def _boom(code, days, cache_dir=None):
        raise RuntimeError("net down")

    monkeypatch.setattr(cond, "_stock_kline", _boom)
    out = cond.listed_2y_cached(["600009"], str(tmp_path))
    assert out["600009"] is None  # 拉不到 → 缺失，不误判
    assert any("listed2y_" in f.name for f in tmp_path.iterdir())  # 按天缓存落盘


# ---- 编排：run_screen（两段式补数） ----

_GUARD = {"above_ma20": True, "text": "大盘在20日线上"}


def test_run_screen_row_only_rule(monkeypatch, tmp_path):
    monkeypatch.setattr(cond, "rows_cached", lambda cache_dir, refresh=False: _rows_three())
    monkeypatch.setattr(cond, "market_guard", lambda cache_dir: _GUARD)
    rule = {"conditions": [{"metric": "pe_ttm", "op": "between", "min": 0, "max": 20}]}
    out = cond.run_screen(rule, str(tmp_path))
    assert out["universe"] == 3
    assert out["count"] == 2
    assert out["kline_scanned"] == 0  # 没用K线指标就不扫K线
    assert out["items"][0]["reasons"]


def test_run_screen_with_kline_metric(monkeypatch, tmp_path):
    monkeypatch.setattr(cond, "rows_cached", lambda cache_dir, refresh=False: _rows_three())
    monkeypatch.setattr(cond, "market_guard", lambda cache_dir: _GUARD)
    closes = [10 * 1.007 ** i for i in range(200)]
    monkeypatch.setattr(cond, "_stock_kline",
                        lambda code, days, cache_dir=None: _kline(closes))
    rule = {"conditions": [{"metric": "above_ma20", "op": "eq", "value": 1}]}
    out = cond.run_screen(rule, str(tmp_path))
    assert out["kline_scanned"] == 3
    assert out["count"] == 3  # 单边上行全站上MA20


def test_run_screen_slow_metric_second_pass(monkeypatch, tmp_path):
    """慢指标（PE分位）：先粗筛，存活者逐股补数后再终筛。"""
    monkeypatch.setattr(cond, "rows_cached", lambda cache_dir, refresh=False: _rows_three())
    monkeypatch.setattr(cond, "market_guard", lambda cache_dir: _GUARD)
    monkeypatch.setattr(cond, "pe_percentile_cached",
                        lambda codes, cache_dir: {"600001": 12.0, "600003": 85.0})
    rule = {
        "conditions": [
            {"metric": "pe_ttm", "op": "between", "min": 0, "max": 20},
            {"metric": "pe_pct", "op": "<", "value": 20},
        ],
    }
    out = cond.run_screen(rule, str(tmp_path))
    assert out["count"] == 1 and out["items"][0]["code"] == "600001"
    assert out["slow_fetched"] >= 2  # 甲丙（PE达标者）都补了分位


def test_run_screen_listed_2y_second_pass(monkeypatch, tmp_path):
    """上市满2年（慢指标）与其他条件同走两段式：只给 pending 行补数。"""
    monkeypatch.setattr(cond, "rows_cached", lambda cache_dir, refresh=False: _rows_three())
    monkeypatch.setattr(cond, "market_guard", lambda cache_dir: _GUARD)
    seen: list[list[str]] = []
    monkeypatch.setattr(cond, "listed_2y_cached",
                        lambda codes, cache_dir: (seen.append(list(codes)), {c: 1 for c in codes})[1])
    rule = {
        "conditions": [
            {"metric": "pe_ttm", "op": "between", "min": 0, "max": 20},
            {"metric": "listed_2y", "op": "eq", "value": 1},
        ],
    }
    out = cond.run_screen(rule, str(tmp_path))
    assert out["slow_fetched"] == 2  # 只补 PE 达标的甲丙，不补贵的乙
    assert out["count"] == 2


def test_run_screen_invalid_rule_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(cond, "rows_cached", lambda cache_dir, refresh=False: [])
    with pytest.raises(ValueError):
        cond.run_screen({"conditions": [{"metric": "nope", "op": ">", "value": 1}]}, str(tmp_path))


# ---- 编排：run_backtest ----

def test_run_backtest_orchestration(monkeypatch, tmp_path):
    rows = _rows_three()
    monkeypatch.setattr(cond, "rows_cached", lambda cache_dir, refresh=False: rows)
    closes = [10 * 1.005 ** i for i in range(200)]
    monkeypatch.setattr(cond, "_stock_kline", lambda code, days, cache_dir=None: _kline(closes))
    rule = {"conditions": [{"metric": "above_ma20", "op": "eq", "value": 1}]}
    out = cond.run_backtest(rule, str(tmp_path))
    assert out["stats"]["n"] >= 1
    assert out["n_stocks"] == 3
    assert "口径" in out["note"]


def test_run_backtest_refuses_fundamental_rule(monkeypatch, tmp_path):
    monkeypatch.setattr(cond, "rows_cached", lambda cache_dir, refresh=False: _rows_three())
    rule = {"conditions": [{"metric": "pe_ttm", "op": "<", "value": 20}]}
    with pytest.raises(ValueError) as ei:
        cond.run_backtest(rule, str(tmp_path))
    assert "泄漏" in str(ei.value) or "回测" in str(ei.value)


# ---- 保留件：统计/判定/计划/人工清洗/大盘防守 ----

def test_stats_from_trades():
    stats = cond.stats_from_trades([0.10, -0.05, 0.20, -0.04, 0.15])
    assert stats["n"] == 5
    assert stats["win_rate"] == pytest.approx(0.6)
    assert stats["payoff"] == pytest.approx(0.15 / 0.045, rel=0.01)
    assert stats["max_dd"] < 0


def test_strategy_verdict_thresholds():
    assert cond.strategy_verdict({"n": 30, "sharpe": 1.2, "win_rate": 0.65, "payoff": 1.6})["ok"]
    assert not cond.strategy_verdict({"n": 30, "sharpe": 0.5, "win_rate": 0.65, "payoff": 2.0})["ok"]
    assert not cond.strategy_verdict({"n": 5, "sharpe": 3.0, "win_rate": 0.8, "payoff": 3.0})["ok"]


def test_trade_plan_and_review():
    plan = cond.trade_plan(price=10.0)
    assert plan["stop_price"] == pytest.approx(9.25)
    items = cond.manual_review_items({"code": "600001", "name": "甲"})
    assert any("质押" in t for t in items) and any("减持" in t for t in items)


def test_sma_and_ma_angle_kept():
    assert cond.sma([1.0] * 30, 20)[-1] == 1.0
    assert cond.ma_angle_deg([10.0 * (1.006 ** i) for i in range(30)]) > 30
