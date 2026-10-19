"""买入指数：五步判断高 ROE 股票是否值得研究买入（0~100，越高越适合）。

五步框架（每维 0~1，权重加总归一）：

1. **持续性**（0.25）：近 3~5 年年报 ROE 均值与最低值——平时 5% 某年暴增 30% 的
   「昙花一现」压到 ≤0.2，只有连续多年稳定 15%+ 才拿满分。
2. **杠杆驱动**（0.15）：资产负债率（最近中报）<30% 满分，50% 一档，>70% 归零——
   高 ROE 若靠 70-80% 负债硬泡出来，警惕。
3. **估值**：PEG = PE(TTM)/净利润增速（0.15，≤0.5 满分，>2 归零档）+ PE 近五年
   历史分位（0.10，≤20% 满分，>80% 0.1 档——历史高位不追）。
4. **现金流**（0.20）：近 3~5 年经营现金流净额/净利润均值——利润是不是真金白银；
   任一年 OCF 为负直接 0。
5. **行业属性**（0.15）：东财行业分类关键词归类——强周期 0.2（高 ROE+低 PE 可能是
   周期顶陷阱）/ 中性 0.6 / 弱周期消费医药公用 1.0。

数据源：估值历史走百度股市通（近五年 PE，逐股，仅取预筛短名单）；行业归属走
东财 datacenter F10（逐股，30 天缓存）。维度缺数据时该维置 None 并权重归一。
命名按用户口径叫「买入指数」，输出仍为研究参考排序，不构成投资建议。
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime
from pathlib import Path

import httpx

WEIGHTS = {"roe": 0.25, "debt": 0.15, "peg": 0.15, "percentile": 0.10, "cash": 0.20, "industry": 0.15}

BUYINDEX_CALIBER = (
    "持续性25%(3~5年ROE稳定) + 杠杆15%(负债率) + PEG15% + PE五年分位10% + "
    "现金流20%(OCF/净利润,任一年为负归零) + 行业15%(强周期0.2/中性0.6/弱周期1.0)；"
    "缺数据维度权重归一。研究参考，非投资建议。"
)

_F10_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
_INDUSTRY_TTL = 30 * 86400
_PCT_TTL = 86400
_PREFILTER_TOP = 60  # 预筛后取前 N 只拉估值历史/行业（控制逐股请求数）

_CYCLICAL = (
    "钢铁", "煤炭", "石油", "化工", "化纤", "化肥", "塑料", "橡胶", "有色", "贵金属",
    "工业金属", "能源金属", "小金属", "采矿", "矿物", "冶炼", "航运", "港口", "航空",
    "船舶", "建材", "水泥", "玻璃", "玻纤", "房地产", "房屋建设", "工程建设", "装修",
    "农牧", "饲料", "养殖", "种业", "渔业", "造纸", "光伏", "风电", "贸易", "证券",
)
_DEFENSIVE = (
    "白酒", "啤酒", "酿酒", "饮料", "食品", "乳", "调味", "零食", "休闲食品", "医药",
    "医疗", "中药", "生物制品", "疫苗", "制药", "药", "医院", "体检", "电力", "燃气",
    "水务", "高速", "铁路", "机场", "保险", "游戏", "软件",
)


# ---- 五维评分（纯函数）----

def dim_roe(roe_hist: list[float] | None) -> float | None:
    """持续性：3~5 年 ROE 均值 + 最低值；不足 3 年不评（None）。"""
    if not roe_hist or len(roe_hist) < 3:
        return None
    vals = [float(v) for v in roe_hist if v is not None]
    if len(vals) < 3:
        return None
    mean_r = sum(vals) / len(vals)
    min_r = min(vals)
    latest = vals[0]  # 历史 Keys 按近→远排
    if latest >= 25 and mean_r < 12:
        return 0.2  # 昙花一现：平时平庸某年暴增
    if mean_r >= 20 and min_r >= 15:
        return 1.0
    if mean_r >= 15 and min_r >= 12:
        return 0.9
    if mean_r >= 15 and min_r >= 10:
        return 0.8
    if mean_r >= 15:
        return 0.45  # 均值高但某年跌破 10（波动大）
    if mean_r >= 10:
        return 0.4
    if mean_r >= 5:
        return 0.2
    return 0.0


def dim_debt(debt_ratio: float | None) -> float | None:
    """杠杆驱动：负债率越低越好（银行保险等高杠杆行业本就过不了 50% 一档）。"""
    if debt_ratio is None:
        return None
    if debt_ratio < 30:
        return 1.0
    if debt_ratio < 50:
        return 0.85
    if debt_ratio < 60:
        return 0.5
    if debt_ratio < 70:
        return 0.25
    return 0.0


def dim_peg(pe_ttm: float | None, growth_pct: float | None) -> float | None:
    """估值·PEG：亏损或增速失速时低分而非 None（这是负面证据，不是缺数据）。"""
    if pe_ttm is None or growth_pct is None:
        return None
    if pe_ttm <= 0:
        return 0.1  # 亏损，PEG 无意义
    if growth_pct <= 0:
        return 0.15  # 增长失速
    peg = pe_ttm / growth_pct
    if peg <= 0.5:
        return 1.0
    if peg <= 1.0:
        return 0.85
    if peg <= 1.5:
        return 0.6
    if peg <= 2.0:
        return 0.35
    return 0.1


def dim_percentile(pct: float | None) -> float | None:
    """估值·PE 近五年分位：≤20% 便宜买，>80% 历史高位不追。"""
    if pct is None:
        return None
    if pct <= 20:
        return 1.0
    if pct <= 40:
        return 0.85
    if pct <= 60:
        return 0.6
    if pct <= 80:
        return 0.35
    return 0.1


def dim_cash(ocf_hist: list[float], profit_hist: list[float]) -> float | None:
    """现金流：近 3~5 年 OCF/净利润 均值；任一年 OCF 为负直接 0。"""
    pairs = [
        (o, p)
        for o, p in zip(ocf_hist or [], profit_hist or [])
        if o is not None and p is not None
    ]
    if len(pairs) < 3:
        return None
    if any(float(o) <= 0 for o, _ in pairs):
        return 0.0
    ratios = [float(o) / float(p) for o, p in pairs if float(p) > 0]
    if not ratios:
        return 0.0  # 全部亏损年，现金质量无从谈起
    avg = sum(ratios) / len(ratios)
    if avg >= 1.2:
        return 1.0
    if avg >= 0.9:
        return 0.85
    if avg >= 0.6:
        return 0.65
    if avg >= 0.3:
        return 0.4
    return 0.2


def classify_industry(name: str | None) -> str:
    """东财行业名 → cyclical / neutral / defensive（关键词启发式）。"""
    if not name:
        return "neutral"
    for kw in _CYCLICAL:
        if kw in name:
            return "cyclical"
    for kw in _DEFENSIVE:
        if kw in name:
            return "defensive"
    return "neutral"


def dim_industry(name: str | None) -> float:
    """行业属性：强周期 0.2（高 ROE+低 PE 可能是周期顶）/ 中性 0.6 / 弱周期 1.0。"""
    cls = classify_industry(name)
    if cls == "cyclical":
        return 0.2
    if cls == "defensive":
        return 1.0
    return 0.6


def buy_index_total(dims: dict) -> float:
    """加权合计，缺数据维度（None）权重归一。"""
    num = sum(WEIGHTS[k] * v for k, v in dims.items() if v is not None)
    den = sum(WEIGHTS[k] for k, v in dims.items() if v is not None)
    return round(100 * num / den, 1) if den else 0.0


def buy_label(score: float) -> str:
    """买入指数 → 研究参考标签（非买卖指令）。"""
    if score >= 75:
        return "适合买入研究"
    if score >= 65:
        return "较适合研究"
    if score >= 50:
        return "一般"
    if score >= 35:
        return "偏弱"
    return "回避研究"


# ---- 数据获取（短名单逐股，带缓存）----

def fetch_pe_percentile(symbol: str) -> float | None:
    """百度股市通近五年 PE(TTM)：当前值在近五年中的分位（0~100，越低越便宜）。"""
    import akshare as ak

    hist = ak.stock_zh_valuation_baidu(symbol=symbol, indicator="市盈率(TTM)", period="近五年")
    vals = [float(v) for v in hist["value"] if v is not None]
    if len(vals) < 200:  # 不足一年的数据不谈分位
        return None
    current = vals[-1]
    below = sum(1 for v in vals if v <= current)
    return round(below / len(vals) * 100, 1)


def percentiles_cached(codes: list[str], cache_dir: str | None) -> dict[str, float | None]:
    """PE 分位按天缓存（逐股请求只花一天一次）。"""
    if not cache_dir:
        return {c: _safe_pct(c) for c in codes}
    path = Path(cache_dir)
    path.mkdir(parents=True, exist_ok=True)
    cache_file = path / f"pe_pct_{date.today().isoformat()}.json"
    if cache_file.exists() and time.time() - cache_file.stat().st_mtime < _PCT_TTL:
        cached: dict = json.loads(cache_file.read_text(encoding="utf-8"))
    else:
        cached = {}
    for code in codes:
        if code not in cached:
            cached[code] = _safe_pct(code)
            cache_file.write_text(json.dumps(cached, ensure_ascii=False), encoding="utf-8")
    return cached


def _safe_pct(code: str) -> float | None:
    try:
        return fetch_pe_percentile(code)
    except Exception:  # noqa: BLE001 - 单股失败不废整体
        return None


def fetch_industry(symbol: str, suffix: str) -> str | None:
    """东财 F10 基本资料 EM2016 行业字段（如 金融-银行-股份制与城商行）。"""
    resp = httpx.get(
        _F10_URL,
        params={
            "reportName": "RPT_F10_BASIC_ORGINFO",
            "columns": "EM2016",
            "filter": f'(SECUCODE="{symbol}.{suffix}")',
            "pageSize": "1",
            "source": "HSF10",
            "client": "PC",
        },
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=10,
    )
    resp.raise_for_status()
    data = (resp.json().get("result") or {}).get("data") or []
    return data[0].get("EM2016") if data else None


def industry_cached(pairs: list[tuple[str, str]], cache_dir: str | None) -> dict[str, str | None]:
    """行业归属 30 天缓存；pairs = [(code, suffix)]，suffix 为 SH/SZ。"""
    result: dict[str, str | None] = {}
    cache_file = None
    if cache_dir:
        path = Path(cache_dir)
        path.mkdir(parents=True, exist_ok=True)
        cache_file = path / "industry_map.json"
        if cache_file.exists() and time.time() - cache_file.stat().st_mtime < _INDUSTRY_TTL:
            cached: dict = json.loads(cache_file.read_text(encoding="utf-8"))
            result = {c: v for c, v in cached.items() if c in {p[0] for p in pairs}}
    for code, suffix in pairs:
        if code in result:
            continue
        try:
            result[code] = fetch_industry(code, suffix)
        except Exception:  # noqa: BLE001
            result[code] = None
        if cache_file:
            cache_file.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result


# ---- 编排 ----

def _market_suffix(code: str) -> str:
    return "SH" if code.startswith(("6",)) else "SZ"


def score_cheap(row: dict) -> dict:
    """只依赖候选池行的四维快评（持续性/杠杆/PEG/现金流），用于预筛排序。"""
    roe_hist = row.get("roe_hist") or []
    dims = {
        "roe": dim_roe(roe_hist),
        "debt": dim_debt(row.get("debt_ratio")),
        "peg": dim_peg(row.get("pe_ttm"), row.get("growth")),
        "cash": dim_cash(list((row.get("ocf_hist") or {}).values()), list((row.get("profit_hist") or {}).values())),
    }
    return {**dims, "cheap_total": buy_index_total(dims)}


def prefilter(rows: list[dict], top: int = _PREFILTER_TOP) -> list[tuple[dict, dict]]:
    """粗筛：ROE 均值≥12 且盈利，按四维快评分降序取前 top。"""
    cands = []
    for r in rows:
        roe_hist = [v for v in (r.get("roe_hist") or {}).values() if v]
        if not roe_hist or sum(roe_hist) / len(roe_hist) < 12:
            continue
        if not r.get("pe_ttm") or r["pe_ttm"] <= 0:
            continue
        dims = score_cheap(r)
        cands.append((r, dims))
    cands.sort(key=lambda pair: pair[1]["cheap_total"], reverse=True)
    return cands[:top]


def run_buy_index(rows: list[dict], cache_dir: str | None, refresh: bool = False) -> dict:
    """买入指数门面：候选池 → 预筛 → 逐股分位+行业 → 五维评分 TOP20。"""
    short = prefilter(rows)
    pairs = [(r["code"], _market_suffix(r["code"])) for r, _ in short]
    pct_map = percentiles_cached([r["code"] for r, _ in short], cache_dir)
    ind_map = industry_cached(pairs, cache_dir)

    items = []
    for r, cheap in short:
        code = r["code"]
        dims = {
            "roe": cheap["roe"],
            "debt": cheap["debt"],
            "peg": cheap["peg"],
            "percentile": dim_percentile(pct_map.get(code)),
            "cash": cheap["cash"],
            "industry": dim_industry(ind_map.get(code)),
        }
        total = buy_index_total(dims)
        roe_hist = [v for v in (r.get("roe_hist") or {}).values() if v]
        ocf_hist = r.get("ocf_hist") or {}
        profit_hist = r.get("profit_hist") or {}
        items.append(
            {
                "code": code,
                "name": r["name"],
                "price": r["price"],
                "pe_ttm": r["pe_ttm"],
                "pb": r["pb"],
                "buy_index": total,
                "label": buy_label(total),
                "dims": {k: (round(v * 100) if v is not None else None) for k, v in dims.items()},
                "roe_mean": round(sum(roe_hist) / len(roe_hist), 2) if roe_hist else None,
                "roe_min": round(min(roe_hist), 2) if roe_hist else None,
                "growth": r.get("growth"),
                "peg": round(r["pe_ttm"] / r["growth"], 2) if r.get("growth") and r["growth"] > 0 else None,
                "pe_pct": pct_map.get(code),
                "debt_ratio": r.get("debt_ratio"),
                "cash_ratio": (
                    round(
                        sum(float(o) / float(p) for o, p in zip(ocf_hist.values(), profit_hist.values()) if p)
                        / max(1, sum(1 for p in profit_hist.values() if p)),
                        2,
                    )
                    if ocf_hist and profit_hist
                    else None
                ),
                "industry": ind_map.get(code),
                "ocf": ocf_hist,
                "profit": profit_hist,
            }
        )
    items.sort(key=lambda x: x["buy_index"], reverse=True)
    items = items[:20]
    return {
        "kind": "buyindex",
        "asof": datetime.now().isoformat(timespec="seconds"),
        "universe": len(rows),
        "prefiltered": len(short),
        "caliber": BUYINDEX_CALIBER,
        "count": len(items),
        "items": items,
    }


__all__ = [
    "run_buy_index",
    "buy_index_total",
    "buy_label",
    "dim_roe",
    "dim_debt",
    "dim_peg",
    "dim_percentile",
    "dim_cash",
    "dim_industry",
    "classify_industry",
    "prefilter",
    "score_cheap",
    "percentiles_cached",
    "industry_cached",
    "fetch_pe_percentile",
    "fetch_industry",
    "WEIGHTS",
    "BUYINDEX_CALIBER",
]
