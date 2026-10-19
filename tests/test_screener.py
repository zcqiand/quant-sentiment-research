"""选股器测试：纯函数筛选逻辑 + 腾讯批量报价解析，离线全绿。"""

import quant_sentiment.screener as scr


def _row(code, name, price, pe_ttm, pb, roe, debt_ratio, ocf3, profit, dps3):
    """构造一行候选股数据；ocf3/dps3 为 (最近年报, 前一年, 前两年) 元组。"""
    div_yield = round(sum(dps3) / 3 / price * 100, 2) if price else 0.0
    return {
        "code": code,
        "name": name,
        "price": price,
        "pe_ttm": pe_ttm,
        "pb": pb,
        "mcap_yi": 100.0,
        "roe": roe,
        "debt_ratio": debt_ratio,
        "ocf": dict(zip(scr.period_keys(), ocf3)),
        "profit": profit,
        "dps": dict(zip(scr.period_keys(), dps3)),
        "div_yield": div_yield,
    }


# ---- 白马价值 ----

def test_screen_white_horse_filters_and_ranks():
    good_a = _row("600001", "甲", 10.0, 15.0, 1.2, 18.0, 40.0, (5, 4, 3), 6.0, (0.5, 0.5, 0.5))
    good_b = _row("600002", "乙", 20.0, 10.0, 1.0, 25.0, 30.0, (8, 7, 6), 9.0, (0.8, 0.8, 0.8))
    rows = [
        good_a,
        good_b,
        _row("600003", "PE过高", 10.0, 30.0, 1.0, 20.0, 40.0, (5, 4, 3), 6.0, (0.5, 0.5, 0.5)),
        _row("600004", "PE为负", 10.0, -5.0, 1.0, 20.0, 40.0, (5, 4, 3), 6.0, (0.5, 0.5, 0.5)),
        _row("600005", "ROE不足", 10.0, 15.0, 1.0, 10.0, 40.0, (5, 4, 3), 6.0, (0.5, 0.5, 0.5)),
        _row("600006", "负债过高", 10.0, 15.0, 1.0, 20.0, 60.0, (5, 4, 3), 6.0, (0.5, 0.5, 0.5)),
        _row("600007", "现金流断裂", 10.0, 15.0, 1.0, 20.0, 40.0, (5, -4, 3), 6.0, (0.5, 0.5, 0.5)),
        _row("600008", "ST剔除", 10.0, 15.0, 1.0, 20.0, 40.0, (5, 4, 3), 6.0, (0.5, 0.5, 0.5)),
    ]
    rows[-1]["name"] = "ST 摘帽"
    out = scr.screen_white_horse(rows, top=10)
    assert [r["code"] for r in out] == ["600002", "600001"]  # ROE 降序
    assert out[0]["ocf_total"] == 21.0


def test_screen_white_horse_top_truncates():
    rows = [
        _row(f"6000{i:02d}", f"股{i}", 10.0, 10.0, 1.0, 15.0 + i, 30.0, (5, 4, 3), 6.0, (0.5, 0.5, 0.5))
        for i in range(30)
    ]
    assert len(scr.screen_white_horse(rows, top=20)) == 20


# ---- 高股息防守 ----

def test_screen_dividend_filters_and_ranks():
    good_a = _row("000001", "高息", 10.0, 8.0, 0.8, 12.0, 45.0, (5, 4, 3), 6.0, (0.7, 0.7, 0.7))
    good_a["div_yield"] = 7.0
    good_b = _row("000002", "更高息", 8.0, 6.0, 0.7, 11.0, 40.0, (6, 5, 4), 7.0, (0.7, 0.7, 0.7))
    good_b["div_yield"] = 8.75
    rows = [
        good_a,
        good_b,
        _row("000003", "息不够", 10.0, 8.0, 0.8, 12.0, 45.0, (5, 4, 3), 6.0, (0.4, 0.4, 0.4)),
        _row("000004", "PB偏高", 10.0, 8.0, 2.0, 12.0, 45.0, (5, 4, 3), 6.0, (0.7, 0.7, 0.7)),
        _row("000005", "现金流断裂", 10.0, 8.0, 0.8, 12.0, 45.0, (5, -4, 3), 6.0, (0.7, 0.7, 0.7)),
        _row("000006", "没分红", 10.0, 8.0, 0.8, 12.0, 45.0, (5, 4, 3), 6.0, (0.0, 0.0, 0.0)),
    ]
    rows.append(_row("000007", "亏损派息", 10.0, -20.0, 0.8, 12.0, 45.0, (5, 4, 3), 6.0, (0.7, 0.7, 0.7)))
    out = scr.screen_dividend(rows, top=10)
    assert [r["code"] for r in out] == ["000002", "000001"]  # 股息率降序
    assert out[0]["div_yield"] == 8.75


# ---- 腾讯批量报价解析 ----

def test_parse_quote_fields():
    payload = (
        'v_sh600000="1~浦发银行~600000~9.78~9.73~9.72~1~1~1~1~1~1~1~1~1~1~1~1~1~1~1~'
        '1~1~1~1~1~1~1~1~1~1~1~1~1~1~1~1~1~1~6.36~1~1~1~1~3257.31~3257.31~0.43~";'
        'v_sz000858="x";'
    )
    out = scr._parse_quote(payload)
    assert out["600000"]["name"] == "浦发银行"
    assert out["600000"]["price"] == 9.78
    assert out["600000"]["pe_ttm"] == 6.36
    assert out["600000"]["mcap_yi"] == 3257.31
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
    assert y3 < y2 < annual  # 前两年 < 前一年 < 最近年报（报告期字典序即时间序）
