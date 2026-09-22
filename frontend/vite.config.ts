import path from "path"
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// /api is proxied to FastAPI, so the browser makes same-origin calls and CORS
// never applies in dev. The timeout is generous because an agent turn that
// sizes findings makes two model calls and can take 20-30s.
//
// Ports 5180/8010 rather than Vite's 5173 and uvicorn's 8000, which the
// pharma-bench app on this machine already uses. strictPort makes a clash fail
// loudly: without it Vite silently moves to 5174 while the browser, or a
// health check, keeps talking to whichever app still holds 5173.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"),
    },
  },
  server: {
    port: 5180,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8010',
        changeOrigin: true,
        timeout: 180_000,
        proxyTimeout: 180_000,
      },
    },
  },
})
