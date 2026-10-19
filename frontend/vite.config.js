import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// dev 端口 5610；/api 代理到本地 FastAPI(8610)
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5610,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8610',
        changeOrigin: true,
      },
    },
  },
})
