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
  addStock: (symbol, name) =>
    req('/api/watchlist', { method: 'POST', body: JSON.stringify({ symbol, name }) }),
  removeStock: (symbol) => req(`/api/watchlist/${symbol}`, { method: 'DELETE' }),
  scan: () => req('/api/scan', { method: 'POST' }),
  latestScan: () => req('/api/scan/latest'),
  stockDetail: (symbol) => req(`/api/stocks/${symbol}`),
  research: (symbol) => req(`/api/stocks/${symbol}/research`, { method: 'POST' }),
  backtest: (symbol) => req(`/api/backtest/${symbol}`),
  screener: (kind, refresh = false) =>
    req(`/api/screener/${kind}${refresh ? '?refresh=true' : ''}`),
}
