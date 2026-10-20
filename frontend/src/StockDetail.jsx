import React, { useEffect, useState } from 'react'
import { api } from './api.js'
import KlineChart from './KlineChart.jsx'

// 个股极简详情：K线 + 交易计划 + 人工核查清单。只服务买卖决策，不做舆情。
export default function StockDetail({ symbol, onBack }) {
  const [data, setData] = useState(null)
  const [msg, setMsg] = useState(null)

  useEffect(() => {
    api.stockDetail(symbol)
      .then(setData)
      .catch((e) => setMsg({ kind: 'err', text: e.message }))
  }, [symbol])

  if (msg) {
    return (
      <div className="app">
        <button className="nav" onClick={onBack}>← 返回</button>
        <div className="msg msg-err" style={{ marginTop: 16 }}>{msg.text}</div>
      </div>
    )
  }
  if (!data) return <div className="app"><p className="hint">加载中…</p></div>

  const plan = data.plan || {}

  return (
    <div className="app">
      <div className="detail-head">
        <button className="nav" onClick={onBack}>← 返回</button>
        <h2>{symbol} {data.name}</h2>
        <div className="ind-chips">
          <span className="chip">现价 {data.price?.toFixed(2)}</span>
          <span className="chip">PE(TTM) {data.pe_ttm?.toFixed(1)}</span>
          <span className="chip">PB {data.pb?.toFixed(2)}</span>
          <span className="chip">市值 {data.mcap_yi?.toFixed(0)}亿</span>
        </div>
      </div>

      <KlineChart kline={data.kline || []} />

      <div className="detail-grid">
        <div className="panel">
          <h3>交易计划（纪律先行）</h3>
          <ul className="plan-list">
            <li><b>建仓</b>：{plan.position}</li>
            <li><b>止损</b>：{plan.stop}</li>
            <li><b>止盈</b>：{plan.take_profit}</li>
            <li><b>防守</b>：{plan.market_guard}</li>
          </ul>
        </div>
        <div className="panel">
          <h3>人工核查清单（买入前必查）</h3>
          <ul className="review-list">
            {(data.manual_review || []).map((t) => <li key={t}>{t}</li>)}
          </ul>
        </div>
      </div>
    </div>
  )
}
