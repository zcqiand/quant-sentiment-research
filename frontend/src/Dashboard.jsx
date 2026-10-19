import React, { useEffect, useState } from 'react'
import { api } from './api.js'

const LABEL_CLASS = {
  重点关注: 'lab-hot',
  关注: 'lab-good',
  观望: 'lab-neutral',
  谨慎: 'lab-warn',
  回避研究: 'lab-bad',
}

function fmtPrice(row) {
  return row.price != null ? row.price.toFixed(2) : '—'
}

export default function Dashboard({ onOpenStock }) {
  const [rows, setRows] = useState([])
  const [errors, setErrors] = useState([])
  const [watchlist, setWatchlist] = useState([])
  const [scanning, setScanning] = useState(false)
  const [scanTs, setScanTs] = useState(null)
  const [msg, setMsg] = useState(null)
  const [newSymbol, setNewSymbol] = useState('')
  const [newName, setNewName] = useState('')

  const loadLatest = () => {
    api.latestScan().then((s) => {
      setRows((s.results || []).slice().sort((a, b) => b.composite - a.composite))
      setErrors(s.errors || [])
      setScanTs(s.ts)
    }).catch(() => setMsg({ kind: 'info', text: '还没有扫描记录，点「一键盘前扫描」开始' }))
  }

  useEffect(() => {
    api.watchlist().then(setWatchlist).catch(() => {})
    loadLatest()
  }, [])

  const doScan = async () => {
    setScanning(true)
    setMsg(null)
    try {
      const s = await api.scan()
      setRows((s.results || []).slice().sort((a, b) => b.composite - a.composite))
      setErrors(s.errors || [])
      setScanTs(s.ts)
      setMsg({ kind: 'ok', text: `扫描完成：${s.results.length} 只成功，${s.errors.length} 只失败` })
    } catch (e) {
      setMsg({ kind: 'err', text: `扫描失败：${e.message}` })
    } finally {
      setScanning(false)
    }
  }

  const addStock = async (e) => {
    e.preventDefault()
    if (!/^\d{6}$/.test(newSymbol)) {
      setMsg({ kind: 'err', text: '股票代码须为 6 位数字' })
      return
    }
    try {
      await api.addStock(newSymbol, newName)
      setWatchlist(await api.watchlist())
      setNewSymbol('')
      setNewName('')
      setMsg({ kind: 'ok', text: '已加入自选' })
    } catch (e2) {
      setMsg({ kind: 'err', text: e2.message })
    }
  }

  const removeStock = async (symbol) => {
    await api.removeStock(symbol).catch(() => {})
    setWatchlist(await api.watchlist())
  }

  return (
    <div className="dashboard">
      <div className="toolbar">
        <button className="primary" onClick={doScan} disabled={scanning}>
          {scanning ? '扫描中…（舆情打分需要点时间）' : '⚡ 一键盘前扫描'}
        </button>
        <form className="add-form" onSubmit={addStock}>
          <input placeholder="代码 如 600000" value={newSymbol} onChange={(e) => setNewSymbol(e.target.value)} />
          <input placeholder="名称（可选）" value={newName} onChange={(e) => setNewName(e.target.value)} />
          <button type="submit">＋ 自选</button>
        </form>
        {scanTs && <span className="scan-ts">数据时间 {scanTs.replace('T', ' ')}</span>}
      </div>

      {msg && <div className={`msg msg-${msg.kind}`}>{msg.text}</div>}

      {watchlist.length > 0 && (
        <div className="watchlist-bar">
          自选：
          {watchlist.map((w) => (
            <span key={w.symbol} className="watch-chip">
              <button className="link" onClick={() => onOpenStock(w.symbol)}>
                {w.name || w.symbol}
              </button>
              <button className="x" title="移除" onClick={() => removeStock(w.symbol)}>×</button>
            </span>
          ))}
        </div>
      )}

      {errors.length > 0 && (
        <div className="msg msg-err">
          {errors.map((e) => (
            <div key={e.symbol}>{e.symbol}: {e.error}</div>
          ))}
        </div>
      )}

      <table className="scan-table">
        <thead>
          <tr>
            <th>合成分</th>
            <th>信号</th>
            <th>代码/名称</th>
            <th>现价</th>
            <th>涨跌%</th>
            <th>技术面</th>
            <th>舆情(多/空/中)</th>
            <th>热度</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.symbol} className="clickable" onClick={() => onOpenStock(r.symbol)}>
              <td>
                <span className={`score ${r.composite >= 30 ? 'score-up' : r.composite <= -30 ? 'score-down' : ''}`}>
                  {r.composite > 0 ? '+' : ''}{r.composite}
                </span>
              </td>
              <td><span className={`lab ${LABEL_CLASS[r.composite_label] || 'lab-neutral'}`}>{r.composite_label}</span></td>
              <td className="sym">{r.symbol} {r.name}</td>
              <td>{fmtPrice(r)}</td>
              <td className={r.change_pct > 0 ? 'up' : r.change_pct < 0 ? 'down' : ''}>
                {r.change_pct > 0 ? '+' : ''}{r.change_pct?.toFixed(2)}
              </td>
              <td>
                {r.technical?.trend} <small>({r.technical?.score})</small>
              </td>
              <td>
                {r.sentiment?.bull}/{r.sentiment?.bear}/{r.sentiment?.neutral}
              </td>
              <td>{r.heat}</td>
              <td>
                <button className="link" onClick={(e) => { e.stopPropagation(); onOpenStock(r.symbol) }}>详情 →</button>
              </td>
            </tr>
          ))}
          {rows.length === 0 && !scanning && (
            <tr><td colSpan={9} className="empty">暂无扫描结果 —— 添加自选股后点「一键盘前扫描」</td></tr>
          )}
        </tbody>
      </table>

      <p className="hint">
        合成分 = 45% 舆情 + 45% 技术面 + 10% 资金热度，范围 ±100；仅供研究排序参考，不构成买卖指令。
      </p>
    </div>
  )
}
