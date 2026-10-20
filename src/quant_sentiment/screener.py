"""全市场候选池构建器（机器池子的原料）。

口径（全 A，剔除 ST 与北交所）：财务三表+分红表走东财 datacenter 批量接口
（整表一次拉取），行情（现价/成交额/PE-TTM/PB/市值）走腾讯 qt.gtimg.cn 批量
报价（push2his 拉黑期的独立通路）。候选池原始行按 6h TTL 落 JSON 缓存——
反复刷新不再打数据源。行 schema v3：近5年报 ROE/净利/OCF/投资现金流历史 +
最新净利增速 + 双期股息率 + 成交额，因子交叉在 strategies.py。
"""

from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

import httpx

_TENCENT_URL = "https://qt.gtimg.cn/q="
_QUOTE_BATCH = 50
_ROWS_TTL_SECONDS = 6 * 3600  # 候选池行缓存半日，refresh=True 强制重拉



# ---- 报告期 ----

def report_periods() -> tuple[str, str, str, str]:
    """(最近完整年报, 前一年, 前两年, 最近中报)。

    年报 4/30 前披露完毕，5 月起以「上一年年报」为最近完整年报；
    三季报 10/31 才披露完，9 月起以当年中报为最新资产负债表时点。
    """
    today = date.today()
    annual = today.year - 1 if today.month >= 5 else today.year - 2
    interim_year = today.year if today.month >= 9 else today.year - 1
    return f"{annual}1231", f"{annual - 1}1231", f"{annual - 2}1231", f"{interim_year}0630"


def report_hist_periods(n: int = 5) -> list[str]:
    """近 n 个完整年报报告期（近→远），买入指数的 3~5 年持续性分析用。"""
    annual, _y2, _y3, _interim = report_periods()
    y = int(annual[:4])
    return [f"{y - i}1231" for i in range(n)]


def period_keys() -> tuple[str, str, str]:
    """ocf/dps 字典键（最近年报, 前一年, 前两年）。"""
    annual, y2, y3, _ = report_periods()
    return annual, y2, y3


# ---- 腾讯批量报价 ----

def _tencent_code(code: str) -> str | None:
    """6 位代码 → 腾讯带市场前缀代码；北交所(4/8 开头)不进池。"""
    if code.startswith(("60", "68")):
        return "sh" + code
    if code.startswith(("00", "30")):
        return "sz" + code
    return None


def _parse_quote(payload: str) -> dict[str, dict]:
    """解析 qt.gtimg.cn 响应：f1名称 f3现价 f37成交额(万) f39PE-TTM f45总市值(亿) f46PB。

    f37 实测口径（浦发 27017=2.7亿/五粮液 91611=9.2亿，与 f35 第三段「价格/量/额」互验）。
    """
    out: dict[str, dict] = {}
    for part in payload.split(";"):
        part = part.strip()
        if '="' not in part:
            continue
        fields = part.split('"')[1].split("~")
        if len(fields) < 47:
            continue
        code = fields[2]
        try:
            out[code] = {
                "name": fields[1].replace(" ", ""),
                "price": float(fields[3]),
                "turnover_wan": float(fields[37]),
                "pe_ttm": float(fields[39]),
                "mcap_yi": float(fields[45]),
                "pb": float(fields[46]),
            }
        except ValueError:  # 停牌/缺数据字段为空串
            continue
    return out


def fetch_quotes(codes: list[str], transport: httpx.Transport | None = None) -> dict[str, dict]:
    """腾讯批量报价，50 只/请求；返回 {code: quote}。"""
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for code in codes:
        t = _tencent_code(code)
        if t and t not in seen:
            seen.add(t)
            pairs.append((t, code))
    out: dict[str, dict] = {}
    with httpx.Client(transport=transport, trust_env=transport is None, timeout=15) as client:
        for i in range(0, len(pairs), _QUOTE_BATCH):
            batch = pairs[i : i + _QUOTE_BATCH]
            resp = client.get(_TENCENT_URL + ",".join(t for t, _ in batch))
            resp.raise_for_status()
            parsed = _parse_quote(resp.content.decode("gbk", errors="ignore"))
            for t, code in batch:
                if code in parsed:
                    out[code] = parsed[code]
    return out


# ---- 候选池构建 ----

def _col(df, keywords: tuple[str, ...] | str, exclude: tuple[str, ...] = ()) -> str:
    """按候选关键词依序找列名，可排除干扰列；找不到即抛 ValueError。"""
    if isinstance(keywords, str):
        keywords = (keywords,)
    for kw in keywords:
        for c in df.columns:
            if kw in c and not any(e in c for e in exclude):
                return c
    raise ValueError(f"找不到列（含 {keywords}，排除 {exclude}）：{list(df.columns)}")


def build_rows(
    quotes: dict[str, dict],
    yjbb_hist: dict[str, "object"],
    zcfz,
    xjll_hist: dict[str, "object"],
    fhps_by_period: dict[str, "object"],
) -> list[dict]:
    """财务表 × 行情快照 → 候选池行（纯函数，可测）。

    yjbb_hist/xjll_hist 为 {报告期: DataFrame}（近5个年报，近→远），
    fhps 为 {报告期: DataFrame}（近3个年报），形状见 fetch 层。
    行内历史键均按近→远排列。
    """
    periods = list(yjbb_hist.keys())
    annual = periods[0]
    latest_yjbb = yjbb_hist[annual]
    roe_col = _col(latest_yjbb, "净资产收益率", exclude=("扣非",))
    profit_col = _col(latest_yjbb, "净利润", exclude=("增长", "环比", "扣非"))
    growth_col = _col(latest_yjbb, "同比增长")
    ocf_cols = {
        p: _col(df, ("经营活动产生的现金流量净额", "经营性现金流-现金流量净额"))
        for p, df in xjll_hist.items()
    }
    inv_cols = {
        p: _col(df, ("投资活动产生的现金流量净额", "投资性现金流-现金流量净额"))
        for p, df in xjll_hist.items()
    }
    dps_col = _col(fhps_by_period[annual], "现金分红比例")

    roe_maps = {p: dict(zip(df["股票代码"], df[roe_col])) for p, df in yjbb_hist.items()}
    profit_maps = {p: dict(zip(df["股票代码"], df[profit_col])) for p, df in yjbb_hist.items()}
    growth_map = dict(zip(latest_yjbb["股票代码"], latest_yjbb[growth_col]))
    debt_map = {
        str(code): round(float(ratio), 2)
        for code, ratio in zip(zcfz["股票代码"], zcfz[_col(zcfz, "资产负债率")])
        if ratio and float(ratio) == float(ratio)
    }
    ocf_maps = {
        p: dict(zip(xjll_hist[p]["股票代码"], xjll_hist[p][ocf_cols[p]]))
        for p in xjll_hist
    }
    inv_maps = {
        p: dict(zip(xjll_hist[p]["股票代码"], xjll_hist[p][inv_cols[p]]))
        for p in xjll_hist
    }
    dps_maps: dict[str, dict] = {}
    for p, df in fhps_by_period.items():
        implemented = df[df["方案进度"] == "实施分配"] if "方案进度" in df.columns else df
        per_share = implemented[dps_col] / 10.0  # 每10股派息 → 每股股利
        dps_maps[p] = dict(zip(implemented["代码"], per_share))

    def _num(v) -> float | None:
        try:
            f = float(v)
            return None if f != f else f
        except (TypeError, ValueError):
            return None

    rows: list[dict] = []
    dps_keys = list(fhps_by_period.keys())
    for code, q in quotes.items():
        if "ST" in q["name"].upper():
            continue
        ocf_hist = {p: _num(ocf_maps.get(p, {}).get(code)) for p in periods}
        inv_hist = {p: _num(inv_maps.get(p, {}).get(code)) for p in periods}
        profit_hist = {p: _num(profit_maps.get(p, {}).get(code)) for p in periods}
        roe_hist = {p: _num(roe_maps.get(p, {}).get(code)) for p in periods}
        dps = {p: _num(dps_maps.get(p, {}).get(code)) for p in dps_keys}
        if any(v is None for v in list(ocf_hist.values()) + list(dps.values())):
            continue  # 现金流/分红数据不全的不进池
        div_yield = round(sum(float(d) for d in dps.values()) / 3 / q["price"] * 100, 2) if q["price"] else 0.0
        div_yield_latest = round(float(dps[dps_keys[0]]) / q["price"] * 100, 2) if q["price"] else 0.0
        rows.append(
            {
                "code": code,
                "name": q["name"],
                "price": q["price"],
                "turnover_wan": q.get("turnover_wan"),
                "pe_ttm": q["pe_ttm"],
                "pb": q["pb"],
                "mcap_yi": q["mcap_yi"],
                "roe": round(roe_hist[annual] or 0, 2),
                "debt_ratio": debt_map.get(code),
                "ocf": {p: round(v, 2) for p, v in ocf_hist.items()},
                "ocf_hist": {p: round(v, 2) for p, v in ocf_hist.items()},
                "inv_hist": {p: round(v, 2) for p, v in inv_hist.items() if v is not None},
                "profit": round(profit_hist[annual] or 0, 2),
                "profit_hist": {p: round(v, 2) for p, v in profit_hist.items()},
                "roe_hist": {p: round(v, 2) for p, v in roe_hist.items()},
                "growth": (round(g, 2) if (g := _num(growth_map.get(code))) is not None else None),
                "dps": {p: round(v, 4) for p, v in dps.items()},
                "div_yield": div_yield,
                "div_yield_latest": div_yield_latest,
            }
        )
    return rows


def fetch_rows() -> list[dict]:
    """在线拉全量候选池行（v2：近5年报 ROE/净利/OCF 历史 + 最新增速）。

    东财批量表 11 张（yjbb×5 + xjll×5 + zcfz）+ 分红表 3 张 + 腾讯批量报价，约 2 分钟。
    """
    import akshare as ak

    _annual, _y2, _y3, interim = report_periods()
    hist = report_hist_periods()
    dps_periods = hist[:3]
    yjbb_hist = {p: ak.stock_yjbb_em(date=p) for p in hist}
    zcfz = ak.stock_zcfz_em(date=interim)
    xjll_hist = {p: ak.stock_xjll_em(date=p) for p in hist}
    fhps = {p: ak.stock_fhps_em(date=p) for p in dps_periods}

    codes = sorted({str(c) for c in zcfz["股票代码"]})
    quotes = fetch_quotes(codes)
    return build_rows(quotes, yjbb_hist, zcfz, xjll_hist, fhps)


def rows_cached(cache_dir: str | None, refresh: bool = False) -> list[dict]:
    """候选池行按天缓存（v3 schema：+inv_hist/+turnover_wan，TTL 6h）；refresh=True 或无缓存时在线拉取。"""
    if cache_dir:
        path = Path(cache_dir)
        path.mkdir(parents=True, exist_ok=True)
        cache_file = path / f"screen_rows_v3_{date.today().isoformat()}.json"
        if not refresh and cache_file.exists():
            age = time.time() - cache_file.stat().st_mtime
            if age < _ROWS_TTL_SECONDS:
                return json.loads(cache_file.read_text(encoding="utf-8"))
        rows = fetch_rows()
        cache_file.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        return rows
    return fetch_rows()


__all__ = [
    "build_rows",
    "rows_cached",
    "fetch_rows",
    "fetch_quotes",
    "report_periods",
    "report_hist_periods",
    "period_keys",
]
