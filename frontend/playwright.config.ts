import { defineConfig } from '@playwright/test'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(__dirname, '..')
const dataRoot = process.env.LWS_E2E_DATA_ROOT || path.join(os.tmpdir(), `lws-playwright-data-${process.pid}`)
const backendPort = process.env.LWS_E2E_BACKEND_PORT || '18080'
const frontendPort = process.env.LWS_E2E_FRONTEND_PORT || '15173'
const backendURL = `http://127.0.0.1:${backendPort}`
const frontendURL = process.env.E2E_BASE_URL || `http://127.0.0.1:${frontendPort}`
const managedWebServers = process.env.E2E_BASE_URL
  ? undefined
  : [
      {
        command: `python -m uvicorn app.main:app --host 127.0.0.1 --port ${backendPort} --app-dir backend`,
        cwd: repoRoot,
        url: `${backendURL}/api/health`,
        reuseExistingServer: false,
        timeout: 120_000,
        env: {
          ...process.env,
          LWS_DATA_ROOT: dataRoot,
          PYTHONPATH: path.join(repoRoot, 'backend'),
        },
      },
      {
        command: `npm run dev -- --host 127.0.0.1 --port ${frontendPort}`,
        cwd: __dirname,
        url: frontendURL,
        reuseExistingServer: false,
        timeout: 120_000,
        env: {
          ...process.env,
          E2E_BASE_URL: frontendURL,
          LWS_API_TARGET: backendURL,
        },
      },
    ]

export default defineConfig({
  testDir: './e2e',
  timeout: 120_000,
  expect: { timeout: 20_000 },
  use: {
    baseURL: frontendURL,
    trace: 'retain-on-failure',
  },
  webServer: managedWebServers,
})
