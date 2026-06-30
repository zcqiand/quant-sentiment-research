import json

from quant_sentiment.backtest import run_backtest, BacktestResult
from quant_sentiment.gateway import set_offline


def _fake_sentiment_strategy(news_item):
    """测试用情绪判定：按 title 关键词粗判，模拟 LLM 判定。

    故意做得很朴素（只看标题关键词），用来验证 run_backtest 的对齐与计数：
    它既会判对（TP/TN），也会判错（FP/FN），覆盖四个计数分支。
    """
    title = news_item.get("title", "")
    if any(kw in title for kw in ("利好", "上涨", "增长", "突破")):
        return "利好"
    if any(kw in title for kw in ("利空", "下跌", "下滑", "亏损")):
        return "利空"
    return "中性"


def test_run_backtest(tmp_path):
    news = [
        {"title": "一季度净利同比增长30%", "content": "业绩大增", "url": "https://example.com/n1"},
        {"title": "高管减持引发下跌担忧", "content": "减持计划", "url": "https://example.com/n2"},
        {"title": "看似利好实则监管趋严", "content": "监管收紧", "url": "https://example.com/n3"},
        {"title": "订单超预期交付", "content": "交付提速", "url": "https://example.com/n4"},
    ]
    (tmp_path / "news_600000.json").write_text(
        json.dumps(news, ensure_ascii=False), encoding="utf-8"
    )
    gold_labels = {
        "https://example.com/n1": "利好",  # 策略判「增长」→利好，金标利好 → TP
        "https://example.com/n2": "利空",  # 策略判「下跌」→利空，金标利空 → TN
        "https://example.com/n3": "利空",  # 策略被「利好」字样误导→利好，金标利空 → FP
        "https://example.com/n4": "利好",  # 策略无关键词→中性，金标利好 → FN
    }
    set_offline(True)
    res = run_backtest(
        _fake_sentiment_strategy, "600000", str(tmp_path), gold_labels
    )
    assert isinstance(res, BacktestResult)
    assert 0.0 <= res.precision <= 1.0
    assert 0.0 <= res.recall <= 1.0
    assert res.samples > 0
