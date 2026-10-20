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
const deepcopy = (x) => JSON.parse(JSON.stringify(x))

// 条件 → 可读文案（清单展示用）
const OP_TXT = { '>': '大于', '>=': '不小于', '<': '小于', '<=': '不大于' }

function condText(c, metrics) {
  const m = metrics.find((x) => x.key === c.metric)
  const name = m?.name || c.metric
  let body
  if (c.op === 'between') body = `介于 ${c.min} ~ ${c.max}`
  else if (c.op === 'eq') body = c.value ? '为是' : '为否'
  else if (c.op === 'contains') body = `含「${c.value}」`
  else body = `${OP_TXT[c.op] || c.op} ${c.value}`
  const text = `${name} ${body}`
  return c.negate ? { exclude: true, text } : { exclude: false, text }
}

function rankText(rank, metrics) {
  if (!rank) return null
  const name = metrics.find((x) => x.key === rank.metric)?.name || rank.metric
  return `按${name}${rank.order === 'asc' ? '升序' : '降序'}取前 ${rank.top_pct}%`
}

// ---- 单个条件行（编辑器内） ----

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
                  value: nop === 'between' ? null : nm.ops.includes('eq') && !nm.ops.includes('contains') ? 1 : '',
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

function groupedMetrics(metrics) {
  const order = ['基础信息', '估值', '财务', '技术', '风险过滤']
  const map = {}
  for (const m of metrics) (map[m.category] = map[m.category] || []).push(m)
  return order.filter((c) => map[c]).map((c) => [c, map[c]])
}

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

// ---- 历史选股表现分析（功能A） ----

const defaultHistDate = () => {
  const d = new Date()
  d.setMonth(d.getMonth() - 6)
  return d.toISOString().slice(0, 10)
}

const pct = (v) => (v == null ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(2)}%`)

function HistPanel({ spec, hist, setHist }) {
  const run = () => {
    setHist((h) => ({ ...h, busy: true, err: null }))
    api.histScreen(spec, hist.date)
      .then((b) => setHist((h) => ({ ...h, busy: false, data: b })))
      .catch((e) => setHist((h) => ({ ...h, busy: false, err: e.message })))
  }
  const d = hist.data
  return (
    <div className="panel hist-panel">
      <h3>历史选股表现分析</h3>
      <p className="hint">
        按所选历史日期「当时可得」的数据筛选（仅纯K线组合），统计入选股持有 20/60/120
        交易日的收益率，对照同期上证基准。信号次日收盘入场，无止损无成本。
      </p>
      <div className="hist-bar">
        <span className="hint">历史日期</span>
        <input type="date" value={hist.date} max={new Date().toISOString().slice(0, 10)}
               onChange={(e) => setHist((h) => ({ ...h, date: e.target.value }))} />
        <button className="primary" onClick={run} disabled={hist.busy}>
          {hist.busy ? '分析中…（首次约2-5分钟）' : '▶ 分析'}
        </button>
      </div>
      {hist.err && <div className="msg msg-err">{hist.err}</div>}
      {d && (
        <>
          <div className="bt-cards">
            <div className="card"><div className="num">{d.count}</div><div className="cap">当时入选（只）</div></div>
            {['20', '60', '120'].map((h) => {
              const s = d.horizons[h] || {}
              return (
                <div className="card" key={h}>
                  <div className="num">{s.mean != null ? pct(s.mean) : '—'}</div>
                  <div className="cap">持有{h}日 平均</div>
                  <div className="cap">
                    中位 {s.median != null ? pct(s.median) : '—'} · 盈利 {s.win_rate != null ? `${(s.win_rate * 100).toFixed(0)}%` : '—'}
                    {s.excess_mean != null ? ` · 超基准 ${pct(s.excess_mean)}` : (d.benchmark?.[h] != null ? ` · 基准 ${pct(d.benchmark[h])}` : '')}
                  </div>
                </div>
              )
            })}
          </div>
          {d.count > 0 && (
            <table className="scan-table">
              <thead>
                <tr>
                  <th>代码/名称</th>
                  <th>当时收盘</th>
                  <th>次日入场</th>
                  <th>20日</th>
                  <th>60日</th>
                  <th>120日</th>
                </tr>
              </thead>
              <tbody>
                {d.items.map((it) => (
                  <tr key={it.code}>
                    <td className="sym">{it.code} {it.name}</td>
                    <td>{it.price?.toFixed(2)}</td>
                    <td>{it.entry_close?.toFixed(2) ?? '—'}</td>
                    {['ret20', 'ret60', 'ret120'].map((k) => (
                      <td key={k} className={it[k] == null ? '' : it[k] > 0 ? 'up' : 'down'}>{pct(it[k])}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <ul className="hist-notes">
            {(d.notes || []).map((n) => <li key={n}>{n}</li>)}
          </ul>
        </>
      )}
    </div>
  )
}

// ---- 主组件：清单一整屏 → 点进组合详情页 ----

export default function Screener({ onOpenStock }) {
  const [metrics, setMetrics] = useState([])
  const [plans, setPlans] = useState([]) // [{id, name, builtin, version?, spec}]
  const [current, setCurrent] = useState(null) // 详情页的组合；null=清单页
  const [result, setResult] = useState(null)
  const [bt, setBt] = useState(null)
  const [busy, setBusy] = useState('')
  const [msg, setMsg] = useState(null)
  const [added, setAdded] = useState({})
  const [draft, setDraft] = useState(null) // {name, originName?, spec} 编辑器打开时非空
  const [hist, setHist] = useState({ open: false, date: defaultHistDate(), data: null, busy: false, err: null })

  useEffect(() => {
    api.metrics().then((b) => setMetrics(b.metrics)).catch((e) => setMsg({ kind: 'err', text: e.message }))
    refreshPlans()
  }, [])

  const refreshPlans = () => {
    Promise.all([api.presets(), api.rules()])
      .then(([pb, rb]) => {
        setPlans([
          ...pb.presets.map((p) => ({ id: `preset:${p.key}`, name: p.name, builtin: true, desc: p.desc, spec: p.rule })),
          ...rb.rules.map((r) => ({ id: `rule:${r.name}`, name: r.name, builtin: false, version: r.version, spec: r.spec })),
        ])
      })
      .catch((e) => setMsg({ kind: 'err', text: e.message }))
  }

  const metricKeys = useMemo(() => {
    const spec = draft?.spec || current?.spec
    if (!spec) return []
    const keys = spec.conditions.map((c) => c.metric)
    if (spec.rank) keys.push(spec.rank.metric)
    return [...new Set(keys)]
  }, [draft, current])

  const cols = useMemo(
    () => metricKeys.map((k) => ({ key: k, name: metrics.find((m) => m.key === k)?.name || k })),
    [metricKeys, metrics]
  )

  // ---- 动作 ----

  const runScreen = (spec) => {
    setBusy('screen')
    setMsg(null)
    api.screen(spec)
      .then((b) => { setResult(b); setBt(null) })
      .catch((e) => setMsg({ kind: 'err', text: e.message }))
      .finally(() => setBusy(''))
  }

  // 清单页点卡片 → 进详情页并筛选
  const openPlan = (p) => {
    setDraft(null)
    setCurrent(p)
    setHist({ open: false, date: defaultHistDate(), data: null, busy: false, err: null })
    runScreen(p.spec)
  }

  const rerun = () => {
    const spec = draft?.spec || current?.spec
    if (spec) runScreen(spec)
  }

  const runBacktest = () => {
    const spec = draft?.spec || current?.spec
    if (!spec) return
    setBusy('bt')
    setMsg(null)
    api.backtest(spec)
      .then(setBt)
      .catch((e) => setMsg({ kind: 'err', text: e.message }))
      .finally(() => setBusy(''))
  }

  const startEdit = () => {
    if (!current || draft) return
    setDraft({ name: current.builtin ? '' : current.name, originName: current.builtin ? null : current.name, spec: deepcopy(current.spec) })
  }

  const newPlan = () => {
    // 新建 = 直接进一张空白草稿的详情页，编辑器默认展开
    const spec = { logic: 'all', conditions: [emptyCondition()], rank: null }
    setDraft({ name: '', originName: null, spec: deepcopy(spec) })
    setCurrent({ id: 'draft', name: '新建条件组合', builtin: false, spec })
    setResult(null)
    setBt(null)
    setMsg(null)
  }

  const patchDraft = (patch) => setDraft((d) => ({ ...d, spec: { ...d.spec, ...patch } }))

  const doSave = async () => {
    const name = (draft.name || '').trim()
    if (!name) { setMsg({ kind: 'err', text: '先填条件组合名称再保存' }); return }
    try {
      await api.saveRule(name, draft.spec)
      const saved = { id: `rule:${name}`, name, builtin: false, spec: draft.spec }
      setCurrent(saved)
      setDraft(null)
      refreshPlans()
      setMsg({ kind: 'ok', text: `已保存条件组合「${name}」（新版本）` })
    } catch (e) {
      setMsg({ kind: 'err', text: e.message })
    }
  }

  const doDelete = async () => {
    if (!draft?.originName) return
    try {
      await api.deleteRule(draft.originName)
      setDraft(null)
      setCurrent(null)
      setResult(null)
      setBt(null)
      refreshPlans()
      setMsg({ kind: 'ok', text: `已删除条件组合「${draft.originName}」` })
    } catch (e) {
      setMsg({ kind: 'err', text: e.message })
    }
  }

  const addWatch = async (r) => {
    try {
      await api.addStock(r.code, r.name, `条件选股·${current?.name || '自定义'}`)
      setAdded((m) => ({ ...m, [r.code]: true }))
    } catch (e) {
      setMsg({ kind: 'err', text: `${r.code}: ${e.message}` })
    }
  }

  const backToList = () => {
    setCurrent(null)
    setDraft(null)
    setResult(null)
    setBt(null)
    setMsg(null)
    setHist({ open: false, date: defaultHistDate(), data: null, busy: false, err: null })
  }

  if (!metrics.length && !plans.length) {
    return <div className="hint" style={{ marginTop: 24 }}>加载条件组合清单…</div>
  }

  // ============ 详情页：某个条件组合 ============
  if (current) {
    const guard = result?.market_guard
    const rank = rankText(draft?.spec.rank ?? current.spec.rank, metrics)
    const logicTxt = (draft?.spec ?? current.spec).logic === 'any' ? '任一满足（OR）' : '全部满足（AND）'

    return (
      <div>
        <div className="detail-bar">
          <button className="nav" onClick={backToList}>← 返回清单</button>
          <h3 style={{ margin: 0 }}>
            {current.name}
            {current.builtin ? <span className="chip" style={{ marginLeft: 8 }}>内置</span>
              : current.version ? <span className="chip" style={{ marginLeft: 8 }}>v{current.version}</span> : null}
          </h3>
          <span className="flex-sp" />
          <button className="nav" onClick={rerun} disabled={!!busy}>
            {busy === 'screen' ? '筛选中…（首次约2-5分钟）' : '↻ 重新筛选'}
          </button>
          <button className="nav" onClick={runBacktest} disabled={!!busy}>
            {busy === 'bt' ? '回测中…' : '📊 回测验证'}
          </button>
          <button className={hist.open ? 'nav active' : 'nav'}
                  onClick={() => setHist((h) => ({ ...h, open: !h.open }))}>
            📅 历史验证
          </button>
          {!draft && <button className="primary" onClick={startEdit}>✏️ 编辑条件</button>}
        </div>
        <p className="plan-conds" style={{ margin: '4px 0 8px' }}>
          {logicTxt}{rank ? ` · ${rank}` : ''} ·{' '}
          {current.spec.conditions.map((c, i) => {
            const t = condText(c, metrics)
            return (
              <span key={i}>
                {i > 0 && <span className="sep"> · </span>}
                <span className={t.exclude ? 'excl' : ''}>{t.exclude ? '排除：' : ''}{t.text}</span>
              </span>
            )
          })}
        </p>
        {current.desc && <p className="hint" style={{ margin: '0 0 10px' }}>📌 {current.desc}</p>}

        {/* 编辑器 */}
        {draft && (
          <div className="panel editor-panel">
            <div className="cond-head">
              <span className="hint">组合方式：</span>
              <button className={draft.spec.logic === 'all' ? 'nav active' : 'nav'}
                      onClick={() => patchDraft({ logic: 'all' })}>全部满足（AND）</button>
              <button className={draft.spec.logic === 'any' ? 'nav active' : 'nav'}
                      onClick={() => patchDraft({ logic: 'any' })}>任一满足（OR）</button>
              <span className="flex-sp" />
              <button className="link" onClick={() => setDraft(null)}>收起编辑器</button>
            </div>

            {draft.spec.conditions.map((c, i) => (
              <ConditionRow key={i} cond={c} metrics={metrics}
                            onChange={(nc) => patchDraft({ conditions: draft.spec.conditions.map((x, j) => (j === i ? nc : x)) })}
                            onRemove={() => patchDraft({ conditions: draft.spec.conditions.filter((_, j) => j !== i) })} />
            ))}
            <button className="link" onClick={() => patchDraft({ conditions: [...draft.spec.conditions, emptyCondition()] })}>
              ＋添加条件
            </button>

            <div className="cond-rank">
              {draft.spec.rank ? (
                <>
                  <span className="hint">排名取前</span>
                  <input className="cond-num" type="number" min="1" max="100" value={draft.spec.rank.top_pct}
                         onChange={(e) => patchDraft({ rank: { ...draft.spec.rank, top_pct: Number(e.target.value) } })} />
                  <span className="hint">% 按</span>
                  <select className="cond-op" value={draft.spec.rank.metric}
                          onChange={(e) => patchDraft({ rank: { ...draft.spec.rank, metric: e.target.value } })}>
                    {groupedMetrics(metrics).map(([cat, list]) => (
                      <optgroup key={cat} label={cat}>
                        {list.map((x) => <option key={x.key} value={x.key}>{x.name}</option>)}
                      </optgroup>
                    ))}
                  </select>
                  <select className="cond-op" value={draft.spec.rank.order}
                          onChange={(e) => patchDraft({ rank: { ...draft.spec.rank, order: e.target.value } })}>
                    <option value="desc">降序</option>
                    <option value="asc">升序</option>
                  </select>
                  <button className="link" onClick={() => patchDraft({ rank: null })}>✕ 去掉排名</button>
                </>
              ) : (
                <button className="link" onClick={() => patchDraft({ rank: { metric: 'div_yield', top_pct: 20, order: 'desc' } })}>
                  ＋排名条件（取前 N%）
                </button>
              )}
            </div>

            <div className="cond-actions">
              <button className="primary" onClick={rerun} disabled={!!busy}>
                {busy === 'screen' ? '筛选中…（首次约2-5分钟）' : '▶ 试运行'}
              </button>
              <input className="save-name" placeholder="组合名称（保存用）" value={draft.name}
                     onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
              <button className="nav" onClick={doSave}>💾 保存</button>
              {draft.originName && <button className="nav" onClick={doDelete}>🗑 删除「{draft.originName}」</button>}
              <span className="hint">内置模板另存为我的组合；同名保存版本号 +1</span>
            </div>
          </div>
        )}

        {msg && <div className={`msg msg-${msg.kind}`}>{msg.text}</div>}
        {guard && (
          <div className={`msg ${guard.above_ma20 === true ? 'msg-ok' : guard.above_ma20 === false ? 'msg-err' : 'msg-info'}`}>
            🛡 大盘防守开关：{guard.text}
          </div>
        )}

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
              <div className="msg msg-info">无标的通过条件——点「编辑条件」放宽阈值再试。</div>
            )}
          </>
        )}
        {!result && !busy && !draft && (
          <div className="msg msg-info">点「↻ 重新筛选」跑一遍这个组合。</div>
        )}

        <BacktestCard bt={bt} />

        {hist.open && (
          <HistPanel spec={draft?.spec || current.spec} hist={hist} setHist={setHist} />
        )}

        {result && result.manual_review?.length > 0 && result.count > 0 && (
          <div className="panel" style={{ marginTop: 16 }}>
            <h3>人工清洗清单（买入前必查）</h3>
            <ul className="review-list">
              {result.manual_review.map((t) => <li key={t}>{t}</li>)}
            </ul>
          </div>
        )}
        {!result && (
          <p className="hint">指标口径悬停可见；缺失数据一律「不命中并标注」；财务/估值条件无法历史重放（防未来数据泄漏），回测仅支持纯K线组合。</p>
        )}
      </div>
    )
  }

  // ============ 清单页：条件组合一整屏 ============
  return (
    <div>
      <div className="plan-col-head">
        <h3 style={{ margin: 0 }}>条件组合</h3>
        <button className="primary" onClick={newPlan}>＋新建条件组合</button>
      </div>
      <div className="plan-list">
        {plans.map((p) => {
          const rank = rankText(p.spec.rank, metrics)
          const logicTxt = p.spec.logic === 'any' ? '任一满足（OR）' : '全部满足（AND）'
          return (
            <div key={p.id} className="plan-card" onClick={() => openPlan(p)}>
              <div className="plan-head">
                <b>{p.name}</b>
                <span className="hint">{logicTxt}{rank ? ` · ${rank}` : ''} · {p.builtin ? '内置' : `v${p.version}`}</span>
              </div>
              <div className="plan-conds">
                {p.spec.conditions.map((c, i) => {
                  const t = condText(c, metrics)
                  return (
                    <span key={i}>
                      {i > 0 && <span className="sep"> · </span>}
                      <span className={t.exclude ? 'excl' : ''}>{t.exclude ? '排除：' : ''}{t.text}</span>
                    </span>
                  )
                })}
              </div>
            </div>
          )
        })}
      </div>
      {msg && <div className={`msg msg-${msg.kind}`}>{msg.text}</div>}
      <p className="hint">点任意组合进入查看它选出的股票；进入后可「编辑条件」「回测验证」。缺失数据一律「不命中并标注」。</p>
    </div>
  )
}
