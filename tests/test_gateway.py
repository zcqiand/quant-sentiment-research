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


def test_kline_em_cooldown_skips_eastmoney_after_failure(monkeypatch):
    """东财失败后进入冷却期，冷却期内直接走腾讯不再撞东财（省 4s 重试）。"""
    import pandas as pd

    from quant_sentiment import gateway

    em_calls = []

    def fake_em(symbol, days):
        em_calls.append(symbol)
        raise RuntimeError("em blocked")

    def fake_tx(symbol, days):
        return pd.DataFrame(
            {
                "date": [f"2026-01-0{i}" for i in range(1, 6)],
                "open": [10.0] * 5,
                "close": [10.1] * 5,
                "high": [10.2] * 5,
                "low": [9.9] * 5,
                "volume": [100] * 5,
            }
        )

    set_offline(False)  # 其他测试会把模块级 _OFFLINE 留成 True，先归位
    monkeypatch.setattr(gateway, "_fetch_kline_eastmoney", fake_em)
    monkeypatch.setattr(gateway, "_fetch_kline_tencent", fake_tx)
    monkeypatch.setattr(gateway, "_em_cooldown_until", 0.0)

    gateway.fetch_kline("600000", days=5, cache_dir=None)
    gateway.fetch_kline("600000", days=5, cache_dir=None)
    assert len(em_calls) == 1  # 第二次在冷却期内，东财被跳过

    monkeypatch.setattr(gateway, "_em_cooldown_until", 0.0)  # 冷却期过，恢复尝试
    gateway.fetch_kline("600000", days=5, cache_dir=None)
    assert len(em_calls) == 2
