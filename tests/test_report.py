from quant_sentiment.report import generate_report
from quant_sentiment.state import Evidence


def test_report_has_disclaimer_and_symbol():
    state = {"symbol": "600000", "scores": {"technical": "上行"}, "evidence": [Evidence("营收增长", "Q1+30%", "http://x", "2026-01-01")]}
    r = generate_report(state)
    assert "免责" in r
    assert "600000" in r


def test_report_has_no_buy_sell_signal():
    state = {"symbol": "600000", "scores": {}, "evidence": []}
    r = generate_report(state)
    assert "买入" not in r
    assert "卖出" not in r
