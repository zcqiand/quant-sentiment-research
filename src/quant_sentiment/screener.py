"""价值选股器：白马价值 TOP20 / 高股息防守 TOP20。

口径（全 A，剔除 ST 与北交所）：

- **白马价值**：0 < PE(TTM) < 20 · ROE(最近披露完整年报·加权) > 15%
  · 资产负债率(最近中报) < 50% · 连续三个年报经营现金流净额 > 0，按 ROE 降序取 TOP。
- **高股息防守**：股息率(近三年年报每股股利均值/现价) > 5% · PB < 1.5 · PE(TTM) > 0
  （盈利为正，亏钱派息不是防守）· 现金流充足 = 连续三个年报经营现金流净额 > 0
  （近三年累计为正），按股息率降序取 TOP。

数据源：财务三表+分红表走东财 datacenter 批量接口（整表一次拉取），
行情（现价/PE-TTM/PB/市值）走腾讯 qt.gtimg.cn 批量报价（push2his 拉黑期的
独立通路）。候选池原始行按天落 JSON 缓存——盘前多次刷新不再打数据源。
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime
from pathlib import Path

import httpx

_TENCENT_URL = "https://qt.gtimg.cn/q="
_QUOTE_BATCH = 50
_ROWS_TTL_SECONDS = 6 * 3600  # 候选池行缓存半日，refresh=True 强制重拉

WHITEHORSE_CALIBER = "0<PE(TTM)<20 · ROE(最近年报加权)>15% · 资产负债率(最近中报)<50% · 连续3年年报经营现金流>0 · 按 ROE 降序"
DIVIDEND_CALIBER = "股息率(近三年年报每股股利均值/现价)>5% · PB<1.5 · PE(TTM)>0 · 连续3年年报经营现金流>0 · 按股息率降序"


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
    """解析 qt.gtimg.cn 响应：f1名称 f3现价 f39PE-TTM f45总市值(亿) f46PB。"""
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
    yjbb,
    zcfz,
    xjll_by_period: dict[str, "object"],
    fhps_by_period: dict[str, "object"],
) -> list[dict]:
    """财务表 × 行情快照 → 候选池行（纯函数，可测）。

    yjbb/zcfz/xjll/fhps 均为 pandas DataFrame（东财批量表），入参形状见 fetch 层。
    """
    annual, y2, y3, _interim = report_periods()
    roe_col = _col(yjbb, "净资产收益率", exclude=("扣非",))
    profit_col = _col(yjbb, "净利润", exclude=("增长", "环比", "扣非"))
    ocf_cols = {
        p: _col(df, ("经营活动产生的现金流量净额", "经营性现金流-现金流量净额"))
        for p, df in xjll_by_period.items()
    }
    dps_col = _col(fhps_by_period[annual], "现金分红比例")

    roe_map = dict(zip(yjbb["股票代码"], yjbb[roe_col]))
    profit_map = dict(zip(yjbb["股票代码"], yjbb[profit_col]))
    debt_map = {
        str(code): round(float(ratio), 2)
        for code, ratio in zip(zcfz["股票代码"], zcfz[_col(zcfz, "资产负债率")])
        if ratio and float(ratio) == float(ratio)
    }
    ocf_maps = {
        p: dict(zip(xjll_by_period[p]["股票代码"], xjll_by_period[p][ocf_cols[p]]))
        for p in xjll_by_period
    }
    dps_maps: dict[str, dict] = {}
    for p, df in fhps_by_period.items():
        implemented = df[df["方案进度"] == "实施分配"] if "方案进度" in df.columns else df
        per_share = implemented[dps_col] / 10.0  # 每10股派息 → 每股股利
        dps_maps[p] = dict(zip(implemented["代码"], per_share))

    rows: list[dict] = []
    keys = (annual, y2, y3)
    for code, q in quotes.items():
        if "ST" in q["name"].upper():
            continue
        ocf = {p: ocf_maps.get(p, {}).get(code) for p in keys}
        dps = {p: dps_maps.get(p, {}).get(code) for p in keys}
        if any(v is None or float(v) != float(v) for v in list(ocf.values()) + list(dps.values())):
            continue  # 财务数据不全的不进池
        div_yield = round(sum(float(d) for d in dps.values()) / 3 / q["price"] * 100, 2) if q["price"] else 0.0
        rows.append(
            {
                "code": code,
                "name": q["name"],
                "price": q["price"],
                "pe_ttm": q["pe_ttm"],
                "pb": q["pb"],
                "mcap_yi": q["mcap_yi"],
                "roe": round(float(roe_map.get(code, 0) or 0), 2),
                "debt_ratio": debt_map.get(code),
                "ocf": {p: round(float(v), 2) for p, v in ocf.items()},
                "profit": round(float(profit_map.get(code, 0) or 0), 2),
                "dps": {p: round(float(v), 4) for p, v in dps.items()},
                "div_yield": div_yield,
            }
        )
    return rows


def fetch_rows() -> list[dict]:
    """在线拉全量候选池行：东财财务四表 + 腾讯批量报价（约 1 分钟）。"""
    import akshare as ak

    annual, y2, y3, interim = report_periods()
    yjbb = ak.stock_yjbb_em(date=annual)
    zcfz = ak.stock_zcfz_em(date=interim)
    xjll = {p: ak.stock_xjll_em(date=p) for p in (annual, y2, y3)}
    fhps = {p: ak.stock_fhps_em(date=p) for p in (annual, y2, y3)}

    codes = sorted({str(c) for c in zcfz["股票代码"]})
    quotes = fetch_quotes(codes)
    return build_rows(quotes, yjbb, zcfz, xjll, fhps)


def rows_cached(cache_dir: str | None, refresh: bool = False) -> list[dict]:
    """候选池行按天缓存（TTL 6h）；refresh=True 或无缓存时在线拉取。"""
    if cache_dir:
        path = Path(cache_dir)
        path.mkdir(parents=True, exist_ok=True)
        cache_file = path / f"screen_rows_{date.today().isoformat()}.json"
        if not refresh and cache_file.exists():
            age = time.time() - cache_file.stat().st_mtime
            if age < _ROWS_TTL_SECONDS:
                return json.loads(cache_file.read_text(encoding="utf-8"))
        rows = fetch_rows()
        cache_file.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        return rows
    return fetch_rows()


# ---- 筛选（纯函数）----

def _ocf_positive_all(row: dict) -> bool:
    return all(isinstance(v, (int, float)) and v > 0 for v in row["ocf"].values())


def screen_white_horse(rows: list[dict], top: int = 20) -> list[dict]:
    """白马价值 TOP：PE 合理 + 高 ROE + 低负债 + 三年现金流为正，ROE 降序。"""
    picked = [
        r
        for r in rows
        if r["debt_ratio"] is not None
        and 0 < r["pe_ttm"] < 20
        and r["roe"] > 15
        and r["debt_ratio"] < 50
        and _ocf_positive_all(r)
        and "ST" not in r["name"].upper()
    ]
    picked.sort(key=lambda r: r["roe"], reverse=True)
    out = []
    for r in picked[:top]:
        out.append({**r, "ocf_total": round(sum(r["ocf"].values()), 2)})
    return out


def screen_dividend(rows: list[dict], top: int = 20) -> list[dict]:
    """高股息防守 TOP：股息率>5% + 破净/低PB + 盈利为正 + 连续三年现金流为正，股息率降序。"""
    picked = [
        r
        for r in rows
        if r["div_yield"] > 5
        and 0 < r["pb"] < 1.5
        and r["pe_ttm"] > 0
        and _ocf_positive_all(r)
        and "ST" not in r["name"].upper()
    ]
    picked.sort(key=lambda r: r["div_yield"], reverse=True)
    return picked[:top]


def run_screen(kind: str, cache_dir: str | None, refresh: bool = False) -> dict:
    """选股器门面：whitehorse / dividend。返回 {kind, asof, caliber, count, items}。"""
    if kind not in ("whitehorse", "dividend"):
        raise ValueError(f"未知选股器：{kind}")
    rows = rows_cached(cache_dir, refresh)
    if kind == "whitehorse":
        items = screen_white_horse(rows)
        caliber = WHITEHORSE_CALIBER
    else:
        items = screen_dividend(rows)
        caliber = DIVIDEND_CALIBER
    return {
        "kind": kind,
        "asof": datetime.now().isoformat(timespec="seconds"),
        "universe": len(rows),
        "caliber": caliber,
        "count": len(items),
        "items": items,
    }


__all__ = [
    "run_screen",
    "screen_white_horse",
    "screen_dividend",
    "build_rows",
    "rows_cached",
    "fetch_rows",
    "fetch_quotes",
    "report_periods",
    "period_keys",
    "WHITEHORSE_CALIBER",
    "DIVIDEND_CALIBER",
]
