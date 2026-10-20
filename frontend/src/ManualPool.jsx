import React, { useCallback, useEffect, useState } from 'react'
import { api } from './api.js'

// 人工池子：自己的自选名单 + 基础因子快照。机器筛概率，人来拿主意。
export default function ManualPool({ onOpenStock }) {
  const [data, setData] = useState(null)
  const [code, setCode] = useState('')
  const [note, setNote] = useState('')
  const [msg, setMsg] = useState(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    api.watchlist().then(setData).catch((e) => setMsg({ kind: 'err', text: e.message }))
  }, [])

  useEffect(() => { load() }, [load])

  const add = async () => {
    if (!/^\d{6}$/.test(code)) {
      setMsg({ kind: 'err', text: '请输入6位股票代码' })
      return
    }
    setBusy(true)
    setMsg(null)
    try {
      await api.addStock(code, '', note)
      setCode('')
      setNote('')
      load()
    } catch (e) {
      setMsg({ kind: 'err', text: e.message })
    } finally {
      setBusy(false)
    }
  }

  const remove = async (symbol) => {
    try {
      await api.removeStock(symbol)
      load()
    } catch (e) {
      setMsg({ kind: 'err', text: e.message })
    }
  }

  const items = data?.items || []

  return (
    <div>
      <div className="toolbar">
        <div className="add-form">
          <input
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
            placeholder="6位代码，如 600519"
            inputMode="numeric"
          />
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="备注（可选）"
            style={{ width: 200 }}
          />
          <button className="primary" onClick={add} disabled={busy}>＋加入人工池子</button>
        </div>
        <button onClick={load}>↻ 刷新快照</button>
      </div>

      {msg && <div className={`msg msg-${msg.kind}`}>{msg.text}</div>}

      <table className="scan-table">
        <thead>
          <tr>
            <th>代码/名称</th>
            <th>现价</th>
            <th>PE(TTM)</th>
            <th>PB</th>
            <th title="来自机器候选池的基础快照：ROE为最近年报">ROE%</th>
            <th title="近三年年报每股股利均值/现价">股息率%</th>
            <th title="资产负债率%（最近中报）">负债率%</th>
            <th>备注</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {items.map((r) => (
            <tr key={r.symbol} className="clickable" onClick={() => onOpenStock(r.symbol)}>
              <td className="sym">
                {r.symbol} {r.name || '—'}
                {r.in_pool
                  ? <span className="lab lab-good" title="在机器候选池内">池</span>
                  : <span className="lab lab-neutral" title="不在机器候选池内">池外</span>}
              </td>
              <td>{r.price?.toFixed(2) ?? '—'}</td>
              <td>{r.pe_ttm?.toFixed(1) ?? '—'}</td>
              <td>{r.pb?.toFixed(2) ?? '—'}</td>
              <td>{r.roe ?? '—'}</td>
              <td className={r.div_yield >= 4.5 ? 'up' : ''}>{r.div_yield ?? '—'}</td>
              <td>{r.debt_ratio ?? '—'}</td>
              <td className="hint">{r.note}</td>
              <td>
                <button className="link" onClick={(e) => { e.stopPropagation(); remove(r.symbol) }}>移除</button>
              </td>
            </tr>
          ))}
          {items.length === 0 && (
            <tr><td colSpan={9} className="empty">人工池子还是空的——从机器池子挑，或直接加代码</td></tr>
          )}
        </tbody>
      </table>

      <p className="hint">
        人工池子是你真正跟踪的名字：机器池子选出概率占优的，你在这里决定研究和买卖。
        行内「池」标=该股在当日机器候选池内；快照为最近一次选股数据，点行看K线与交易计划。
      </p>
    </div>
  )
}
