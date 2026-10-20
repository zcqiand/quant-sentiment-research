import React, { useEffect, useState } from 'react'
import Screener from './Screener.jsx'
import ManualPool from './ManualPool.jsx'
import StockDetail from './StockDetail.jsx'
import { api } from './api.js'

export default function App() {
  const [tab, setTab] = useState('screen')
  const [stock, setStock] = useState(null)
  const [health, setHealth] = useState(null)

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth({ mode: 'offline' }))
  }, [])

  const openStock = (code) => setStock(code)
  const closeStock = () => setStock(null)

  if (stock) return <StockDetail symbol={stock} onBack={closeStock} />

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo">📊</span>
          <div>
            <h1>个人选股工作台</h1>
            <span className="sub">条件选股 · 历史回测 · 用历史大数据买概率</span>
          </div>
        </div>
        <div className="status">
          <span className={`chip ${health?.mode === 'online' ? 'chip-ok' : 'chip-warn'}`}>
            {health ? (health.mode === 'online' ? '数据在线' : '离线/缓存') : '…'}
          </span>
        </div>
      </header>

      <nav className="pool-tabs">
        <button className={tab === 'screen' ? 'nav active' : 'nav'} onClick={() => setTab('screen')}>
          条件选股
        </button>
        <button className={tab === 'manual' ? 'nav active' : 'nav'} onClick={() => setTab('manual')}>
          人工池子
        </button>
      </nav>

      {tab === 'screen' ? <Screener onOpenStock={openStock} /> : <ManualPool onOpenStock={openStock} />}

      <p className="foot">
        选股结果为条件筛选与历史回测，仅供研究参考，不构成买卖指令。
        三层用法：现成方案 → 自定义条件 → 策略回测；买前过人工清洗清单。
      </p>
    </div>
  )
}
