import React, { useEffect, useState } from 'react'
import { api } from './api.js'

const STRATS = [
  { key: 'value', label: '模板A · 稳健价值' },
  { key: 'momentum', label: '模板B · 动量突破' },
]

function BacktestCard({ bt, note }) {
  if (!bt || !bt.stats || !bt.stats.n) {
    return (
      <div className="panel bt-panel">
        <h3>策略回测</h3>
        <p className="hint">本期无成交样本，无法评估。</p>
      </div>
    )
  }
  const s = bt.stats
  return (
    <div className="panel bt-panel">
      <h3>
        策略回测{' '}
        <span className={bt.verdict?.ok ? 'lab lab-good' : 'lab lab-bad'}>
          {bt.verdict?.ok ? '达标' : '不达标'}
        </span>
      </h3>
      <div className="bt-cards">
        <div className="card"><div className="num">{s.n}</div><div className="cap">交易笔数</div></div>
        <div className="card"><div className="num">{s.win_rate != null ? `${(s.win_rate * 100).toFixed(0)}%` : '—'}</div><div className="cap">胜率</div></div>
        <div className="card"><div className="num">{s.payoff ?? '—'}</div><div className="cap">盈亏比</div></div>
        <div className="card"><div className="num">{s.max_dd != null ? `${(s.max_dd * 100).toFixed(1)}%` : '—'}</div><div className="cap">最大回撤</div></div>
        <div className="card"><div className="num">{s.sharpe ?? '—'}</div><div className="cap">夏普</div></div>
      </div>
      <p className="hint">{bt.verdict?.text}{note ? ` · ${note}` : ''}</p>
    </div>
  )
}

function ValueRow({ r, added, onAdd, onOpen }) {
  const f = r.factors || {}
  const dot = (ok) => <em className={ok ? 'up' : 'down'}>{ok ? '●' : '○'}</em>
  return (
    <tr className="clickable" onClick={() => onOpen(r.code)}>
      <td className="sym">{r.code} {r.name}</td>
      <td>{r.price?.toFixed(2)}</td>
      <td title={`近3年报ROE：${(f.roe_hist || []).join(' / ')}`}>
        <span className={f.roe_ok ? 'up' : 'down'}>{f.roe_ok ? '✓' : '✗'}</span>
        {' '}{f.roe_hist?.[0]?.toFixed(1)}
      </td>
      <td title={f.growth_source}>
        <span className={f.growth_ok ? 'up' : 'down'}>{f.growth_ok ? '✓' : '✗'}</span>
        {' '}{f.growth_value?.toFixed(1) ?? '—'}%
      </td>
      <td title={`OCF/净利 ${f.cash_detail?.ocf_over_profit} · FCF合计 ${f.cash_detail ? (f.cash_detail.fcf_total / 1e8).toFixed(0) : '—'}亿`}>
        <span className={f.cash_ok ? 'up' : 'down'}>{f.cash_ok ? '✓' : '✗'}</span>
      </td>
      <td className={f.pe_ok ? 'up' : 'down'}>{f.pe_pct != null ? `${f.pe_pct}%` : '—'}</td>
      <td>{r.pe_ttm?.toFixed(1)}</td>
      <td>{r.mcap_yi?.toFixed(0)}亿</td>
      <td>
        {added[r.code]
          ? <span className="lab lab-good">已自选</span>
          : <button className="link" onClick={(e) => { e.stopPropagation(); onAdd(r) }}>＋自选</button>}
      </td>
    </tr>
  )
}

function MomentumRow({ r, added, onAdd, onOpen }) {
  const h = r.hits || {}
  return (
    <tr className="clickable" onClick={() => onOpen(r.code)}>
      <td className="sym">{r.code} {r.name}</td>
      <td>{r.price?.toFixed(2)}</td>
      <td><span className={h.above_ma20 ? 'up' : 'down'}>{h.above_ma20 ? '✓' : '✗'}</span></td>
      <td className={h.angle_ok ? 'up' : 'down'}>{h.angle}°</td>
      <td><span className={h.high60 ? 'up' : 'down'}>{h.high60 ? '✓' : '✗'}</span></td>
      <td className={h.volume_ok ? 'up' : 'down'}>{h.volume_ratio}</td>
      <td>{(r.turnover_wan / 1e4).toFixed(1)}亿</td>
      <td>{r.pe_ttm?.toFixed(1)}</td>
      <td>{r.mcap_yi?.toFixed(0)}亿</td>
      <td>
        {added[r.code]
          ? <span className="lab lab-good">已自选</span>
          : <button className="link" onClick={(e) => { e.stopPropagation(); onAdd(r) }}>＋自选</button>}
      </td>
    </tr>
  )
}

export default function MachinePool({ onOpenStock }) {
  const [key, setKey] = useState('value')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [msg, setMsg] = useState(null)
  const [added, setAdded] = useState({})

  const load = (k, refresh = false) => {
    setLoading(true)
    setMsg(null)
    api.strategy(k, refresh)
      .then(setData)
      .catch((e) => { setData(null); setMsg({ kind: 'err', text: e.message }) })
      .finally(() => setLoading(false))
  }

  useEffect(() => { load(key) }, [key])

  const addWatch = async (r) => {
    const note = key === 'value' ? '机器池子·稳健价值' : '机器池子·动量突破'
    try {
      await api.addStock(r.code, r.name, note)
      setAdded((m) => ({ ...m, [r.code]: true }))
    } catch (e) {
      setMsg({ kind: 'err', text: `${r.code}: ${e.message}` })
    }
  }

  const guard = data?.market_guard
  const isValue = key === 'value'

  return (
    <div>
      <div className="toolbar">
        {STRATS.map((s) => (
          <button key={s.key} className={s.key === key ? 'nav active' : 'nav'} onClick={() => setKey(s.key)}>
            {s.label}
          </button>
        ))}
        <button className="primary" onClick={() => load(key, true)} disabled={loading}>
          {loading ? '选股中…（首次约2-5分钟）' : '↻ 重新选股'}
        </button>
        {data && (
          <span className="scan-ts">
            候选池 {data.universe} · 可交易 {data.tradable} · 入池 {data.count} · {data.asof?.replace('T', ' ')}
          </span>
        )}
      </div>

      {guard && (
        <div className={`msg ${guard.above_ma20 === true ? 'msg-ok' : guard.above_ma20 === false ? 'msg-err' : 'msg-info'}`}>
          🛡 大盘防守开关：{guard.text}
        </div>
      )}
      {msg && <div className={`msg msg-${msg.kind}`}>{msg.text}</div>}

      {data && <BacktestCard bt={data.backtest} note={data.backtest_note} />}

      {data && data.count > 0 && (
        <table className="scan-table">
          <thead>
            <tr>
              <th>代码/名称</th>
              <th>现价</th>
              {isValue ? (
                <>
                  <th title="近3年报ROE全>15%">ROE持续</th>
                  <th title="扣非净利增速>20%（F10，缺失回退净利润同比）">增速%</th>
                  <th title="OCF/净利3年合计>1 且 FCF代理3年合计>0">现金流</th>
                  <th title="PE(TTM)近5年分位<20%，越低越便宜">PE分位%</th>
                </>
              ) : (
                <>
                  <th title="收盘>MA20">MA20</th>
                  <th title="MA20角度>30°（日斜率约0.58%）">角度</th>
                  <th title="收盘创60日新高">新高</th>
                  <th title="量比>2（今日量/5日均量）">量比</th>
                  <th>成交额</th>
                </>
              )}
              <th>PE</th>
              <th>市值</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((r) =>
              isValue ? (
                <ValueRow key={r.code} r={r} added={added} onAdd={addWatch} onOpen={onOpenStock} />
              ) : (
                <MomentumRow key={r.code} r={r} added={added} onAdd={addWatch} onOpen={onOpenStock} />
              )
            )}
          </tbody>
        </table>
      )}
      {data && data.count === 0 && !loading && (
        <div className="msg msg-info">本期无标的通过全部因子交叉——空仓也是策略。</div>
      )}

      {data && (
        <p className="hint">口径：{data.caliber}</p>
      )}
      {data && data.manual_review?.length > 0 && (
        <div className="panel">
          <h3>人工清洗清单（买入前必查）</h3>
          <ul className="review-list">
            {data.manual_review.map((t) => <li key={t}>{t}</li>)}
          </ul>
        </div>
      )}
    </div>
  )
}
