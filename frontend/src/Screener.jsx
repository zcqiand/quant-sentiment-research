import React, { useEffect, useState } from 'react'
import { api } from './api.js'

const TABS = [
  { kind: 'whitehorse', label: '白马价值 TOP20', hint: '选价值成长：估值合理 + 高 ROE + 低负债 + 现金流扎实' },
  { kind: 'dividend', label: '高股息防守 TOP20', hint: '选防守：高股息 + 低 PB + 盈利为正 + 现金流扎实' },
]

const ocfSumYi = (r) => Object.values(r.ocf || {}).reduce((a, b) => a + b, 0) / 1e8

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

  const tab = TABS.find((t) => t.kind === kind)
  const isDiv = kind === 'dividend'

  return (
    <div className="dashboard">
      <div className="toolbar">
        {TABS.map((t) => (
          <button key={t.kind} className={t.kind === kind ? 'nav active' : 'nav'} onClick={() => setKind(t.kind)}>
            {t.label}
          </button>
        ))}
        <button onClick={() => load(kind, true)} disabled={loading}>
          {loading ? '选股中…（约1分钟）' : '↻ 强制刷新'}
        </button>
      </div>

      {data && (
        <p className="hint">
          候选池 {data.universe} 只 · 数据截至 {data.asof.replace('T', ' ')} · 口径：{data.caliber}
        </p>
      )}
      {msg && <div className={`msg msg-${msg.kind}`}>{msg.text}</div>}

      <table className="scan-table">
        <thead>
          <tr>
            <th>代码/名称</th>
            <th>现价</th>
            <th>PE(TTM)</th>
            <th>PB</th>
            {isDiv ? <th>股息率%</th> : <th>ROE%</th>}
            {isDiv ? null : <th>负债率%</th>}
            <th>3年OCF(亿)</th>
            <th>市值(亿)</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {(data?.items || []).map((r) => (
            <tr key={r.code} className="clickable" onClick={() => onOpenStock(r.code)}>
              <td className="sym">{r.code} {r.name}</td>
              <td>{r.price?.toFixed(2)}</td>
              <td className={r.pe_ttm <= 0 ? 'down' : ''}>{r.pe_ttm?.toFixed(1)}</td>
              <td>{r.pb?.toFixed(2)}</td>
              {isDiv ? <td className="up">{r.div_yield?.toFixed(2)}</td> : <td className="up">{r.roe?.toFixed(2)}</td>}
              {isDiv ? null : <td>{r.debt_ratio?.toFixed(1)}</td>}
              <td>{ocfSumYi(r).toFixed(1)}</td>
              <td>{r.mcap_yi?.toFixed(0)}</td>
              <td>
                {added[r.code]
                  ? <span className="lab lab-good">已自选</span>
                  : <button className="link" onClick={(e) => { e.stopPropagation(); addWatch(r) }}>＋自选</button>}
              </td>
            </tr>
          ))}
          {!loading && data && data.count === 0 && (
            <tr><td colSpan={9} className="empty">无符合条件的标的</td></tr>
          )}
          {!data && !loading && !msg && (
            <tr><td colSpan={9} className="empty">{tab.hint}</td></tr>
          )}
        </tbody>
      </table>

      <p className="hint">
        {tab?.hint}。选股结果为财务口径静态筛选，仅供研究参考，不构成买卖指令；
        点行可进个股详情看舆情与技术面。
      </p>
    </div>
  )
}
