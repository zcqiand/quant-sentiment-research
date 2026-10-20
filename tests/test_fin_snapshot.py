"""历史财务横截面快照：公告日期门控的 point-in-time 指标（让含财务条件的规则可跑历史验证）。"""

from datetime import date

import pandas as pd
import pytest

from quant_sentiment import fin_snapshot as fs


def _ts(s):
    return pd.Timestamp(s)


def _yjbb(period, rows):
    """rows: [(code, announce, eps, bps, roe, growth, rev_growth, industry)] → 报告期整表。"""
    return pd.DataFrame(
        rows,
        columns=["股票代码", "最新公告日期", "每股收益", "每股净资产", "净资产收益率",
                 "净利润-同比增长", "营业总收入-同比增长", "所处行业"],
    ).assign(报告期=period)


def _zcfz(period, rows):
    """rows: [(code, announce, debt_ratio)]。"""
    return pd.DataFrame(rows, columns=["股票代码", "公告日期", "资产负债率"]).assign(报告期=period)


# ---- 报告期推算 ----

def test_quarter_ends_back():
    # asof 2026-08-29，20 天披露缓冲 → 候选截至 2026-08-09：近 4 个季度末
    assert fs.quarter_ends_back(_ts("2026-08-29"), 4) == ["20260630", "20260331", "20251231", "20250930"]


def test_quarter_ends_back_excludes_too_fresh():
    # 2026-06-30 结束的季度在 7 月初还没到披露期，不入候选
    assert fs.quarter_ends_back(_ts("2026-07-05"), 2) == ["20260331", "20251231"]
    assert "20260630" not in fs.quarter_ends_back(_ts("2026-07-05"), 6)


def test_annual_periods_three_years():
    assert fs.annual_periods(_ts("2026-08-29")) == ["20251231", "20241231", "20231231"]
    # 年初时最近年报可能尚未到披露期 → 候选里只有更早的
    assert fs.annual_periods(_ts("2024-02-01")) == ["20221231", "20211231", "20201231"]


# ---- 快照构建（纯函数） ----

def _three_annuals():
    return {
        "20251231": _yjbb("20251231", [
            ("600001", "2026-03-10", 2.0, 5.0, 22.0, 12.0, 10.0, "白色家电"),
            ("600002", "2026-04-20", 1.0, 3.0, 10.0, -5.0, 2.0, "普钢"),
        ]),
        "20241231": _yjbb("20241231", [
            ("600001", "2025-03-05", 1.8, 4.5, 21.0, 8.0, 7.0, "白色家电"),
            ("600002", "2025-04-15", 0.9, 2.8, 9.0, -3.0, 1.0, "普钢"),
        ]),
        "20231231": _yjbb("20231231", [
            ("600001", "2024-03-01", 1.5, 4.0, 20.0, 6.0, 5.0, "白色家电"),
            ("600002", "2024-04-10", 0.8, 2.5, 8.0, 2.0, 0.5, "普钢"),
        ]),
    }


ANNUALS = ["20251231", "20241231", "20231231"]


def test_roe_hist_annual_gated_by_announce():
    # asof 2026-03-15：600001 的 2025 年报已公告（3-10）→ 3 个年报齐
    snaps = fs.build_snapshots(_ts("2026-03-15"), _three_annuals(), {}, ANNUALS)
    s = snaps["600001"]
    assert s["roe"] == 22.0
    assert list(s["roe_hist"].keys()) == ["20251231", "20241231", "20231231"]
    assert s["roe_hist"]["20251231"] == 22.0
    # 600002 的 2025 年报 4-20 才公告 → 只有 2 个年报，roe 取最新可得，均值缺失
    s2 = snaps["600002"]
    assert s2["roe"] == 9.0  # 最新可得年报是 20241231
    assert s2["roe_hist"] is None  # 不足 3 个年报 → 派生均值将是缺失，不当 0
    assert s2["growth"] == -3.0


def test_roe_mean3_hand_computed():
    """roe_mean3/roe_min3 由 conditions._DERIVED 从 roe_hist 派生，这里验原料。"""
    snaps = fs.build_snapshots(_ts("2026-08-29"), _three_annuals(), {}, ANNUALS)
    h = snaps["600001"]["roe_hist"]
    assert h == {"20251231": 22.0, "20241231": 21.0, "20231231": 20.0}
    assert round(sum(h.values()) / 3, 2) == 21.0


def test_announce_after_asof_excluded_everywhere():
    # asof 早于一切公告 → 该股无任何可用年报 → 全缺
    snaps = fs.build_snapshots(_ts("2023-06-01"), _three_annuals(), {}, ANNUALS)
    assert snaps["600001"]["roe"] is None
    assert snaps["600001"]["roe_hist"] is None


def test_ttm_eps_and_pe_hand_computed():
    yjbb = dict(_three_annuals())
    # 2026 中报：eps 累计 1.0；2025 中报：0.8 → TTM = 2.0(2025年报) − 0.8 + 1.0 = 2.2
    yjbb["20260630"] = _yjbb("20260630", [("600001", "2026-08-20", 1.0, 5.2, 11.0, 3.0, 2.0, "白色家电")])
    yjbb["20250630"] = _yjbb("20250630", [("600001", "2025-08-15", 0.8, 4.8, 10.5, 4.0, 3.0, "白色家电")])
    snaps = fs.build_snapshots(_ts("2026-08-29"), yjbb, {}, ANNUALS)
    s = snaps["600001"]
    assert s["eps_ttm"] == 2.2
    assert s["bps"] == 5.2  # 最新披露期的每股净资产
    # pe = 当时收盘 / eps_ttm（在 analyze_hist 里算）；这里验 eps 传递
    assert s["industry"] == "白色家电"


def test_ttm_missing_prev_year_quarter_is_none():
    yjbb = dict(_three_annuals())
    yjbb["20260630"] = _yjbb("20260630", [("600001", "2026-08-20", 1.0, 5.2, 11.0, 3.0, 2.0, "白色家电")])
    # 缺 20250630 → TTM 算不出 → None（不当 0）
    snaps = fs.build_snapshots(_ts("2026-08-29"), yjbb, {}, ANNUALS)
    assert snaps["600001"]["eps_ttm"] is None


def test_debt_ratio_gated_by_zcfz_announce():
    zcfz = {
        "20260630": _zcfz("20260630", [("600001", "2026-08-25", 55.0)]),
        "20250331": _zcfz("20250331", [("600001", "2025-04-25", 60.0)]),
    }
    snaps = fs.build_snapshots(_ts("2026-08-29"), _three_annuals(), zcfz, ANNUALS)
    assert snaps["600001"]["debt_ratio"] == 55.0
    # asof 早于中报公告 → 用上一期
    snaps2 = fs.build_snapshots(_ts("2026-06-01"), _three_annuals(), zcfz, ANNUALS)
    assert snaps2["600001"]["debt_ratio"] == 60.0


# ---- 缓存往返（回归：前导零代码不能丢） ----

def test_cached_table_roundtrip_announce_date_survives(tmp_path):
    """to_json 默认 date_format=epoch 会把公告日期写成 1773100800000——
    读回解析失败 = 全市场「未公告」，roe_hist/eps_ttm 集体蒸发（2026-10-20 事故）。
    akshare 实况是 object 列装 datetime.date，与 datetime64 一样会被写成 epoch。"""
    df = _yjbb("20251231", [("600001", "2026-03-10", 2.0, 5.0, 22.0, 12.0, 10.0, "白色家电")])
    df["最新公告日期"] = df["最新公告日期"].map(date.fromisoformat)
    fs._cached_table("yjbb", "20251231", str(tmp_path), lambda p: df)  # 首次真拉（返回原始 df）
    df2 = fs._cached_table("yjbb", "20251231", str(tmp_path), lambda p: df)  # 第二次走缓存回读
    ts = fs._ann_ts(df2.loc[0, "最新公告日期"])
    assert ts is not None
    assert ts == pd.Timestamp("2026-03-10").normalize()


def test_ann_ts_handles_epoch_ms():
    """旧毒缓存里公告日期是 epoch 毫秒——读得出来就解析，别当「未公告」。"""
    expect = pd.to_datetime(1774915200000, unit="ms").normalize()
    assert fs._ann_ts("1774915200000") == expect
    assert fs._ann_ts(1774915200000) == expect
    # 普通日期串不受影响
    assert fs._ann_ts("2025-03-28") == pd.Timestamp("2025-03-28").normalize()


def test_cached_table_roundtrip_keeps_leading_zero_codes(tmp_path, monkeypatch):
    """read_json 会把「000333」推断成整数 333——深市代码全体失配，count 归零的真凶。"""
    calls = []

    def fake_fetch(period):
        calls.append(period)
        return _yjbb("20251231", [
            ("000333", "2026-03-10", 2.0, 5.0, 22.0, 12.0, 10.0, "白色家电"),
            ("600519", "2026-03-10", 2.0, 5.0, 22.0, 12.0, 10.0, "白酒Ⅱ"),
        ])

    df1 = fs._cached_table("yjbb", "20251231", str(tmp_path), fake_fetch)
    assert len(calls) == 1  # 首次真拉
    df2 = fs._cached_table("yjbb", "20251231", str(tmp_path), fake_fetch)
    assert len(calls) == 1  # 第二次命中缓存
    snaps = fs.build_snapshots(_ts("2026-08-29"), {"20251231": df2}, {}, ["20251231"])
    assert "000333" in snaps  # 前导零代码原样保留
    assert snaps["000333"]["roe"] == 22.0
    assert snaps["600519"]["industry"] == "白酒Ⅱ"


# ---- 披露截止双门控（最新公告日期会随事后更正前移，不能单靠它） ----

def test_disclose_deadline_rescues_updated_records():
    """东财「最新公告日期」随事后更正前移（茅台2024年报现值2026-04-17），
    单靠它门控历史 asof 会把全市场误判为「未公告」。asof 已过法定披露截止
    （年报次年4-30）的报告期必然已全员披露 → 视为当时已知。"""
    yjbb = {
        "20251231": _yjbb("20251231", [("600001", "2026-10-21", 2.0, 5.0, 22.0, 12.0, 10.0, "白色家电")]),
        "20241231": _yjbb("20241231", [("600001", "2026-04-17", 1.8, 4.5, 21.0, 8.0, 7.0, "白色家电")]),
        "20231231": _yjbb("20231231", [("600001", "2024-05-01", 1.5, 4.0, 20.0, 6.0, 5.0, "白色家电")]),
        "20221231": _yjbb("20221231", [("600001", "2023-05-01", 1.2, 3.5, 19.0, 4.0, 3.0, "白色家电")]),
    }
    anns = ["20251231", "20241231", "20231231", "20221231"]
    # asof 2025-08-29：20241231 已过截止(2025-04-30) → 已知；20251231 未到截止也没公告 → 未知
    s = fs.build_snapshots(_ts("2025-08-29"), yjbb, {}, anns)["600001"]
    assert s["roe"] == 21.0  # 最新已知年报=20241231，不是被更正日期骗过的 20251231
    assert s["roe_hist"] == {"20241231": 21.0, "20231231": 20.0, "20221231": 19.0}
    # asof 2025-03-01：还没到 20241231 的披露截止，公告日又在未来 → 不可知
    s2 = fs.build_snapshots(_ts("2025-03-01"), yjbb, {}, anns)["600001"]
    assert s2["roe"] == 20.0  # 退回 20231231
    assert s2["roe_hist"] is None  # 只有 2023/2022 两个年报


def test_disclose_deadline_quarters():
    # 中报截止 8-31：asof 8-29 不到截止 → 靠公告日判定；asof 9-1 过截止 → 已知
    assert fs.disclose_deadline("20250630") == _ts("2025-08-31")
    assert fs.disclose_deadline("20250331") == _ts("2025-04-30")
    assert fs.disclose_deadline("20240930") == _ts("2024-10-31")
    assert fs.disclose_deadline("20241231") == _ts("2025-04-30")


# ---- 历史验证准入门 ----

def _rule(*metrics):
    return {"logic": "all",
            "conditions": [{"metric": m, "op": ">" if m != "industry" else "contains", "value": 1} for m in metrics],
            "rank": None}


def test_all_four_presets_supported():
    from quant_sentiment.conditions import PRESETS
    for p in PRESETS:
        ok, why = fs.hist_supportable(p["rule"])
        assert ok, f"{p['key']}: {why}"


def test_kline_only_rule_supported():
    ok, why = fs.hist_supportable(_rule("above_ma20", "ret20"))
    assert ok and why == ""


def test_slow_metrics_refused_with_names():
    ok, why = fs.hist_supportable(_rule("pe_pct", "above_ma20"))
    assert not ok and "PE" in why and "泄漏" in why


def test_unsupported_row_metrics_refused():
    for m in ("div_yield", "ocf_over_profit", "turnover_wan", "mcap_yi", "deduct_growth"):
        ok, why = fs.hist_supportable(_rule(m))
        assert not ok, m


def test_rank_metric_also_checked():
    rule = {"logic": "all", "conditions": [{"metric": "above_ma20", "op": "eq", "value": 1}],
            "rank": {"metric": "pe_pct", "top_pct": 30, "order": "asc"}}
    assert not fs.hist_supportable(rule)[0]


def test_listed_2y_supported_point_in_time():
    ok, _ = fs.hist_supportable(_rule("listed_2y"))
    assert ok  # 前缀K线长度即可判定，天然 point-in-time


# ---- 拉取失败可见化 ----

def test_fetch_reports_failed_annual_table(monkeypatch):
    """年报表拉取失败不许静默——少一张年报 roe_hist 全市场蒸发，必须透出警告。"""
    def flaky(name, period, cache_dir, fetcher):
        if period == "20231231":  # asof 2026-08-29 的第三个年报
            return None  # 模拟拉取失败
        return fetcher(period)

    monkeypatch.setattr(fs, "_cached_table", flaky)
    monkeypatch.setattr(fs, "_fetch_yjbb", lambda p: _yjbb(p, [
        ("600001", "2026-03-10", 2.0, 5.0, 22.0, 12.0, 10.0, "白色家电")]))
    snaps, warns = fs.fetch_hist_fundamentals("2026-08-29", _rule("roe_mean3"), None)
    assert any("20231231" in w and "yjbb" in w for w in warns)


def test_fetch_no_warning_when_all_tables_ok(monkeypatch):
    monkeypatch.setattr(fs, "_fetch_yjbb", lambda p: _yjbb(p, [
        ("600001", "2026-03-10", 2.0, 5.0, 22.0, 12.0, 10.0, "白色家电")]))
    snaps, warns = fs.fetch_hist_fundamentals("2026-08-29", _rule("roe_mean3"), None)
    assert warns == []
    assert "600001" in snaps
