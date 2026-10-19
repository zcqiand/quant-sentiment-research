import React, { useEffect, useState } from 'react'
import { api } from './api.js'

const TABS = [
  { kind: 'whitehorse', label: '白马价值 TOP20', hint: '选价值成长：估值合理 + 高 ROE + 低负债 + 现金流扎实' },
  { kind: 'dividend', label: '高股息防守 TOP20', hint: '选防守：高股息 + 低 PB + 盈利为正 + 现金流扎实' },
  { kind: 'buyindex', label: '买入指数 TOP20', hint: '五步判断高ROE股：持续性/杠杆/估值(PEG+分位)/现金流/行业' },
]

const DIM_NAMES = { roe: '持续', debt: '杠杆', peg: 'PEG', percentile: '分位', cash: '现金', industry: '行业' }
const LABEL_CLASS = {
  适合买入研究: 'lab-good',
  较适合研究: 'lab-good',
  一般: 'lab-neutral',
  偏弱: 'lab-warn',
  回避研究: 'lab-bad',
}

const ocfSumYi = (r) => Object.values(r.ocf || {}).reduce((a, b) => a + b, 0) / 1e8

function DimCell({ v }) {
  if (v == null) return <span>—</span>
  const cls = v >= 80 ? 'up' : v <= 30 ? 'down' : ''
  return <span className={cls}>{v}</span>
}

export default function Screener({ onOpenStock }) {
  const [kind, setKind] = useState('whitehorse')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [msg, setMsg] = useState(null)
  const [added, setAdded] = useState({})

  const load = (k, refresh = false) => {
    setLoading(true)
    setMsg(null)
    api.screener(k, refresh)
      .then(setData)
      .catch((e) => { setData(null); setMsg({ kind: 'err', text: e.message }) })
      .finally(() => setLoading(false))
  }

  useEffect(() => { load(kind) }, [kind])

  const addWatch = async (row) => {
    try {
      await api.addStock(row.code, row.name)
      setAdded((m) => ({ ...m, [row.code]: true }))
    } catch (e) {
      setMsg({ kind: 'err', text: `${row.code}: ${e.message}` })
    }
  }

  const isBuy = kind === 'buyindex'
  const isDiv = kind === 'dividend'
  const tab = TABS.find((t) => t.kind === kind)
  const colCount = isBuy ? 10 : 9

  return (
    <div className="dashboard">
      <div className="toolbar">
        {TABS.map((t) => (
          <button key={t.kind} className={t.kind === kind ? 'nav active' : 'nav'} onClick={() => setKind(t.kind)}>
            {t.label}
          </button>
        ))}
        <button onClick={() => load(kind, true)} disabled={loading}>
          {loading
            ? (isBuy ? '计算中…（首次约3-5分钟）' : '选股中…（约1分钟）')
            : '↻ 强制刷新'}
        </button>
      </div>

      {data && (
        <p className="hint">
          候选池 {data.universe} 只{data.prefiltered != null ? ` · 预筛入围 ${data.prefiltered} 只` : ''} ·
          数据截至 {data.asof.replace('T', ' ')} · 口径：{data.caliber}
        </p>
      )}
      {msg && <div className={`msg msg-${msg.kind}`}>{msg.text}</div>}

      <table className="scan-table">
        <thead>
          <tr>
            <th>代码/名称</th>
            {isBuy && <th>买入指数</th>}
            {isBuy && <th>研究参考</th>}
            {!isBuy && <th>现价</th>}
            <th>PE(TTM)</th>
            {isBuy ? (
              <>
                <th title="近5年年报ROE均值/最低">ROE 5年均</th>
                <th title="PE(TTM)/净利润增速">PEG</th>
                <th title="当前PE在近五年的分位，越低越便宜">PE分位%</th>
                <th title="资产负债率%（最近中报）">负债率%</th>
                <th title="近3~5年经营现金流/净利润，任一年为负=0">OCF/净利</th>
                <th title="东财行业分类">行业</th>
              </>
            ) : (
              <>
                <th>PB</th>
                {isDiv ? <th>股息率%</th> : <th>ROE%</th>}
                {isDiv ? null : <th>负债率%</th>}
                <th>3年OCF(亿)</th>
                <th>市值(亿)</th>
              </>
            )}
            <th></th>
          </tr>
        </thead>
        <tbody>
          {(data?.items || []).map((r) => (
            <tr key={r.code} className="clickable" onClick={() => onOpenStock(r.code)}>
              <td className="sym">{r.code} {r.name}</td>
              {isBuy && (
                <td>
                  <span className={`score ${r.buy_index >= 65 ? 'score-up' : r.buy_index < 40 ? 'score-down' : ''}`}>
                    {r.buy_index}
                  </span>
                  <span className="dim-strip" title="五维分项(0-100)">
                    {Object.entries(DIM_NAMES).map(([k, n]) => (
                      <em key={k} className={r.dims?.[k] >= 80 ? 'up' : r.dims?.[k] <= 30 ? 'down' : ''}>
                        {n}{r.dims?.[k] ?? '—'}
                      </em>
                    ))}
                  </span>
                </td>
              )}
              {isBuy && <td><span className={`lab ${LABEL_CLASS[r.label] || 'lab-neutral'}`}>{r.label}</span></td>}
              {!isBuy && <td>{r.price?.toFixed(2)}</td>}
              <td className={r.pe_ttm <= 0 ? 'down' : ''}>{r.pe_ttm?.toFixed(1)}</td>
              {isBuy ? (
                <>
                  <td title={`最低 ${r.roe_min}`}>{r.roe_mean?.toFixed(1)}</td>
                  <td>{r.peg?.toFixed(2) ?? '—'}</td>
                  <td className={r.pe_pct <= 30 ? 'up' : r.pe_pct >= 80 ? 'down' : ''}>{r.pe_pct ?? '—'}</td>
                  <td>{r.debt_ratio?.toFixed(1) ?? '—'}</td>
                  <td className={r.cash_ratio >= 0.9 ? 'up' : r.cash_ratio != null && r.cash_ratio < 0.3 ? 'down' : ''}>
                    {r.cash_ratio ?? '—'}
                  </td>
                  <td className="sym" title={(r.industry || '')}>{r.industry || '—'}</td>
                </>
              ) : (
                <>
                  <td>{r.pb?.toFixed(2)}</td>
                  {isDiv ? <td className="up">{r.div_yield?.toFixed(2)}</td> : <td className="up">{r.roe?.toFixed(2)}</td>}
                  {isDiv ? null : <td>{r.debt_ratio?.toFixed(1)}</td>}
                  <td>{ocfSumYi(r).toFixed(1)}</td>
                  <td>{r.mcap_yi?.toFixed(0)}</td>
                </>
              )}
              <td>
                {added[r.code]
                  ? <span className="lab lab-good">已自选</span>
                  : <button className="link" onClick={(e) => { e.stopPropagation(); addWatch(r) }}>＋自选</button>}
              </td>
            </tr>
          ))}
          {!loading && data && data.count === 0 && (
            <tr><td colSpan={colCount} className="empty">无符合条件的标的</td></tr>
          )}
          {!data && !loading && !msg && (
            <tr><td colSpan={colCount} className="empty">{tab.hint}</td></tr>
          )}
        </tbody>
      </table>

      <p className="hint">
        {tab?.hint}
        {isBuy && '。五维分项在「买入指数」格内：持续/杠杆/PEG/分位/现金/行业（0-100）'}
        。选股结果为财务口径静态筛选，仅供研究参考，不构成买卖指令；点行可进个股详情看舆情与技术面。
      </p>
    </div>
  )
}
