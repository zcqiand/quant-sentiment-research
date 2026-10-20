import React, { useEffect, useState } from 'react'
import MachinePool from './MachinePool.jsx'
import ManualPool from './ManualPool.jsx'
import StockDetail from './StockDetail.jsx'
import { api } from './api.js'

export default function App() {
  const [tab, setTab] = useState('machine')
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
            <span className="sub">机器池子筛概率 · 人工池子做决断 · 用历史大数据买概率</span>
          </div>
        </div>
        <div className="status">
          <span className={`chip ${health?.mode === 'online' ? 'chip-ok' : 'chip-warn'}`}>
            {health ? (health.mode === 'online' ? '数据在线' : '离线/缓存') : '…'}
          </span>
        </div>
      </header>

      <nav className="pool-tabs">
        <button className={tab === 'machine' ? 'nav active' : 'nav'} onClick={() => setTab('machine')}>
          机器池子
        </button>
        <button className={tab === 'manual' ? 'nav active' : 'nav'} onClick={() => setTab('manual')}>
          人工池子
        </button>
      </nav>

      {tab === 'machine' ? <MachinePool onOpenStock={openStock} /> : <ManualPool onOpenStock={openStock} />}

      <p className="foot">
        选股结果为量化因子筛选与历史回测，仅供研究参考，不构成买卖指令。
        五步SOP：底层逻辑 → 因子化 → 筛选+人工清洗 → 回测 → 执行与风控。
      </p>
    </div>
  )
}
