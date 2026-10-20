"""候选池构建器测试：行 schema v4 + 腾讯批量报价解析，离线全绿。"""

import pandas as pd

import quant_sentiment.screener as scr

P3 = ["20251231", "20241231", "20231231"]


def _yjbb():
    return {
        p: pd.DataFrame(
            {
                "股票代码": ["600001", "600002"],
                "股票简称": ["甲", "乙"],
                "净资产收益率": [18.0, 25.0],
                "净利润-净利润": [10.0, 9.0],
                "净利润-同比增长": [25.0, -5.0],
                "营业收入-同比增长": [12.0, 30.0],
                "所处行业": ["银行", "白酒"],
            }
        )
        for p in P3
    }


def _xjll():
    return {
        p: pd.DataFrame(
            {
                "股票代码": ["600001", "600002"],
                "经营性现金流-现金流量净额": [12.0, 11.0],
                "投资性现金流-现金流量净额": [-3.0, -3.0],
            }
        )
        for p in P3
    }


def _quotes():
    return {
        "600001": {"name": "甲", "price": 10.0, "turnover_wan": 20000.0, "pe_ttm": 15.0, "pb": 1.5, "mcap_yi": 200.0, "float_mcap_yi": 150.0},
        "600002": {"name": "乙", "price": 8.0, "turnover_wan": 15000.0, "pe_ttm": 12.0, "pb": 1.0, "mcap_yi": 160.0, "float_mcap_yi": 120.0},
        "600003": {"name": "ST垃圾", "price": 2.0, "turnover_wan": 5000.0, "pe_ttm": -8.0, "pb": 0.5, "mcap_yi": 20.0, "float_mcap_yi": 15.0},
    }


def test_build_rows_v4_schema():
    zcfz = pd.DataFrame({"股票代码": ["600001", "600002"], "资产负债率": [40.0, 35.0]})
    fhps = {
        p: pd.DataFrame({"代码": ["600001", "600002"], "现金分红-现金分红比例": [5.0, 8.0]}) for p in P3
    }
    rows = scr.build_rows(_quotes(), _yjbb(), zcfz, _xjll(), fhps)
    codes = [r["code"] for r in rows]
    assert codes == ["600001", "600002"]  # ST 剔除
    r = rows[0]
    assert r["turnover_wan"] == 20000.0  # 成交额（流动性门槛用）
    assert r["inv_hist"]["20251231"] == -3.0  # 投资现金流（FCF 代理用）
    assert r["roe_hist"]["20231231"] == 18.0  # 近5年报 ROE 历史
    assert r["dps"]["20251231"] == 0.5  # 每10股5元 → 每股0.5
    assert r["div_yield"] == 5.0  # 0.5/10
    assert r["growth"] == 25.0
    assert r["debt_ratio"] == 40.0
    assert r["revenue_growth"] == 12.0  # v4 新列：营收同比（成长类条件用）
    assert r["industry"] == "银行"  # v4 新列：行业（过滤/展示用）
    assert r["float_mcap_yi"] == 150.0  # v5 新列：流通市值（小市值组合用）
    assert rows[1]["revenue_growth"] == 30.0
    assert rows[1]["industry"] == "白酒"
    assert rows[1]["float_mcap_yi"] == 120.0


def test_rows_cached_v5_filename(tmp_path, monkeypatch):
    """schema v5 缓存文件名升版——旧 v4 缓存不串数据。"""
    monkeypatch.setattr(scr, "fetch_rows", lambda: [{"code": "600001"}])
    rows = scr.rows_cached(str(tmp_path), refresh=False)
    assert rows == [{"code": "600001"}]
    files = list(tmp_path.iterdir())
    assert len(files) == 1 and "screen_rows_v5_" in files[0].name


def test_build_rows_drops_incomplete_cashflow():
    """现金流/分红数据不全的不进池。"""
    xjll = _xjll()
    xjll["20231231"] = xjll["20231231"].drop(index=1).reset_index(drop=True)  # 乙 缺前年现金流
    fhps = {p: pd.DataFrame({"代码": ["600001", "600002"], "现金分红-现金分红比例": [5.0, 8.0]}) for p in P3}
    rows = scr.build_rows(_quotes(), _yjbb(), pd.DataFrame(columns=["股票代码", "资产负债率"]), xjll, fhps)
    assert [r["code"] for r in rows] == ["600001"]


# ---- 腾讯批量报价解析 ----

def test_parse_quote_fields():
    payload = (
        'v_sh600000="1~浦发银行~600000~9.78~9.73~9.72~1~1~1~1~1~1~1~1~1~1~1~1~1~1~1~'
        '1~1~1~1~1~1~1~1~1~1~1~1~1~1~1~1~27017~0.08~6.36~1~1~1~1~3257.31~3257.31~0.43~";'
        'v_sz000858="x";'
    )
    out = scr._parse_quote(payload)
    assert out["600000"]["name"] == "浦发银行"
    assert out["600000"]["price"] == 9.78
    assert out["600000"]["turnover_wan"] == 27017.0  # f37 成交额(万)
    assert out["600000"]["pe_ttm"] == 6.36
    assert out["600000"]["mcap_yi"] == 3257.31  # f45 总市值
    assert out["600000"]["float_mcap_yi"] == 3257.31  # f44 流通市值
    assert out["600000"]["pb"] == 0.43
    assert "000858" not in out  # 字段不足的行丢弃


def test_tencent_code_prefix():
    assert scr._tencent_code("600000") == "sh600000"
    assert scr._tencent_code("688111") == "sh688111"
    assert scr._tencent_code("000858") == "sz000858"
    assert scr._tencent_code("300750") == "sz300750"
    assert scr._tencent_code("830000") is None  # 北交所不进池
    assert scr._tencent_code("430000") is None


def test_report_periods():
    annual, y2, y3, interim = scr.report_periods()
    assert annual.endswith("1231") and interim.endswith("0630")
    assert y3 < y2 < annual  # 报告期字典序即时间序
