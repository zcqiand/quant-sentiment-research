"""历史财务横截面快照——公告日期门控的 point-in-time 指标。

功能A（hist_analysis）要「按当时的数据」筛选：K线用截至历史日的前缀即可，
财务指标则必须还原「历史那天，市场实际已知的数字」——拿今天的财务快照
重放历史是未来数据泄漏。本模块以「报告期 × 全市场整表」为单位拉东财
业绩报表（yjbb）与资产负债表（zcfz），逐股取 asof 时「已知」的最新
报告期，拼出当时的：

已知判定（双门控）：东财「最新公告日期」会随事后更正/重述**前移**，
单靠它做历史门控会把全市场误判为「未公告」。所以公告日期 ≤ 历史日
→ 已知；历史日已过该报告期的法定披露截止（年报次年4-30/一季报4-30/
中报8-31/三季报10-31）→ 也已知（截止后必然全员披露完，无泄漏）。

- roe / roe_hist(近3年报) / growth / revenue_growth / industry ← 年报 yjbb
  （口径镜像 screener 现行：年报口径，不混季度）
- eps_ttm ← 年报EPS − 上年同期累计EPS + 最新累计EPS（TTM 拼接）
- bps ← 最新披露期 每股净资产（yjbb）
- debt_ratio ← zcfz 最新披露期 资产负债率

PE/PB 不在此算——需要历史日收盘价，由 hist_analysis 用「当时收盘 ÷ eps_ttm/bps」
拼出（与腾讯实时口径略有差异，notes 显式标注）。缺失一律 None（不当 0）。

不支持历史化的指标（PE分位/扣非增速/股息率/现金流族等）由 hist_supportable
拒绝——诚实拒绝而不是给虚高结果。整表按天缓存 data/yjbb_<报告期>_<日期>.json。
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from .conditions import METRICS

# 公告门控可还原的行指标（其余行指标历史化未实现 → 拒绝）
_HIST_ROW_OK = {"price", "industry", "float_mcap_yi", "pe_ttm", "pb",
                "roe", "roe_mean3", "roe_min3", "growth", "revenue_growth", "debt_ratio"}
# kind=slow 但可由前缀K线 point-in-time 判定的特例
_HIST_SLOW_OK = {"listed_2y"}

_ANNOUNCE_BUFFER_DAYS = 20  # 季度结束后不足 20 天不拉表（几乎无人披露，白拉）

# 法定披露截止（月-日）：全部 A 股必须在此前披露完该报告期
_DISCLOSE_DEADLINE = {"1231": (4, 30), "0331": (4, 30), "0630": (8, 31), "0930": (10, 31)}


def disclose_deadline(period: str) -> pd.Timestamp:
    """报告期的法定披露截止日（年报=次年4-30，一季报=4-30，中报=8-31，三季报=10-31）。"""
    md = _DISCLOSE_DEADLINE[period[4:]]
    year = int(period[:4]) + (1 if period.endswith("1231") else 0)
    return pd.Timestamp(year=year, month=md[0], day=md[1])


def hist_supportable(rule: dict) -> tuple[bool, str]:
    """历史验证准入门：纯K线 + 公告门控可还原的财务/估值条件放行，其余拒绝。"""
    metrics = {c["metric"] for c in rule["conditions"]}
    if rule.get("rank"):
        metrics.add(rule["rank"]["metric"])
    bad = sorted(
        m for m in metrics
        if not (METRICS[m]["kind"] == "kline"
                or m in _HIST_ROW_OK
                or m in _HIST_SLOW_OK)
    )
    if bad:
        names = "、".join(METRICS[m]["name"] for m in bad)
        return False, (
            f"规则含不支持历史验证的条件（{names}）：这些指标没有公告日期门控的历史快照，"
            "用今天的数值重放历史会引入未来数据泄漏——已支持纯K线与常用财务/估值条件"
            "（ROE/PE/PB/负债率/行业/流通市值近似等）。"
        )
    return True, ""


# ---- 报告期推算 ----

def quarter_ends_back(asof: pd.Timestamp, n: int) -> list[str]:
    """asof 前 n 个季度末（披露缓冲 20 天，近→远，YYYYMMDD）。"""
    cutoff = asof - pd.Timedelta(days=_ANNOUNCE_BUFFER_DAYS)
    qend = pd.Timestamp(year=cutoff.year, month=cutoff.month, day=1) + pd.offsets.MonthEnd(0)
    while qend > cutoff or qend.month % 3 != 0:
        qend -= pd.offsets.MonthEnd(1)
    out = []
    while len(out) < n:
        out.append(qend.strftime("%Y%m%d"))
        qend -= pd.offsets.MonthEnd(3)
    return out


def annual_periods(asof: pd.Timestamp, n: int = 3) -> list[str]:
    """asof 前 n 个年报报告期（YYYY1231，近→远）；年报 12-31 后不足 60 天不入候选。"""
    cutoff = asof - pd.Timedelta(days=60)
    out: list[str] = []
    y = cutoff.year
    if pd.Timestamp(year=y, month=12, day=31) > cutoff:
        y -= 1
    while len(out) < n:
        out.append(f"{y}1231")
        y -= 1
    return out


# ---- 列定位（关键词匹配，与 screener._col 同思路） ----

def _col(df: pd.DataFrame, keywords: tuple[str, ...], exclude: tuple[str, ...] = ()) -> str | None:
    for kw in keywords:
        for c in df.columns:
            if kw in c and not any(e in c for e in exclude):
                return c
    return None


def _num(v) -> float | None:
    try:
        f = float(v)
        return None if f != f else f
    except (TypeError, ValueError):
        return None


def _txt(v) -> str | None:
    """文本值清洗：dtype=str 读回时 NaN 会变 'nan' 字符串，归一成 None。"""
    s = None if v is None else str(v)
    return None if s in (None, "", "nan", "None", "NaT") else s


def _ann_ts(v) -> pd.Timestamp | None:
    """公告日期强转：日期串、datetime.date、epoch 毫秒（旧毒缓存）都接；解析不出 → None。"""
    try:
        if isinstance(v, str) and v.isdigit() or isinstance(v, (int, float)) and not isinstance(v, bool):
            n = int(v)
            if 10_000_000_000 <= n < 100_000_000_000_000:  # 1e11~1e14：只能是 epoch 毫秒
                return pd.Timestamp(n, unit="ms").normalize()
        return pd.Timestamp(v).normalize()
    except Exception:  # noqa: BLE001
        return None


def _tables_by_code(dfs: dict[str, pd.DataFrame], cols: dict[str, str | None]) -> dict[str, dict]:
    """{报告期: df} → {code: {报告期: {列别名: 值}}}；只保留定位到的列。"""
    out: dict[str, dict] = {}
    for period, df in dfs.items():
        keep = {alias: c for alias, c in cols.items() if c and c in df.columns}
        if "code" not in keep:
            continue
        for _, r in df.iterrows():
            code = str(r[keep["code"]])
            out.setdefault(code, {})[period] = {a: r[keep[a]] for a in keep if a != "code"}
    return out


# ---- 快照构建（纯函数） ----

def build_snapshots(asof: pd.Timestamp, yjbb: dict[str, pd.DataFrame],
                    zcfz: dict[str, pd.DataFrame], annuals: list[str]) -> dict[str, dict]:
    """逐股拼公告门控快照。yjbb 含年报+季度表；annuals 为年报报告期（近→远）。"""
    yj_cols = {
        "code": _col(yjbb[next(iter(yjbb))] if yjbb else pd.DataFrame(), ("股票代码",)),
        "announce": "最新公告日期", "eps": "每股收益", "bps": "每股净资产",
        "roe": "净资产收益率", "growth": "净利润-同比增长",
        "rev_growth": "营业总收入-同比增长", "industry": "所处行业",
    }
    per_code = _tables_by_code(yjbb, yj_cols) if yjbb else {}
    zc_cols = {"code": "股票代码", "announce": "公告日期", "debt": "资产负债率"}
    per_code_z = _tables_by_code(zcfz, zc_cols) if zcfz else {}

    snaps: dict[str, dict] = {}
    for code, periods in per_code.items():
        def announced(p: str) -> bool:
            """该股该报告期在 asof 时是否已知。双门控：
            公告日期 ≤ asof（记录未被事后更正前移时是准的），
            或 asof 已过法定披露截止（截止后必然全员披露完，无泄漏——
            东财「最新公告日期」会随更正/重示前移，单靠它历史快照会集体蒸发）。"""
            row = periods.get(p)
            if not row:
                return False
            if asof >= disclose_deadline(p):
                return True
            ann = _ann_ts(row.get("announce"))
            return ann is not None and ann <= asof

        def known(p: str, alias: str):
            return periods.get(p, {}).get(alias) if announced(p) else None

        # 年报族（近→远，仅取已公告的）
        eff_annuals = [p for p in annuals if announced(p)]
        roe_hist = {p: _num(known(p, "roe")) for p in eff_annuals}
        latest_annual = eff_annuals[0] if eff_annuals else None
        out = {
            "roe": round(roe_hist[latest_annual], 2) if latest_annual and roe_hist[latest_annual] is not None else None,
            "roe_hist": roe_hist if len(roe_hist) >= 3 else None,
            "growth": (round(g, 2) if latest_annual and (g := _num(known(latest_annual, "growth"))) is not None else None),
            "revenue_growth": (round(g, 2) if latest_annual and (g := _num(known(latest_annual, "rev_growth"))) is not None else None),
            "industry": (_txt(v) if latest_annual and (v := known(latest_annual, "industry")) is not None else None),
        }
        # TTM EPS：年报EPS − 上年同期累计EPS + 最新累计EPS
        quarters = sorted((p for p in periods if not p.endswith("1231")), reverse=True)
        eps_ttm = None
        if latest_annual:
            annual_eps = _num(known(latest_annual, "eps"))
            eff_q = next((q for q in quarters if announced(q)), None)
            if annual_eps is not None and eff_q is None:
                eps_ttm = annual_eps  # 最新可得就是年报 → TTM=年报EPS
            elif annual_eps is not None and eff_q is not None:
                qy = int(eff_q[:4])
                prev_same = f"{qy - 1}{eff_q[4:]}"
                prev_annual = f"{qy - 1}1231"
                cum_q = _num(known(eff_q, "eps"))
                cum_prev = _num(known(prev_same, "eps"))
                ann_prev = _num(known(prev_annual, "eps"))
                if None not in (cum_q, cum_prev, ann_prev):
                    eps_ttm = round(ann_prev - cum_prev + cum_q, 4)
        out["eps_ttm"] = eps_ttm
        # BPS：最新披露期（季度优先，否则最新年报）
        bps = None
        for p in quarters + list(reversed(annuals)):
            v = _num(known(p, "bps"))
            if v is not None:
                bps = v
                break
        out["bps"] = bps
        # 负债率：zcfz 公告门控（同款双门控），取已知的最新报告期
        debt, debt_p = None, ""
        for p, rows in (per_code_z.get(code) or {}).items():
            if asof < disclose_deadline(p):
                ann = _ann_ts(rows.get("announce"))
                if ann is None or ann > asof:
                    continue
            if _num(rows.get("debt")) is not None and p > debt_p:
                debt, debt_p = round(_num(rows["debt"]), 2), p
        out["debt_ratio"] = debt
        snaps[code] = out
    return snaps


# ---- 拉取层（按天缓存，测试 monkeypatch 桩） ----

def _fetch_yjbb(period: str):
    import akshare as ak
    return ak.stock_yjbb_em(date=period)


def _fetch_zcfz(period: str):
    import akshare as ak
    return ak.stock_zcfz_em(date=period)


def _cached_table(name: str, period: str, cache_dir: str | None, fetcher) -> pd.DataFrame | None:
    path = None
    if cache_dir:
        path = Path(cache_dir) / f"{name}_{period}_{date.today().isoformat()}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            try:
                # 全列按 str 读回：read_json 会把「000333」推断成整数 333，
                # 前导零丢失=深市代码全体失配；数值/日期交给 _num/_ann_ts 强转
                return pd.read_json(path, dtype=str)
            except Exception:  # noqa: BLE001 — 缓存损坏重拉
                pass
    try:
        df = fetcher(period)
    except Exception:  # noqa: BLE001 — 单表失败不废整体（对应指标按缺失处理）
        return None
    if path is not None:
        try:
            # date_format 必须显式 iso：默认 epoch 会把公告日期写成 1773100800000，
            # 读回解析失败 = 全市场「未公告」（2026-10-20 roe_hist 蒸发事故）
            df.to_json(path, orient="records", force_ascii=False, date_format="iso")
        except Exception:  # noqa: BLE001
            pass
    return df


def fetch_hist_fundamentals(asof: str, rule: dict, cache_dir: str | None) -> tuple[dict[str, dict], list[str]]:
    """编排：按规则所需指标拉表（按天缓存）→ 快照。供 hist_analysis 调用。

    返回 (快照, 警告列表)。年报表拉取失败必须进警告——少一张年报 roe_hist
    全市场蒸发，静默跳过=用户拿着瘸腿结果不自知（2026-10-20 事故）。
    """
    ts = pd.Timestamp(asof).normalize()
    metrics = {c["metric"] for c in rule["conditions"]}
    if rule.get("rank"):
        metrics.add(rule["rank"]["metric"])
    annuals = annual_periods(ts)
    yjbb: dict[str, pd.DataFrame] = {}
    zcfz: dict[str, pd.DataFrame] = {}
    warns: list[str] = []
    needs_valuation = bool({"pe_ttm", "pb"} & metrics)
    needs_debt = "debt_ratio" in metrics
    if any(m in metrics for m in _HIST_ROW_OK - {"price", "float_mcap_yi"}):
        periods = list(annuals)
        if needs_valuation or needs_debt:
            periods += [p for p in quarter_ends_back(ts, 6) if p not in annuals]
        for p in periods:
            df = _cached_table("yjbb", p, cache_dir, _fetch_yjbb)
            if df is None:
                if p in annuals:
                    warns.append(f"业绩报表(yjbb) {p} 拉取失败——该年报相关指标按缺失处理，建议重跑。")
                continue
            yjbb[p] = df
        if needs_debt:
            for p in quarter_ends_back(ts, 2):
                df = _cached_table("zcfz", p, cache_dir, _fetch_zcfz)
                if df is None:
                    warns.append(f"资产负债表(zcfz) {p} 拉取失败——负债率按缺失处理，建议重跑。")
                    continue
                zcfz[p] = df
    return build_snapshots(ts, yjbb, zcfz, annuals), warns
