import { defineConfig } from '@playwright/test'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(__dirname, '..')
const dataRoot = process.env.LWS_AUTH_E2E_DATA_ROOT || path.join(os.tmpdir(), `lws-auth-playwright-data-${process.pid}`)
const backendPort = process.env.LWS_AUTH_E2E_BACKEND_PORT || '18081'
const frontendPort = process.env.LWS_AUTH_E2E_FRONTEND_PORT || '15174'
const backendURL = `http://127.0.0.1:${backendPort}`
const frontendURL = process.env.AUTH_E2E_BASE_URL || `http://127.0.0.1:${frontendPort}`
const adminPassword = process.env.LWS_AUTH_E2E_ADMIN_PASSWORD || 'Admin-Initial-Password!'

export default defineConfig({
  testDir: './e2e',
  testMatch: 'auth-flow.spec.ts',
  timeout: 120_000,
  workers: 1,
  expect: { timeout: 20_000 },
  use: {
    baseURL: frontendURL,
    trace: 'retain-on-failure',
  },
  webServer: process.env.AUTH_E2E_BASE_URL
    ? undefined
    : [
        {
          command: `.\\.venv\\Scripts\\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port ${backendPort} --app-dir backend`,
          cwd: repoRoot,
          url: `${backendURL}/api/health`,
          reuseExistingServer: false,
          timeout: 120_000,
          env: {
            ...process.env,
            LWS_DATA_ROOT: dataRoot,
            PYTHONPATH: path.join(repoRoot, 'backend'),
            LWS_AUTH_MODE: 'required',
            LWS_ADMIN_USER: 'e2e-admin',
            LWS_ADMIN_PASSWORD: adminPassword,
            LWS_ENABLE_TEST_PROVIDER: '1',
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
            LWS_API_TARGET: backendURL,
          },
        },
      ],
})
