import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const appVersion = readFileSync(fileURLToPath(new URL('../VERSION', import.meta.url)), 'utf-8').trim()

export default defineConfig({
  plugins: [react()],
  define: {
    __APP_VERSION__: JSON.stringify(appVersion),
    // 线上部署包构建时设 LWS_HIDE_SETTINGS=1，彻底隐藏设置入口（不依赖后端 deployment_mode）。
    __HIDE_SETTINGS__: JSON.stringify(process.env.LWS_HIDE_SETTINGS === '1')
  },
  server: {
    proxy: {
      '/api': process.env.LWS_API_TARGET || 'http://127.0.0.1:8000'
    }
  }
})
