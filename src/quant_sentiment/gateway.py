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
import time
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


_TENCENT_EXCHANGE_PREFIX = {"6": "sh", "0": "sz", "3": "sz", "4": "bj", "8": "bj", "9": "sh"}


def fetch_stock_name(symbol: str, transport=None) -> str:
    """查股票名称（腾讯行情接口 qt.gtimg.cn，GBK 编码）。

    - host 与 eastmoney 独立，K 线主源被限流时仍可用；
    - 直连不走代理（``trust_env=False``，本机代理对行情源不可靠）；
    - 任何失败返回空串不抛——名称是增强信息，不值得让流程失败。
    """
    import httpx

    prefix = _TENCENT_EXCHANGE_PREFIX.get(symbol[:1])
    if not prefix:
        return ""
    try:
        with httpx.Client(transport=transport, trust_env=transport is None) as client:
            resp = client.get(f"https://qt.gtimg.cn/q={prefix}{symbol}", timeout=10.0)
        resp.raise_for_status()
        text = resp.content.decode("gbk", errors="replace")
        for part in text.split(";"):
            segment = part.strip()
            if segment.startswith(f"v_{prefix}{symbol}="):
                fields = segment.split('"')[1].split("~")
                # 腾讯源名称常带装饰空格（如「五 粮 液」），统一去掉
                return fields[1].replace(" ", "") if len(fields) > 1 else ""
        return ""
    except Exception:  # noqa: BLE001 - 名称查不到就空着，流程继续
        return ""


_KLINE_OUT_COLS = ["date", "open", "close", "high", "low", "volume"]


def _standardize_kline(df):
    """中文列名统一映射为英文 OHLCV；缺 open/high/low 时以 close 兜底，volume 缺省 0。"""
    df = df.rename(columns={c: v for c, v in _KLINE_COL_MAP.items() if c in df.columns})
    if "close" not in df.columns:
        raise ValueError(f"K 线数据缺少 close 列：{list(df.columns)}")
    for col in ("open", "high", "low"):
        if col not in df.columns:
            df[col] = df["close"]
    if "volume" not in df.columns:
        df["volume"] = 0
    if "date" not in df.columns:
        df["date"] = [f"d{i + 1}" for i in range(len(df))]
    return df[_KLINE_OUT_COLS].reset_index(drop=True)


def _fetch_kline_eastmoney(symbol: str, days: int):
    """eastmoney 源（ak.stock_zh_a_hist，前复权）——主源，容量大但易限流。"""
    import akshare as ak
    from datetime import datetime, timedelta

    start_date = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")
    df = ak.stock_zh_a_hist(
        symbol=symbol, period="daily", start_date=start_date, adjust="qfq"
    )
    return df


def _fetch_kline_tencent(symbol: str, days: int):
    """腾讯源（ak.stock_zh_a_hist_tx，前复权）——备援，host 独立不易同限。"""
    import akshare as ak
    from datetime import datetime, timedelta

    start_date = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")
    end_date = datetime.now().strftime("%Y%m%d")
    return ak.stock_zh_a_hist_tx(symbol=symbol, start_date=start_date, end_date=end_date)


# ---- K 线：东财主源 + 腾讯备援，双源均失败才抛 ----

_EM_COOLDOWN_SECONDS = 600  # 东财失败后的熔断冷却期（拉黑通常持续数小时，冷却只是止损）
_em_cooldown_until = 0.0  # 模块级状态：冷却截止时间戳


def fetch_kline(symbol: str, days: int = 30, cache_dir: str | None = None):
    """取 ``symbol`` 最近 ``days`` 个交易日标准 OHLCV K 线。

    返回 DataFrame 固定列：date/open/close/high/low/volume（英文列）。

    - 离线模式（``set_offline(True)`` 或 akshare 不可导入）：从
      ``{cache_dir}/kline_{symbol}.parquet`` 读取，缺失则抛
      ``FileNotFoundError`` 并给出清晰提示。
    - 在线模式：eastmoney 主源 → 腾讯备援（host 独立，防单源限流，
      2026-10-19 push2his 指纹级拉黑教训）；若给定 ``cache_dir`` 则写回
      parquet 供离线复用。
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
        return _standardize_kline(df).tail(days).reset_index(drop=True)

    errors: list[str] = []
    global _em_cooldown_until
    # 熔断：东财刚失败过（如 TLS 指纹级拉黑）就别再撞，省 akshare 重试的 4s+
    sources: list = []
    if time.time() >= _em_cooldown_until:
        sources.append(_fetch_kline_eastmoney)
    sources.append(_fetch_kline_tencent)
    for source in sources:
        try:
            df = _standardize_kline(source(symbol, days)).tail(days).reset_index(drop=True)
            if cache_dir:
                import os

                os.makedirs(cache_dir, exist_ok=True)
                df.to_parquet(_kline_cache_path(cache_dir, symbol), index=False)
            return df
        except Exception as exc:  # noqa: BLE001 - 单源失败切下一源
            if source is _fetch_kline_eastmoney:
                _em_cooldown_until = time.time() + _EM_COOLDOWN_SECONDS
            errors.append(f"{source.__name__}: {exc}")

    raise RuntimeError(f"K 线双源均失败：{'；'.join(errors)}")


def fetch_news(
    symbol: str, cache_dir: str | None = None, query: str | None = None
) -> list[dict[str, Any]]:
    """取 ``symbol`` 相关新闻列表。

    - 离线模式：从 ``{cache_dir}/news_{symbol}.json`` 读取。
    - 在线模式：调用 akshare 搜索新闻——``query`` 给定时用它作检索词
      （中文股名检索远比 6 位代码准：按代码搜会命中任何含该数字的文章），
      ``cache_dir`` 给定时写回 json（仍按 symbol 存，测试 fixture 不受影响）。

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

    raw = ak.stock_news_em(symbol=query or symbol)
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


_KLINE_COL_MAP = {
    "日期": "date",
    "开盘": "open",
    "收盘": "close",
    "最高": "high",
    "最低": "low",
    "成交量": "volume",
}


__all__ = ["set_offline", "fetch_kline", "fetch_news", "fetch_stock_name"]
