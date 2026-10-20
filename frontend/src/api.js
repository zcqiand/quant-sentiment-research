// API 封装：统一走同源 /api（vite dev 代理到 8610）
async function req(path, options = {}) {
  const resp = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (resp.status === 204) return null
  const body = await resp.json().catch(() => ({}))
  if (!resp.ok) {
    throw new Error(body.detail || `${resp.status} ${resp.statusText}`)
  }
  return body
}

export const api = {
  health: () => req('/api/health'),
  watchlist: () => req('/api/watchlist'),
  addStock: (symbol, name = '', note = '') =>
    req('/api/watchlist', { method: 'POST', body: JSON.stringify({ symbol, name, note }) }),
  removeStock: (symbol) => req(`/api/watchlist/${symbol}`, { method: 'DELETE' }),
  metrics: () => req('/api/metrics'),
  presets: () => req('/api/presets'),
  screen: (rule) => req('/api/screen', { method: 'POST', body: JSON.stringify(rule) }),
  backtest: (rule) => req('/api/backtest', { method: 'POST', body: JSON.stringify(rule) }),
  histScreen: (rule, asof, kline_limit = 300) =>
    req('/api/hist_screen', { method: 'POST', body: JSON.stringify({ rule, asof, kline_limit }) }),
  rules: () => req('/api/rules'),
  saveRule: (name, rule) =>
    req('/api/rules', { method: 'POST', body: JSON.stringify({ name, rule }) }),
  deleteRule: (name) => req(`/api/rules/${encodeURIComponent(name)}`, { method: 'DELETE' }),
  stockDetail: (symbol) => req(`/api/stocks/${symbol}`),
}
