import React, { useState } from 'react'
import { api } from './api.js'

// 金标回测：LLM 情绪判定 vs 人工金标（利好类 precision / recall）
export default function BacktestPanel() {
  const [symbol, setSymbol] = useState('')
  const [result, setResult] = useState(null)
  const [err, setErr] = useState(null)
  const [loading, setLoading] = useState(false)

  const run = async (e) => {
    e.preventDefault()
    if (!/^\d{6}$/.test(symbol)) {
      setErr('股票代码须为 6 位数字')
      return
    }
    setLoading(true)
    setErr(null)
    setResult(null)
    try {
      setResult(await api.backtest(symbol))
    } catch (e2) {
      setErr(e2.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="backtest">
      <h2>金标回测 · 情绪判定质量</h2>
      <p className="hint">
        把 LLM 的新闻情绪判定当分类器，与人工金标对比，评估「利好」类 precision / recall。
        金标文件放 <code>data/gold_&lt;代码&gt;.json</code>，格式：
        <code>{'{"新闻url或标题": "利好|利空|中性"}'}</code>
      </p>
      <form onSubmit={run} className="add-form">
        <input placeholder="股票代码 如 600000" value={symbol} onChange={(e) => setSymbol(e.target.value)} />
        <button className="primary" type="submit" disabled={loading}>
          {loading ? '回放中…' : '运行回测'}
        </button>
      </form>

      {err && <div className="msg msg-err">{err}</div>}
      {result && (
        <div className="bt-cards">
          <div className="card">
            <div className="num">{(result.precision * 100).toFixed(1)}%</div>
            <div className="cap">Precision（判利好里真利好的比例）</div>
          </div>
          <div className="card">
            <div className="num">{(result.recall * 100).toFixed(1)}%</div>
            <div className="cap">Recall（真利好被捞出来的比例）</div>
          </div>
          <div className="card">
            <div className="num">{result.samples}</div>
            <div className="cap">样本数（有金标的新闻）</div>
          </div>
          <div className="card">
            <div className="num">{result.gold_count}</div>
            <div className="cap">金标条数</div>
          </div>
        </div>
      )}
    </div>
  )
}
