import React, { useEffect, useMemo, useState } from 'react'
import { api } from './api.js'

// ---- 小工具 ----

const fmt = (v) => {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'string') return v
  if (Math.abs(v) >= 1000) return v.toFixed(0)
  if (Math.abs(v) >= 100) return v.toFixed(1)
  return String(v)
}

const emptyCondition = () => ({ metric: 'pe_ttm', op: '<', value: 20, min: null, max: null, negate: false })

function BacktestCard({ bt }) {
  if (!bt) return null
  const s = bt.stats || {}
  return (
    <div className="panel bt-panel">
      <h3>
        规则回测{' '}
        {s.n ? (
          <span className={bt.verdict?.ok ? 'lab lab-good' : 'lab lab-bad'}>
            {bt.verdict?.ok ? '达标' : '不达标'}
          </span>
        ) : null}
      </h3>
      {s.n ? (
        <div className="bt-cards">
          <div className="card"><div className="num">{s.n}</div><div className="cap">交易笔数</div></div>
          <div className="card"><div className="num">{s.win_rate != null ? `${(s.win_rate * 100).toFixed(0)}%` : '—'}</div><div className="cap">胜率</div></div>
          <div className="card"><div className="num">{s.payoff ?? '—'}</div><div className="cap">盈亏比</div></div>
          <div className="card"><div className="num">{s.max_dd != null ? `${(s.max_dd * 100).toFixed(1)}%` : '—'}</div><div className="cap">最大回撤</div></div>
          <div className="card"><div className="num">{s.sharpe ?? '—'}</div><div className="cap">夏普</div></div>
        </div>
      ) : (
        <p className="hint">本期无成交样本，无法评估。</p>
      )}
      {bt.verdict?.text && <p className="hint">{bt.verdict.text}</p>}
      {bt.note && <p className="hint">{bt.note}（覆盖 {bt.n_stocks} 只 · 按成交额取前250）</p>}
    </div>
  )
}

// ---- 单个条件行 ----

function ConditionRow({ cond, metrics, onChange, onRemove }) {
  const m = metrics.find((x) => x.key === cond.metric) || metrics[0]
  const ops = m?.ops || ['>', '>=', '<', '<=', 'between']
  const isText = m?.ops?.includes('contains')
  const isBool = m?.ops?.includes('eq') && !isText

  const set = (patch) => onChange({ ...cond, ...patch })

  const valueInput = () => {
    if (cond.op === 'between') {
      return (
        <>
          <input className="cond-num" type="number" step="any" placeholder="最小" value={cond.min ?? ''}
                 onChange={(e) => set({ min: e.target.value === '' ? null : Number(e.target.value) })} />
          <span className="hint">~</span>
          <input className="cond-num" type="number" step="any" placeholder="最大" value={cond.max ?? ''}
                 onChange={(e) => set({ max: e.target.value === '' ? null : Number(e.target.value) })} />
        </>
      )
    }
    if (isBool) {
      return (
        <select className="cond-num" value={cond.value ?? 1} onChange={(e) => set({ value: Number(e.target.value) })}>
          <option value={1}>是</option>
          <option value={0}>否</option>
        </select>
      )
    }
    if (isText) {
      return <input className="cond-num" placeholder="关键字" value={cond.value ?? ''}
                    onChange={(e) => set({ value: e.target.value })} />
    }
    return <input className="cond-num" type="number" step="any" value={cond.value ?? ''}
                  onChange={(e) => set({ value: e.target.value === '' ? null : Number(e.target.value) })} />
  }

  return (
    <div className="cond-row" title={m?.caliber}>
      <select className="cond-metric" value={cond.metric}
              onChange={(e) => {
                const nm = metrics.find((x) => x.key === e.target.value)
                const nop = nm.ops[0]
                set({
                  metric: e.target.value, op: nop,
                  value: nop === 'between' ? null : isBoolVal(nm) ? 1 : '',
                  min: null, max: null,
                })
              }}>
        {groupedMetrics(metrics).map(([cat, list]) => (
          <optgroup key={cat} label={cat}>
            {list.map((x) => <option key={x.key} value={x.key}>{x.name}</option>)}
          </optgroup>
        ))}
      </select>
      <select className="cond-op" value={cond.op} onChange={(e) => set({ op: e.target.value })}>
        {ops.map((o) => (
          <option key={o} value={o}>
            {{ '>': '>', '>=': '≥', '<': '<', '<=': '≤', between: '区间', eq: '=', contains: '含' }[o]}
          </option>
        ))}
      </select>
      {valueInput()}
      <label className="cond-negate hint">
        <input type="checkbox" checked={cond.negate} onChange={(e) => set({ negate: e.target.checked })} />
        排除
      </label>
      <button className="cond-del" onClick={onRemove} title="删除条件">✕</button>
    </div>
  )
}

const isBoolVal = (m) => m?.ops?.includes('eq') && !m?.ops?.includes('contains')

function groupedMetrics(metrics) {
  const order = ['基础信息', '估值', '财务', '技术', '风险过滤']
  const map = {}
  for (const m of metrics) (map[m.category] = map[m.category] || []).push(m)
  return order.filter((c) => map[c]).map((c) => [c, map[c]])
}

// ---- 主组件 ----

export default function Screener({ onOpenStock }) {
  const [metrics, setMetrics] = useState([])
  const [presets, setPresets] = useState([])
  const [rules, setRules] = useState([])
  const [rule, setRule] = useState(null)
  const [activePreset, setActivePreset] = useState(null)
  const [activeRuleName, setActiveRuleName] = useState('')
  const [saveName, setSaveName] = useState('')
  const [result, setResult] = useState(null)
  const [bt, setBt] = useState(null)
  const [busy, setBusy] = useState('')
  const [msg, setMsg] = useState(null)
  const [added, setAdded] = useState({})

  useEffect(() => {
    api.metrics().then((b) => setMetrics(b.metrics)).catch((e) => setMsg({ kind: 'err', text: e.message }))
    api.presets().then((b) => {
      setPresets(b.presets)
      if (b.presets.length) {
        setRule(JSON.parse(JSON.stringify(b.presets[0].rule)))
        setActivePreset(b.presets[0].key)
      }
    }).catch((e) => setMsg({ kind: 'err', text: e.message }))
    refreshRules()
  }, [])

  const refreshRules = () => {
    api.rules().then((b) => setRules(b.rules)).catch(() => {})
  }

  const metricKeys = useMemo(() => {
    if (!rule) return []
    const keys = rule.conditions.map((c) => c.metric)
    if (rule.rank) keys.push(rule.rank.metric)
    return [...new Set(keys)]
  }, [rule])

  const cols = useMemo(
    () => metricKeys.map((k) => ({ key: k, name: metrics.find((m) => m.key === k)?.name || k })),
    [metricKeys, metrics]
  )

  const patchRule = (patch) => {
    setRule((r) => ({ ...r, ...patch }))
    setActivePreset(null)
    setActiveRuleName('')
  }

  const loadPreset = (p) => {
    setRule(JSON.parse(JSON.stringify(p.rule)))
    setActivePreset(p.key)
    setActiveRuleName('')
    setResult(null)
    setBt(null)
  }

  const loadRule = (r) => {
    setRule(JSON.parse(JSON.stringify(r.spec)))
    setActiveRuleName(r.name)
    setActivePreset(null)
    setResult(null)
    setBt(null)
  }

  const runScreen = () => {
    setBusy('screen')
    setMsg(null)
    api.screen(rule)
      .then((b) => { setResult(b); setBt(null) })
      .catch((e) => setMsg({ kind: 'err', text: e.message }))
      .finally(() => setBusy(''))
  }

  const runBacktest = () => {
    setBusy('bt')
    setMsg(null)
    api.backtest(rule)
      .then(setBt)
      .catch((e) => setMsg({ kind: 'err', text: e.message }))
      .finally(() => setBusy(''))
  }

  const doSave = async () => {
    const name = (saveName || activeRuleName || '').trim()
    if (!name) { setMsg({ kind: 'err', text: '先填规则名再保存' }); return }
    try {
      await api.saveRule(name, rule)
      setSaveName('')
      setActiveRuleName(name)
      refreshRules()
      setMsg({ kind: 'ok', text: `已保存规则「${name}」（新版本）` })
    } catch (e) {
      setMsg({ kind: 'err', text: e.message })
    }
  }

  const doDelete = async () => {
    if (!activeRuleName) return
    try {
      await api.deleteRule(activeRuleName)
      setActiveRuleName('')
      refreshRules()
      setMsg({ kind: 'ok', text: `已删除规则「${activeRuleName}」` })
    } catch (e) {
      setMsg({ kind: 'err', text: e.message })
    }
  }

  const addWatch = async (r) => {
    try {
      await api.addStock(r.code, r.name, `条件选股·${activePreset ? presets.find((p) => p.key === activePreset)?.name : activeRuleName || '自定义'}`)
      setAdded((m) => ({ ...m, [r.code]: true }))
    } catch (e) {
      setMsg({ kind: 'err', text: `${r.code}: ${e.message}` })
    }
  }

  if (!rule) return <div className="hint" style={{ marginTop: 24 }}>加载指标目录…</div>

  const guard = result?.market_guard

  return (
    <div>
      {/* 现成方案：一键载入 */}
      <div className="preset-row">
        {presets.map((p) => (
          <button key={p.key}
                  className={`preset-card ${activePreset === p.key ? 'active' : ''}`}
                  onClick={() => loadPreset(p)}>
            <b>{p.name}</b>
            <span className="hint">{p.rule.conditions.length} 个条件 · 点击载入</span>
          </button>
        ))}
        <select className="rule-select"
                value={activeRuleName}
                onChange={(e) => {
                  const r = rules.find((x) => x.name === e.target.value)
                  if (r) loadRule(r)
                }}>
          <option value="">我的规则…</option>
          {rules.map((r) => <option key={r.name} value={r.name}>{r.name}（v{r.version}）</option>)}
        </select>
      </div>

      {/* 条件构建器 */}
      <div className="panel cond-panel">
        <div className="cond-head">
          <span className="hint">条件组合：</span>
          <button className={rule.logic === 'all' ? 'nav active' : 'nav'}
                  onClick={() => patchRule({ logic: 'all' })}>全部满足（AND）</button>
          <button className={rule.logic === 'any' ? 'nav active' : 'nav'}
                  onClick={() => patchRule({ logic: 'any' })}>任一满足（OR）</button>
        </div>
        {rule.conditions.map((c, i) => (
          <ConditionRow key={i} cond={c} metrics={metrics}
                        onChange={(nc) => patchRule({ conditions: rule.conditions.map((x, j) => (j === i ? nc : x)) })}
                        onRemove={() => patchRule({ conditions: rule.conditions.filter((_, j) => j !== i) })} />
        ))}
        <button className="link" onClick={() => patchRule({ conditions: [...rule.conditions, emptyCondition()] })}>
          ＋添加条件
        </button>

        <div className="cond-rank">
          {rule.rank ? (
            <>
              <span className="hint">排名取前</span>
              <input className="cond-num" type="number" min="1" max="100" value={rule.rank.top_pct}
                     onChange={(e) => patchRule({ rank: { ...rule.rank, top_pct: Number(e.target.value) } })} />
              <span className="hint">% 按</span>
              <select className="cond-op" value={rule.rank.metric}
                      onChange={(e) => patchRule({ rank: { ...rule.rank, metric: e.target.value } })}>
                {groupedMetrics(metrics).map(([cat, list]) => (
                  <optgroup key={cat} label={cat}>
                    {list.map((x) => <option key={x.key} value={x.key}>{x.name}</option>)}
                  </optgroup>
                ))}
              </select>
              <select className="cond-op" value={rule.rank.order}
                      onChange={(e) => patchRule({ rank: { ...rule.rank, order: e.target.value } })}>
                <option value="desc">降序</option>
                <option value="asc">升序</option>
              </select>
              <button className="link" onClick={() => patchRule({ rank: null })}>✕ 去掉排名</button>
            </>
          ) : (
            <button className="link" onClick={() => patchRule({ rank: { metric: 'div_yield', top_pct: 20, order: 'desc' } })}>
              ＋排名条件（取前 N%）
            </button>
          )}
        </div>

        <div className="cond-actions">
          <button className="primary" onClick={runScreen} disabled={!!busy}>
            {busy === 'screen' ? '筛选中…（首次约2-5分钟）' : '▶ 运行筛选'}
          </button>
          <button className="nav" onClick={runBacktest} disabled={!!busy}>
            {busy === 'bt' ? '回测中…' : '📊 回测验证'}
          </button>
          <span className="hint">|</span>
          <input className="save-name" placeholder="规则名（保存用）" value={saveName}
                 onChange={(e) => setSaveName(e.target.value)} />
          <button className="nav" onClick={doSave}>💾 保存规则</button>
          {activeRuleName && <button className="nav" onClick={doDelete}>🗑 删除「{activeRuleName}」</button>}
        </div>
        <p className="hint">
          指标口径悬停可见；数据缺失的条件一律「不命中并标注」；财务/估值条件无法历史重放
          （防未来数据泄漏），回测仅支持纯K线规则。
        </p>
      </div>

      {msg && <div className={`msg msg-${msg.kind}`}>{msg.text}</div>}
      {guard && (
        <div className={`msg ${guard.above_ma20 === true ? 'msg-ok' : guard.above_ma20 === false ? 'msg-err' : 'msg-info'}`}>
          🛡 大盘防守开关：{guard.text}
        </div>
      )}

      <BacktestCard bt={bt} />

      {result && (
        <>
          <p className="scan-ts">
            候选池 {result.universe} · K线扫描 {result.kline_scanned} · 慢指标补数 {result.slow_fetched} ·
            入选 {result.count} · {result.asof?.replace('T', ' ')}
          </p>
          {result.count > 0 ? (
            <table className="scan-table">
              <thead>
                <tr>
                  <th>代码/名称</th>
                  <th>现价</th>
                  {cols.map((c) => <th key={c.key}>{c.name}</th>)}
                  <th>入选原因</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {result.items.map((r) => (
                  <tr key={r.code} className="clickable" onClick={() => onOpenStock(r.code)}>
                    <td className="sym">{r.code} {r.name}</td>
                    <td>{r.price?.toFixed(2)}</td>
                    {cols.map((c) => <td key={c.key}>{fmt(r.values?.[c.key])}</td>)}
                    <td className="reasons">{r.reasons.join('；')}</td>
                    <td>
                      {added[r.code]
                        ? <span className="lab lab-good">已自选</span>
                        : <button className="link" onClick={(e) => { e.stopPropagation(); addWatch(r) }}>＋自选</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="msg msg-info">无标的通过全部条件——放宽阈值或换条件再试。</div>
          )}
        </>
      )}

      {result && result.manual_review?.length > 0 && result.count > 0 && (
        <div className="panel">
          <h3>人工清洗清单（买入前必查）</h3>
          <ul className="review-list">
            {result.manual_review.map((t) => <li key={t}>{t}</li>)}
          </ul>
        </div>
      )}
    </div>
  )
}
