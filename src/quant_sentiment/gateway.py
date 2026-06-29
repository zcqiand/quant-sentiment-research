"""AkShare 行情/舆情数据网关（含离线模式）。

真实数据来自 `akshare <https://akshare.akfamily.xyz/>`_，需要联网。
本仓的**测试**必须在无 akshare、无网络的环境下运行，因此网关支持
一个离线模式：当 ``_OFFLINE`` 为真、或 akshare 不可导入时，从
``cache_dir`` 读取本地 parquet / json fixture。

约定：
- K 线：``{cache_dir}/kline_{symbol}.parquet``，至少含 ``close`` 列。
- 新闻：``{cache_dir}/news_{symbol}.json``，``list[{title, content, url, ts?}]``。
"""

from __future__ import annotations

import json
from typing import Any

# 模块级离线开关。测试通过 set_offline(True) 强制走本地 fixture；
# 生产可保持 False，由 akshare 是否可导入自然降级。
_OFFLINE: bool = False


def set_offline(flag: bool) -> None:
    """切换网关离线模式。"""
    global _OFFLINE
    _OFFLINE = bool(flag)


def _offline_active() -> bool:
    """离线模式生效 = 显式开启 OR akshare 不可导入。"""
    if _OFFLINE:
        return True
    try:
        import akshare  # noqa: F401
    except Exception:
        return True
    return False


def _kline_cache_path(cache_dir: str, symbol: str) -> str:
    import os

    return os.path.join(cache_dir, f"kline_{symbol}.parquet")


def _news_cache_path(cache_dir: str, symbol: str) -> str:
    import os

    return os.path.join(cache_dir, f"news_{symbol}.json")


def fetch_kline(symbol: str, days: int = 30, cache_dir: str | None = None):
    """取 ``symbol`` 最近 ``days`` 个交易日的 K 线。

    - 离线模式（``set_offline(True)`` 或 akshare 不可导入）：从
      ``{cache_dir}/kline_{symbol}.parquet`` 读取，缺失则抛
      ``FileNotFoundError`` 并给出清晰提示。
    - 在线模式：调用 akshare 取近期日 K，返回含 ``close`` 列的 DataFrame；
      若给定 ``cache_dir`` 则写回 parquet 供离线复用。

    返回的 DataFrame 至少含 ``close`` 列。
    """
    import pandas as pd  # 懒加载：测试外不必强依赖

    if _offline_active():
        if not cache_dir:
            raise FileNotFoundError(
                f"离线模式下需要 cache_dir 来定位 kline_{symbol}.parquet"
            )
        path = _kline_cache_path(cache_dir, symbol)
        try:
            df = pd.read_parquet(path)
        except FileNotFoundError as exc:  # pragma: no cover - 路径已校验
            raise FileNotFoundError(
                f"离线 K 线 fixture 缺失：{path}；请先在线抓取或补 fixture"
            ) from exc
        if "close" not in df.columns:
            raise ValueError(f"离线 K 线 fixture {path} 缺少 close 列")
        return df.tail(days).reset_index(drop=True)

    # 在线：akshare 已在 _offline_active() 中确认可导入
    import akshare as ak

    df = ak.stock_zh_a_hist(
        symbol=symbol, period="daily", adjust="qfq"
    )
    # akshare 返回中文列名，统一映射到英文 close
    if "close" not in df.columns and "收盘" in df.columns:
        df = df.rename(columns={"收盘": "close"})
    if "close" not in df.columns:
        raise ValueError(f"akshare 返回的 K 线缺少 close 列：{list(df.columns)}")
    df = df.tail(days).reset_index(drop=True)
    if cache_dir:
        import os

        os.makedirs(cache_dir, exist_ok=True)
        df.to_parquet(_kline_cache_path(cache_dir, symbol), index=False)
    return df


def fetch_news(symbol: str, cache_dir: str | None = None) -> list[dict[str, Any]]:
    """取 ``symbol`` 相关新闻列表。

    - 离线模式：从 ``{cache_dir}/news_{symbol}.json`` 读取。
    - 在线模式：调用 akshare 取新闻，``cache_dir`` 给定时写回 json。

    返回 ``list[dict]``，每项形如 ``{title, content, url, ts?}``。
    """
    if _offline_active():
        if not cache_dir:
            raise FileNotFoundError(
                f"离线模式下需要 cache_dir 来定位 news_{symbol}.json"
            )
        path = _news_cache_path(cache_dir, symbol)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except FileNotFoundError as exc:  # pragma: no cover - 路径已校验
            raise FileNotFoundError(
                f"离线新闻 fixture 缺失：{path}；请先在线抓取或补 fixture"
            ) from exc

    import akshare as ak

    raw = ak.stock_news_em(symbol=symbol)
    # akshare 返回 DataFrame，列名为中文；映射到统一 schema
    col_map = {"新闻标题": "title", "新闻内容": "content", "新闻链接": "url", "发布时间": "ts"}
    records: list[dict[str, Any]] = []
    for _, row in raw.iterrows():
        item = {col_map.get(c, c): row[c] for c in raw.columns}
        records.append(
            {
                "title": item.get("title", ""),
                "content": item.get("content", ""),
                "url": item.get("url", ""),
                **({"ts": item["ts"]} if "ts" in item else {}),
            }
        )
    if cache_dir:
        import os

        os.makedirs(cache_dir, exist_ok=True)
        with open(_news_cache_path(cache_dir, symbol), "w", encoding="utf-8") as fh:
            json.dump(records, fh, ensure_ascii=False)
    return records


__all__ = ["set_offline", "fetch_kline", "fetch_news"]
