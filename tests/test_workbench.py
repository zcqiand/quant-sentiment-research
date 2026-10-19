"""工作台编排层测试：研究快照 / 合成分 / 舆情缓存 / 一键扫描。离线 fixture 驱动。"""

import json

import pandas as pd
import pytest

from quant_sentiment.gateway import set_offline
from quant_sentiment.llm import FakeLLM
from quant_sentiment.workbench import Workbench, composite_label


def _fixtures(tmp_path):
    """单只标的 600000：上行 K 线 + 两条利好新闻。"""
    pd.DataFrame(
        {
            "date": [f"2026-01-{d:02d}" for d in range(1, 31)],
            "open": [10.0] * 30,
            "close": [10.0 + i * 0.1 for i in range(30)],
            "high": [10.5 + i * 0.1 for i in range(30)],
            "low": [9.8 + i * 0.1 for i in range(30)],
            "volume": [1000] * 30,
        }
    ).to_parquet(tmp_path / "kline_600000.parquet")
    (tmp_path / "news_600000.json").write_text(
        json.dumps(
            [
                {"title": "业绩超预期", "content": "净利润大增", "url": "http://x/1", "ts": "2026-01-30 08:00"},
                {"title": "获大额订单", "content": "中标重大项目", "url": "http://x/2", "ts": "2026-01-29 08:00"},
            ]
        ),
        encoding="utf-8",
    )


@pytest.fixture(autouse=True)
def _offline():
    set_offline(True)
    yield
    set_offline(False)


def _bull_llm():
    return FakeLLM(script=['{"label":"利好","confidence":0.9}'])


def test_composite_label_bands():
    assert composite_label(80) == "重点关注"
    assert composite_label(45) == "关注"
    assert composite_label(0) == "观望"
    assert composite_label(-45) == "谨慎"
    assert composite_label(-80) == "回避研究"


def test_research_snapshot_composes_all_dimensions(tmp_path):
    _fixtures(tmp_path)
    wb = Workbench(db_path=str(tmp_path / "wb.db"), cache_dir=str(tmp_path), llm=_bull_llm())
    snap = wb.research_snapshot("600000")

    assert snap["symbol"] == "600000"
    assert snap["price"] == pytest.approx(12.9)  # 末位收盘 10 + 29*0.1
    assert snap["technical"]["trend"] == "上行"
    assert snap["technical"]["score"] > 0
    assert snap["sentiment"]["bull"] == 2
    assert snap["sentiment"]["score"] == pytest.approx(1.0)
    assert snap["composite"] > 60
    assert snap["composite_label"] == "重点关注"
    assert snap["report"]  # 简报文本非空
    assert len(snap["evidence"]) >= 3  # 技术/资金/舆情各至少一条
    assert len(snap["news"]) == 2
    assert snap["news"][0]["label"] == "利好"


def test_news_score_cached_second_run_no_llm_calls(tmp_path):
    _fixtures(tmp_path)
    llm = _bull_llm()
    wb = Workbench(db_path=str(tmp_path / "wb.db"), cache_dir=str(tmp_path), llm=llm)
    wb.research_snapshot("600000")
    calls_first = llm._cursor

    wb.research_snapshot("600000")
    assert llm._cursor == calls_first  # 全部命中缓存，零新增 LLM 调用


def test_scan_collects_errors_for_missing_fixture(tmp_path):
    _fixtures(tmp_path)
    wb = Workbench(db_path=str(tmp_path / "wb.db"), cache_dir=str(tmp_path), llm=_bull_llm())
    wb.add_stock("600000", "浦发银行")
    wb.add_stock("000001", "平安银行")  # 无 fixture，应进 errors

    result = wb.scan()
    assert len(result["results"]) == 1
    assert result["results"][0]["symbol"] == "600000"
    assert len(result["errors"]) == 1
    assert result["errors"][0]["symbol"] == "000001"
    # 扫描结果落库
    latest = wb.store.latest_scan()
    assert latest is not None
    assert latest["payload"]["results"][0]["symbol"] == "600000"


def test_latest_snapshots_from_store(tmp_path):
    _fixtures(tmp_path)
    wb = Workbench(db_path=str(tmp_path / "wb.db"), cache_dir=str(tmp_path), llm=_bull_llm())
    wb.add_stock("600000", "浦发银行")
    wb.scan()
    latest = wb.latest_snapshots()
    assert "600000" in latest
    assert latest["600000"]["composite"] > 60


def test_snapshot_degrades_without_kline(tmp_path):
    """K 线源不可达：技术维度置 None，舆情+热度维度照常出快照（权重归一）。"""
    (tmp_path / "news_000003.json").write_text(
        json.dumps(
            [
                {"title": "重大利好", "content": "签订战略合作", "url": "http://z/1"},
                {"title": "再获增持", "content": "股东增持", "url": "http://z/2"},
            ]
        ),
        encoding="utf-8",
    )
    wb = Workbench(db_path=str(tmp_path / "wb.db"), cache_dir=str(tmp_path), llm=_bull_llm())
    snap = wb.research_snapshot("000003")

    assert snap["technical"] is None
    assert snap["price"] is None
    assert snap["change_pct"] is None
    assert snap["sentiment"]["bull"] == 2
    assert len(snap["evidence"]) >= 2  # 资金面+舆情，无技术面证据
    # 舆情=1.0, heat=0.2 → 归一后 composite = 100*(0.45*1+0.10*0.2)/0.55 ≈ 85
    assert snap["composite"] == 85
    assert snap["composite_label"] == "重点关注"


def test_news_query_prefers_cjk_name(tmp_path):
    from quant_sentiment.workbench import _dedupe_news

    wb = Workbench(db_path=str(tmp_path / "wb.db"), cache_dir=str(tmp_path), llm=_bull_llm())
    wb.add_stock("600000", "浦发银行")
    wb.add_stock("000001", "SPDB")  # 非中文名不用于检索（检索质量差）
    assert wb.news_query("600000") == "浦发银行"
    assert wb.news_query("000001") is None
    assert wb.news_query("999999") is None  # 不在自选 → 用代码

    news = [
        {"url": "u1", "title": "t1"},
        {"url": "u1", "title": "t1"},  # 完全重复
        {"url": "u2", "title": "t1"},  # 同题不同链，保守保留
        {"url": "", "title": "t2"},
    ]
    assert len(_dedupe_news(news)) == 3


def test_downtrend_bearish_news_gives_low_score(tmp_path):
    pd.DataFrame(
        {
            "date": [f"2026-01-{d:02d}" for d in range(1, 31)],
            "close": [20.0 - i * 0.2 for i in range(30)],
        }
    ).to_parquet(tmp_path / "kline_000002.parquet")
    (tmp_path / "news_000002.json").write_text(
        json.dumps([{"title": "业绩爆雷", "content": "商誉减值", "url": "http://y/1"}]),
        encoding="utf-8",
    )
    llm = FakeLLM(script=['{"label":"利空","confidence":0.85}'])
    wb = Workbench(db_path=str(tmp_path / "wb.db"), cache_dir=str(tmp_path), llm=llm)
    snap = wb.research_snapshot("000002")
    assert snap["composite"] < 0
    assert snap["composite_label"] in ("谨慎", "回避研究", "观望")
