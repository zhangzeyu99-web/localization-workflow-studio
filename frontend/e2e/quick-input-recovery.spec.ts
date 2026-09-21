import { expect, test, type Page } from '@playwright/test'

const baseURL = process.env.E2E_BASE_URL ?? `http://127.0.0.1:${process.env.LWS_E2E_FRONTEND_PORT ?? '15173'}`

async function mountQuickInput(page: Page) {
  // All API traffic stays in the browser mock; this suite never creates real projects.
  await page.route('**/api/**', (route) => route.fulfill({
    status: 503,
    contentType: 'application/json',
    body: JSON.stringify({ detail: 'Unexpected API request in isolated quick input test' }),
  }))
  await page.route('**/translation-readiness?*', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ source_rows: 1, translated_rows: 0, empty_target_rows: 1, estimated_batches: 1 }),
  }))
  await page.goto(baseURL)
  await page.evaluate(async () => {
    const React = await import('/@id/react')
    const ReactDOMClient = await import('/@id/react-dom/client')
    const { QuickTaskWizard } = await import('/src/components/quickTask/QuickTaskWizard.tsx')
    const createElement = React.createElement || React.default.createElement
    const createRoot = ReactDOMClient.createRoot || ReactDOMClient.default.createRoot
    const host = document.createElement('div')
    document.body.replaceChildren(host)
    const root = createRoot(host)
    let generation = 1
    const renderTask = () => {
      const scope = { projectId: 'quick-input-project', taskId: `quick-input-task-${generation}`, generation }
      root.render(createElement(QuickTaskWizard, {
        key: scope.generation,
        project: { id: scope.projectId, name: '输入恢复测试', artifacts: [], runs: [] },
        busy: false,
        status: '准备就绪',
        jobQueues: null,
        settings: null,
        scope,
        initialRun: null,
        isCurrentScope: (candidate: typeof scope) => candidate.generation === generation,
        onUploadFile: async (file: File, kind: string, accept: () => boolean) => {
          const body = new FormData()
          body.append('file', file)
          const response = await fetch(`/api/projects/${scope.projectId}/files?kind=${kind}`, { method: 'POST', body })
          const artifact = await response.json()
          return accept() ? artifact : null
        },
        onStartQuickTask: async () => null,
        onRefreshProject: async () => null,
        onContinueTask: () => undefined,
        onViewResult: () => undefined,
        onBack: () => { generation += 1; renderTask() },
        onStartNextTask: () => { generation += 1; renderTask() },
      }))
    }
    renderTask()
  })
  await expect(page.getByTestId('quick-task-id')).toHaveAttribute('data-task-id', 'quick-input-task-1')
}

function artifact(id: string) {
  return { id, project_id: 'quick-input-project', label: `${id}.txt`, kind: 'quick_input', path: `${id}.txt`, size: 10, created_at: '2026-09-20T00:00:00Z' }
}

function targets(language: string) {
  return { detected_languages: [language], suggested_language: language }
}

test('failed language detection retries the accepted input without uploading again', async ({ page }) => {
  await mountQuickInput(page)
  let uploads = 0
  let inspections = 0
  await page.route('**/files?kind=quick_input', async (route) => {
    uploads += 1
    await route.fulfill({ json: artifact('accepted-input') })
  })
  await page.route('**/accepted-input/translation-targets', async (route) => {
    inspections += 1
    await route.fulfill(inspections === 1
      ? { status: 500, json: { detail: 'Temporary detection failure' } }
      : { json: targets('ja') })
  })

  await page.getByTestId('quick-text-input').fill('开始游戏')
  await page.getByTestId('quick-text-next').click()
  await expect(page.getByTestId('quick-input-retry')).toBeVisible()
  await expect(page.getByRole('button', { name: /^2\s*投入参考$/ })).toBeDisabled()
  await page.getByTestId('quick-input-retry').click()
  await expect(page.getByTestId('quick-reference-next')).toBeVisible()
  await page.getByTestId('quick-reference-next').click()
  await expect(page.locator('.quick-launch-grid select')).toHaveValue('ja')
  await expect(page.locator('.quick-launch-grid')).toContainText('accepted-input')
  expect(uploads).toBe(1)
  expect(inspections).toBe(2)
})

for (const delayedStage of ['upload', 'detection'] as const) {
  test(`a late ${delayedStage} response for input A cannot replace input B`, async ({ page }) => {
    await mountQuickInput(page)
    let delayedRequestReceived = false
    let releaseA: () => void = () => undefined
    const gate = new Promise<void>((resolve) => { releaseA = resolve })
    await page.route('**/files?kind=quick_input', async (route) => {
      const id = route.request().postData()?.includes('input-A.txt') ? 'input-A' : 'input-B'
      if (id === 'input-A' && delayedStage === 'upload') {
        delayedRequestReceived = true
        await gate
      }
      await route.fulfill({ json: artifact(id) })
    })
    await page.route('**/translation-targets', async (route) => {
      const isA = route.request().url().includes('/input-A/')
      if (isA && delayedStage === 'detection') {
        delayedRequestReceived = true
        await gate
      }
      await route.fulfill({ json: targets(isA ? 'en' : 'ja') })
    })

    await page.getByTestId('quick-mode-upload').click()
    const upload = page.getByTestId('quick-input-upload').locator('input[type=file]')
    await upload.setInputFiles({ name: 'input-A.txt', mimeType: 'text/plain', buffer: Buffer.from('第一份输入') })
    await expect.poll(() => delayedRequestReceived).toBe(true)
    await upload.setInputFiles({ name: 'input-B.txt', mimeType: 'text/plain', buffer: Buffer.from('第二份输入') })
    await page.getByTestId('quick-reference-next').click()
    await expect(page.locator('.quick-launch-grid select')).toHaveValue('ja')

    const delayedResponse = page.waitForResponse((response) => delayedStage === 'upload'
      ? response.url().includes('/files?') && Boolean(response.request().postData()?.includes('input-A.txt'))
      : response.url().endsWith('/input-A/translation-targets'))
    releaseA()
    await (await delayedResponse).finished()
    await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
    await expect(page.getByTestId('quick-task-start')).toBeVisible()
    await expect(page.locator('.quick-launch-grid select')).toHaveValue('ja')
    await expect(page.locator('.quick-launch-grid')).toContainText('input-B')
    await expect(page.locator('.quick-launch-grid')).not.toContainText('input-A')
  })
}

test('a late failed retry from the previous task cannot change the replacement task', async ({ page }) => {
  await mountQuickInput(page)
  let uploads = 0
  let firstInputInspections = 0
  let retryReceived = false
  let releaseRetry: () => void = () => undefined
  const retryGate = new Promise<void>((resolve) => { releaseRetry = resolve })
  await page.route('**/files?kind=quick_input', async (route) => {
    uploads += 1
    await route.fulfill({ json: artifact(uploads === 1 ? 'input-A' : 'input-B') })
  })
  await page.route('**/translation-targets', async (route) => {
    if (route.request().url().includes('/input-A/')) {
      firstInputInspections += 1
      if (firstInputInspections > 1) {
        retryReceived = true
        await retryGate
      }
      await route.fulfill({ status: 500, json: { detail: 'Previous input detection failed' } })
      return
    }
    await route.fulfill({ json: targets('ja') })
  })

  await page.getByTestId('quick-text-input').fill('第一项任务')
  await page.getByTestId('quick-text-next').click()
  await page.getByTestId('quick-input-retry').click()
  await expect.poll(() => retryReceived).toBe(true)
  await page.getByRole('button', { name: '返回项目概览', exact: true }).click()
  await expect(page.getByTestId('quick-task-id')).toHaveAttribute('data-task-id', 'quick-input-task-2')
  await page.getByTestId('quick-text-input').fill('第二项任务')
  await page.getByTestId('quick-text-next').click()
  await page.getByTestId('quick-reference-next').click()

  const lateResponse = page.waitForResponse((response) => response.url().endsWith('/input-A/translation-targets'))
  releaseRetry()
  await (await lateResponse).finished()
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
  await expect(page.getByTestId('quick-task-id')).toHaveAttribute('data-task-id', 'quick-input-task-2')
  await expect(page.getByTestId('quick-task-start')).toBeVisible()
  await expect(page.locator('.quick-launch-grid select')).toHaveValue('ja')
  await expect(page.locator('.quick-launch-grid')).toContainText('input-B')
  await expect(page.getByTestId('quick-input-retry')).toHaveCount(0)
  expect(uploads).toBe(2)
})
