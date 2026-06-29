import json
import pandas as pd
from quant_sentiment.gateway import set_offline
from quant_sentiment.graph import build_graph
from quant_sentiment.llm import FakeLLM
from quant_sentiment.grounding import validate_report


def _fixtures(tmp_path):
    pd.DataFrame({"date": ["2026-01-01", "2026-01-02"], "close": [10.0, 10.5]}).to_parquet(tmp_path / "kline_600000.parquet")
    (tmp_path / "news_600000.json").write_text(json.dumps([
        {"title": "业绩超预期", "content": "Q1营收大增", "url": "http://x/1", "ts": "2026-01-02"}
    ]))


def test_graph_multi_pass_with_evidence(tmp_path):
    _fixtures(tmp_path)
    set_offline(True)
    llm = FakeLLM(script=['{"label":"利好","confidence":0.8}'])
    g = build_graph(llm=llm, cache_dir=str(tmp_path))
    initial = {"symbol": "600000", "evidence": [], "scores": {}, "report": "", "model_tier": "lite"}
    out = g.invoke(initial)
    assert len(out["evidence"]) >= 1
    assert validate_report(out) is True
    assert out["report"]  # non-empty
    assert "600000" in out["report"]
