import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const appVersion = readFileSync(fileURLToPath(new URL('../VERSION', import.meta.url)), 'utf-8').trim()

export default defineConfig({
  plugins: [react()],
  define: {
    __APP_VERSION__: JSON.stringify(appVersion)
  },
  server: {
    proxy: {
      '/api': process.env.LWS_API_TARGET || 'http://127.0.0.1:8000'
    }
  }
})
