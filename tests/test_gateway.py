import json

import pandas as pd

from quant_sentiment.gateway import set_offline, fetch_kline, fetch_news


def _fixtures(tmp_path):
    pd.DataFrame(
        {"date": ["2026-01-01", "2026-01-02"], "close": [10.0, 10.5]}
    ).to_parquet(tmp_path / "kline_600000.parquet")
    (tmp_path / "news_600000.json").write_text(
        json.dumps([{"title": "利好", "content": "业绩超预期", "url": "http://x"}]),
        encoding="utf-8",
    )


def test_fetch_kline_offline_from_cache(tmp_path):
    _fixtures(tmp_path)
    set_offline(True)
    df = fetch_kline("600000", days=5, cache_dir=str(tmp_path))
    assert len(df) == 2
    assert "close" in df.columns


def test_fetch_news_offline_from_cache(tmp_path):
    _fixtures(tmp_path)
    set_offline(True)
    news = fetch_news("600000", cache_dir=str(tmp_path))
    assert len(news) == 1
    assert news[0]["title"] == "利好"


def test_fetch_stock_name_parses_gbk_response():
    import httpx

    from quant_sentiment.gateway import fetch_stock_name

    body = 'v_sh600000="1~浦发银行~600000~9.78~9.70~9.79~9.65~1000~10000~";'.encode("gbk")
    llm_transport = httpx.MockTransport(lambda request: httpx.Response(200, content=body))
    assert fetch_stock_name("600000", transport=llm_transport) == "浦发银行"


def test_fetch_stock_name_failure_returns_empty():
    import httpx

    from quant_sentiment.gateway import fetch_stock_name

    def boom(request):
        raise httpx.ConnectError("down")

    transport = httpx.MockTransport(boom)
    assert fetch_stock_name("600000", transport=transport) == ""
    assert fetch_stock_name("abc", transport=transport) == ""  # 非法代码直接空
