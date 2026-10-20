import pandas as pd

from quant_sentiment.gateway import set_offline, fetch_kline


def _fixtures(tmp_path):
    pd.DataFrame(
        {"date": ["2026-01-01", "2026-01-02"], "close": [10.0, 10.5]}
    ).to_parquet(tmp_path / "kline_600000_5.parquet")


def test_fetch_kline_offline_from_cache(tmp_path):
    _fixtures(tmp_path)
    set_offline(True)
    df = fetch_kline("600000", days=5, cache_dir=str(tmp_path))
    assert len(df) == 2
    assert "close" in df.columns


def test_kline_amount_column_passthrough(tmp_path):
    """成交额列保留为 amount（东财「成交额」/腾讯 amount）——条件回测的流动性口径。"""
    set_offline(True)
    pd.DataFrame(
        {"date": ["2026-01-01", "2026-01-02"], "close": [10.0, 10.5],
         "成交额": [5e7, 6e7]}
    ).to_parquet(tmp_path / "kline_600001_5.parquet")
    pd.DataFrame(
        {"date": ["2026-01-01", "2026-01-02"], "close": [10.0, 10.5]}
    ).to_parquet(tmp_path / "kline_600000_5.parquet")
    df = fetch_kline("600001", days=5, cache_dir=str(tmp_path))
    assert "amount" in df.columns
    assert df["amount"].iloc[-1] == 6e7

    # 无成交额列（旧缓存/离线 fixture）→ 不产生 amount 列，不报错
    df2 = fetch_kline("600000", days=5, cache_dir=str(tmp_path))
    assert "amount" not in df2.columns


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


def _fake_tx_df():
    import pandas as pd

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


def test_kline_online_ttl_cache(monkeypatch, tmp_path):
    """在线模式 TTL 缓存：几分钟内再取同一只不重发网络请求。"""
    import os
    import time as time_mod

    from quant_sentiment import gateway

    tx_calls = []

    def fake_tx(symbol, days):
        tx_calls.append(symbol)
        return _fake_tx_df()

    set_offline(False)
    monkeypatch.setattr(gateway, "_fetch_kline_tencent", fake_tx)
    monkeypatch.setattr(gateway, "_em_cooldown_until", time_mod.time() + 9999)  # 不走东财

    gateway.fetch_kline("600000", days=5, cache_dir=str(tmp_path))
    gateway.fetch_kline("600000", days=5, cache_dir=str(tmp_path))
    assert len(tx_calls) == 1  # 第二次命中 TTL 缓存

    path = tmp_path / "kline_600000_5.parquet"  # 缓存过期后重新抓（键含 days）
    old = path.stat().st_mtime - 10_000
    os.utime(path, (old, old))
    gateway.fetch_kline("600000", days=5, cache_dir=str(tmp_path))
    assert len(tx_calls) == 2
