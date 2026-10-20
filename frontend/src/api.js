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
  strategy: (key, refresh = false) =>
    req(`/api/strategy/${key}${refresh ? '?refresh=true' : ''}`),
  stockDetail: (symbol) => req(`/api/stocks/${symbol}`),
}
