import React, { useEffect, useState } from 'react'
import { api } from './api.js'
import Dashboard from './Dashboard.jsx'
import StockDetail from './StockDetail.jsx'
import BacktestPanel from './BacktestPanel.jsx'

export default function App() {
  const [health, setHealth] = useState(null)
  const [view, setView] = useState('dashboard') // dashboard | detail | backtest
  const [selected, setSelected] = useState(null)

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth({ ok: false }))
  }, [])

  const openStock = (symbol) => {
    setSelected(symbol)
    setView('detail')
  }

  const llm = health?.llm || {}
  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo">📈</span>
          <div>
            <h1>股票交易个人工作台</h1>
            <span className="sub">舆情 × 技术面 · 研究参考非投资建议</span>
          </div>
        </div>
        <nav>
          <button className={view === 'dashboard' ? 'nav active' : 'nav'} onClick={() => setView('dashboard')}>
            盘前看板
          </button>
          <button className={view === 'backtest' ? 'nav active' : 'nav'} onClick={() => setView('backtest')}>
            金标回测
          </button>
        </nav>
        <div className="status">
          <span className={`chip ${llm.mode === 'fake' ? 'chip-warn' : 'chip-ok'}`}>
            LLM: {llm.model || llm.mode || '…'}
          </span>
          <span className={`chip ${health?.data?.online ? 'chip-ok' : 'chip-warn'}`}>
            {health?.data?.online ? '实时行情' : '离线数据'}
          </span>
        </div>
      </header>

      <main>
        {view === 'dashboard' && <Dashboard onOpenStock={openStock} />}
        {view === 'detail' && selected && (
          <StockDetail symbol={selected} onBack={() => setView('dashboard')} />
        )}
        {view === 'backtest' && <BacktestPanel />}
      </main>

      <footer className="foot">
        免责声明：本工具仅为个人研究与教学示例，所有输出不构成任何投资建议；买卖决策自负盈亏。
      </footer>
    </div>
  )
}
