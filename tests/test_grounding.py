from quant_sentiment.grounding import attach_evidence, validate_report
from quant_sentiment.state import Evidence


def test_attach_evidence_grows_list():
    out = attach_evidence({"evidence": []}, "营收增长", "Q1+30%", "http://x", "2026-01-01")
    assert len(out["evidence"]) == 1
    assert out["evidence"][0].claim == "营收增长"


def test_validate_report_rejects_no_evidence():
    assert validate_report({"report": "利好结论", "evidence": []}) is False


def test_validate_report_passes_with_evidence():
    state = {"report": "利好结论", "evidence": [Evidence("营收增长", "Q1+30%", "http://x", "2026-01-01")]}
    assert validate_report(state) is True


def test_validate_report_passes_empty_report():
    assert validate_report({"report": "", "evidence": []}) is True
