from quant_sentiment.state import Evidence, QuantState


def test_evidence_fields():
    ev = Evidence(claim="营收增长", source_text="Q1营收同比+30%", source_url="http://x", ts="2026-01-01")
    assert ev.claim == "营收增长"
    assert ev.source_url == "http://x"


def test_state_shape():
    s = {"symbol": "600000", "evidence": [], "scores": {}, "report": "", "model_tier": "lite"}
    assert s["symbol"] == "600000"
