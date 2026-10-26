import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const backend = 'http://localhost:8000'

// Dev: Vite on :5173 proxies API, admin and WebSockets to Django on :8000 (same origin, so
// session cookies and CSRF work unchanged). Build: assets live under /static/ so Django
// (WhiteNoise) serves the SPA and the API as one deployable service.
export default defineConfig(({ command }) => ({
  base: command === 'build' ? '/static/' : '/',
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': backend,
      '/admin': backend,
      '/ws': { target: backend, ws: true },
    },
  },
}))
