from quant_sentiment.sentiment import score_sentiment, SentimentScore
from quant_sentiment.llm import FakeLLM


def test_score_sentiment_parses_json():
    llm = FakeLLM(script=['{"label":"利好","confidence":0.8}'])
    sc = score_sentiment({"title": "业绩大增"}, llm=llm)
    assert sc.label == "利好"
    assert sc.confidence == 0.8


def test_score_sentiment_fallback_on_bad_json():
    llm = FakeLLM(script=["这不是JSON"])
    sc = score_sentiment({"title": "x"}, llm=llm)
    assert sc.label == "中性"
    assert sc.confidence < 0.5
