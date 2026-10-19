import React, { useEffect, useState } from 'react'
import { api } from './api.js'
import KlineChart from './KlineChart.jsx'

const LABEL_CLASS = { 利好: 'lab-good', 利空: 'lab-bad', 中性: 'lab-neutral' }

export default function StockDetail({ symbol, onBack }) {
  const [detail, setDetail] = useState(null)
  const [err, setErr] = useState(null)
  const [researching, setResearching] = useState(false)

  const load = () => {
    api.stockDetail(symbol).then(setDetail).catch((e) => setErr(e.message))
  }
  useEffect(load, [symbol])

  const doResearch = async () => {
    setResearching(true)
    try {
      await api.research(symbol)
      load()
    } catch (e) {
      setErr(e.message)
    } finally {
      setResearching(false)
    }
  }

  if (err) {
    return (
      <div className="detail">
        <button className="nav" onClick={onBack}>← 返回看板</button>
        <div className="msg msg-err">{err}</div>
      </div>
    )
  }
  if (!detail) return <div className="detail">加载中…（首次研究该股需并行给新闻打分，约十几秒；再点就是缓存秒开）</div>

  const ind = detail.indicators || {}
  const latest = detail.latest

  return (
    <div className="detail">
      <div className="detail-head">
        <button className="nav" onClick={onBack}>← 返回看板</button>
        <h2>{detail.symbol} {detail.name}</h2>
        <button className="primary" onClick={doResearch} disabled={researching}>
          {researching ? '研究进行中…' : '🔍 重新研究'}
        </button>
      </div>

      <div className="ind-chips">
        <span className="chip">MA5 {ind.ma5?.toFixed?.(2) ?? '—'}</span>
        <span className="chip">MA20 {ind.ma20?.toFixed?.(2) ?? '—'}</span>
        <span className="chip">RSI {ind.rsi?.toFixed?.(1) ?? '—'}</span>
        <span className="chip">MACD DIF {ind.macd?.dif?.toFixed?.(3) ?? '—'}</span>
        <span className={`chip ${ind.technical_score > 0 ? 'chip-ok' : 'chip-warn'}`}>
          技术分 {ind.technical_score?.toFixed?.(2) ?? '—'}
        </span>
        {latest && (
          <span className={`chip ${latest.composite >= 30 ? 'chip-ok' : 'chip-warn'}`}>
            合成分 {latest.composite > 0 ? '+' : ''}{latest.composite} · {latest.composite_label}
          </span>
        )}
      </div>

      {detail.kline ? (
        <KlineChart kline={detail.kline} />
      ) : (
        <div className="kline-chart kline-missing">K 线数据暂时不可用（数据源限流中），舆情数据不受影响</div>
      )}

      <div className="detail-grid">
        <section className="panel">
          <h3>研究简报（最新）</h3>
          {latest ? (
            <>
              <pre className="report">{latest.report}</pre>
              <h4>证据链</h4>
              <ul className="evidence">
                {latest.evidence?.map((e, i) => (
                  <li key={i}>
                    <b>{e.claim}</b>
                    <small>{e.source_text} · {e.source_url} · {e.ts}</small>
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className="empty">还没有研究快照，点右上「重新研究」</p>
          )}
        </section>

        <section className="panel">
          <h3>新闻舆情（{detail.news.length}）</h3>
          <ul className="news">
            {detail.news.map((n, i) => (
              <li key={i}>
                <span className={`lab ${LABEL_CLASS[n.label] || 'lab-neutral'}`}>{n.label}</span>
                <div>
                  <a href={n.url} target="_blank" rel="noreferrer">{n.title}</a>
                  <small>{n.ts} · 置信度 {n.confidence}</small>
                </div>
              </li>
            ))}
            {detail.news.length === 0 && <li className="empty">暂无新闻</li>}
          </ul>
        </section>
      </div>
    </div>
  )
}
