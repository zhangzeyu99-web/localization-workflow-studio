import { expect, test, type Page } from '@playwright/test'

const baseURL = process.env.E2E_BASE_URL ?? `http://127.0.0.1:${process.env.LWS_E2E_FRONTEND_PORT ?? '15173'}`
const projectId = 'quick-running-project'
const taskId = 'quick-task-running-1'
const input = { id: 'running-input', project_id: projectId, label: '当前输入.txt', kind: 'quick_input', path: 'current.txt', size: 10, created_at: '2026-09-21T00:00:00Z' }

function run(status: string) {
  return {
    id: 'quick-running-run', project_id: projectId, kind: 'translation', language: 'en', status,
    created_at: '2026-09-21T00:00:00Z', updated_at: '2026-09-21T00:00:00Z', artifacts: [],
    metadata: { task_origin: 'quick_task', translation_task_id: taskId, input_artifact_id: input.id },
  }
}

async function mountQuickTask(page: Page, initialStatus: string | null = null) {
  // Render the real component; every API response in this suite is an isolated fixture.
  await page.route('**/api/**', (route) => route.fulfill({ status: 503, json: { detail: 'Unexpected fixture request' } }))
  await page.route('**/translation-readiness?*', (route) => route.fulfill({ json: { source_rows: 1, translated_rows: 0, empty_target_rows: 1, estimated_batches: 1 } }))
  await page.route('**/translation-targets', (route) => route.fulfill({ json: { detected_languages: ['en'], suggested_language: 'en' } }))
  await page.route(`**/api/runs/quick-running-run`, (route) => route.fulfill({ json: run(initialStatus || 'running') }))
  await page.goto(baseURL)
  await page.evaluate(async ({ input, initialRun, projectId, taskId }) => {
    const React = await import('/@id/react')
    const ReactDOMClient = await import('/@id/react-dom/client')
    const { QuickTaskWizard } = await import('/src/components/quickTask/QuickTaskWizard.tsx')
    const createElement = React.createElement || React.default.createElement
    const createRoot = ReactDOMClient.createRoot || ReactDOMClient.default.createRoot
    const host = document.createElement('main')
    host.style.padding = '24px'
    document.body.replaceChildren(host)
    const root = createRoot(host)
    let generation = 1
    const renderTask = (restoredRun = initialRun, restoredProject = projectId) => {
      const scope = { projectId: restoredProject, taskId: generation === 1 ? taskId : `quick-task-replacement-${generation}`, generation }
      root.render(createElement(QuickTaskWizard, {
        key: `${scope.projectId}:${scope.generation}`,
        project: { id: scope.projectId, name: '快速任务运行态验收', artifacts: [input], runs: [] },
        busy: false, status: '准备就绪', jobQueues: null, settings: null, scope, initialRun: restoredRun,
        isCurrentScope: (candidate: typeof scope) => candidate.generation === generation && candidate.projectId === scope.projectId,
        onUploadFile: async (_file: File, kind: string) => kind === 'quick_input' ? input : { ...input, id: 'reference', label: '参考.txt' },
        onStartQuickTask: async () => fetch('/api/fixture/start', { method: 'POST' }).then((response) => response.json()),
        onRefreshProject: async () => null,
        onContinueTask: () => undefined,
        onViewResult: (currentRun: { id: string }) => { host.dataset.viewedRun = currentRun.id },
        onBack: () => { generation += 1; renderTask(null, 'replacement-project') },
        onStartNextTask: () => { generation += 1; renderTask(null) },
      }))
    }
    renderTask()
  }, { input, initialRun: initialStatus ? run(initialStatus) : null, projectId, taskId })
  await expect(page.getByTestId('quick-task-id')).toHaveAttribute('data-task-id', taskId)
}

async function prepareInput(page: Page) {
  await page.getByTestId('quick-text-input').fill('开始游戏')
  await page.getByTestId('quick-text-next').click()
  await page.getByTestId('quick-reference-next').click()
}

test('a delayed start freezes the selected context while earlier steps stay readable', async ({ page }) => {
  await mountQuickTask(page)
  let requested = false
  let release: () => void = () => undefined
  const gate = new Promise<void>((resolve) => { release = resolve })
  await page.route('**/api/fixture/start', async (route) => {
    requested = true
    await gate
    await route.fulfill({ json: run('queued') })
  })
  await prepareInput(page)
  await page.getByTestId('quick-task-start').click()
  await expect.poll(() => requested).toBe(true)
  try {
    await expect(page.getByTestId('quick-objective-qa')).toBeDisabled()
    await expect(page.locator('.quick-launch-grid select')).toBeDisabled()
    await page.getByRole('button', { name: /^1\s*投入内容$/ }).click()
    await expect(page.getByTestId('quick-text-input')).toHaveAttribute('readonly', '')
    await expect(page.getByTestId('quick-text-input')).toHaveValue('开始游戏')
    await expect(page.getByTestId('quick-mode-upload')).toBeDisabled()
    await expect(page.getByTestId('quick-text-next')).toBeDisabled()
    await expect(page.getByTestId('quick-task-runtime')).toContainText('正在启动')
    await page.getByRole('button', { name: /^2\s*投入参考$/ }).click()
    await expect(page.getByTestId('quick-reference-upload').locator('input')).toBeDisabled()
  } finally {
    release()
  }
  await expect(page.getByTestId('quick-task-runtime')).toContainText('quick-running-run')
  await expect(page.getByTestId('quick-task-stop')).toBeVisible()
})

for (const status of ['queued', 'running']) {
  test(`${status} tasks retain stop and details on earlier steps after restoration`, async ({ page }, testInfo) => {
    await mountQuickTask(page, status)
    let stops = 0
    await page.route('**/api/runs/quick-running-run/translate/cancel', async (route) => {
      stops += 1
      await route.fulfill({ json: run('canceled') })
    })
    await expect(page.getByTestId('quick-objective-qa')).toBeDisabled()
    await page.getByRole('button', { name: /^2\s*投入参考$/ }).click()
    await expect(page.getByTestId('quick-reference-upload').locator('input')).toBeDisabled()
    await expect(page.getByTestId('quick-task-runtime')).toContainText('快速任务输入｜current')
    await page.getByRole('button', { name: /^1\s*投入内容$/ }).click()
    await expect(page.getByTestId('quick-input-upload').locator('input')).toBeDisabled()
    await expect(page.getByTestId('quick-text-input')).toHaveCount(0)
    await expect(page.getByTestId('quick-task-stop')).toBeVisible()
    await page.getByTestId('quick-task-detail').click()
    await expect(page.locator('main')).toHaveAttribute('data-viewed-run', 'quick-running-run')
    if (status === 'running') {
      for (const width of [1280, 1024]) {
        await page.setViewportSize({ width, height: 900 })
        await expect(page.getByTestId('quick-task-stop')).toBeInViewport()
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
        await page.screenshot({ path: testInfo.outputPath(`P04-step1-${width}.png`) })
        await page.getByRole('button', { name: /^2\s*投入参考$/ }).click()
        await expect(page.getByTestId('quick-reference-upload').locator('input')).toBeDisabled()
        await expect(page.getByTestId('quick-task-stop')).toBeInViewport()
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
        await page.screenshot({ path: testInfo.outputPath(`P04-step2-${width}.png`) })
        await page.getByRole('button', { name: /^1\s*投入内容$/ }).click()
      }
    }
    await page.getByTestId('quick-task-stop').click()
    await expect.poll(() => stops).toBe(1)
    await expect(page.getByTestId('quick-task-runtime')).toContainText('已取消')
    await expect(page.getByTestId('quick-task-stop')).toHaveCount(0)
    await expect(page.getByTestId('quick-mode-upload')).toBeEnabled()
    await page.getByRole('button', { name: /^3\s*目标并启动$/ }).click()
    await expect(page.getByTestId('quick-task-start')).toBeDisabled()
  })
}

test('delivery download readback keeps earlier steps locked until the result is verified', async ({ page }) => {
  await mountQuickTask(page, 'running')
  let readbackRequested = false
  let release: () => void = () => undefined
  const gate = new Promise<void>((resolve) => { release = resolve })
  await page.route('**/delivery-package?*', (route) => route.fulfill({ json: {
    files: [{ kind: 'final', filename: 'delivery.txt', download_url: '/api/fixture/delivery.txt' }],
    deliverable: { run_id: 'quick-running-run', translation_task_id: taskId },
  } }))
  await page.route('**/api/fixture/delivery.txt', async (route) => {
    readbackRequested = true
    await gate
    await route.fulfill({ status: 200, contentType: 'text/plain', body: 'Start game' })
  })
  await page.route('**/api/runs/quick-running-run', (route) => route.fulfill({ json: run('passed') }))
  await expect.poll(() => readbackRequested).toBe(true)
  try {
    await expect(page.getByTestId('quick-delivery-result')).toHaveCount(0)
    await expect(page.getByTestId('quick-task-runtime')).toContainText('正在生成并读回交付')
    await expect(page.getByTestId('quick-task-stop')).toHaveCount(0)
    await page.getByRole('button', { name: /^2\s*投入参考$/ }).click()
    await expect(page.getByTestId('quick-reference-upload').locator('input')).toBeDisabled()
    await page.getByRole('button', { name: /^1\s*投入内容$/ }).click()
    await expect(page.getByTestId('quick-input-upload').locator('input')).toBeDisabled()
    await expect(page.getByTestId('quick-task-detail')).toBeVisible()
  } finally {
    release()
  }
  await page.getByRole('button', { name: '返回任务结果', exact: true }).click()
  await expect(page.getByTestId('quick-delivery-result')).toContainText('Start game')
  await expect(page.getByTestId('quick-task-start')).toBeDisabled()
  await page.getByTestId('quick-start-next-task').click()
  await expect(page.getByTestId('quick-text-input')).toHaveValue('')
  await expect(page.getByTestId('quick-text-input')).not.toHaveAttribute('readonly', '')
  await expect(page.getByTestId('quick-task-runtime')).toHaveCount(0)
})

test('a late start response cannot lock or replace the next project task', async ({ page }) => {
  await mountQuickTask(page)
  let requested = false
  let release: () => void = () => undefined
  const gate = new Promise<void>((resolve) => { release = resolve })
  await page.route('**/api/fixture/start', async (route) => {
    requested = true
    await gate
    await route.fulfill({ json: run('running') })
  })
  await prepareInput(page)
  await page.getByTestId('quick-task-start').click()
  await expect.poll(() => requested).toBe(true)
  await page.getByRole('button', { name: '返回项目概览', exact: true }).click()
  await expect(page.getByTestId('quick-task-id')).toHaveAttribute('data-task-id', 'quick-task-replacement-2')
  await page.getByTestId('quick-text-input').fill('新项目任务')
  const lateResponse = page.waitForResponse('**/api/fixture/start')
  release()
  await (await lateResponse).finished()
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
  await expect(page.getByTestId('quick-text-input')).toHaveValue('新项目任务')
  await expect(page.getByTestId('quick-text-input')).not.toHaveAttribute('readonly', '')
  await expect(page.getByTestId('quick-task-runtime')).toHaveCount(0)
  await expect(page.getByTestId('quick-text-next')).toBeEnabled()
})

test('the app restores running context after refresh and does not lock a different project', async ({ page, request }, testInfo) => {
  // Only projects are real TEMP records; the long-running Run is an API fixture.
  const activeName = `E2E Quick Running Restore ${Date.now()}`
  const otherName = `${activeName} Other`
  const activeProject = await request.post(`${baseURL}/api/projects`, { data: { name: activeName, type: 'quick-task' } }).then((response) => response.json())
  await request.post(`${baseURL}/api/projects`, { data: { name: otherName, type: 'quick-task' } })
  const activeInput = { ...input, project_id: activeProject.id }
  const activeRun = { ...run('running'), project_id: activeProject.id }
  await page.route(`**/api/projects/${activeProject.id}?**`, (route) => route.fulfill({ json: {
    ...activeProject, artifacts: [activeInput], runs: [activeRun], announcement_tasks: [],
  } }))
  await page.route('**/api/runs/quick-running-run', (route) => route.fulfill({ json: activeRun }))
  await page.route('**/translation-readiness?*', (route) => route.fulfill({ json: { source_rows: 1, translated_rows: 0, empty_target_rows: 1 } }))
  await page.goto(baseURL)
  await page.locator('.project-item').getByText(activeName, { exact: true }).click()
  await page.getByTestId('quick-task-entry').click()
  await expect(page.getByTestId('quick-task-id')).toHaveAttribute('data-task-id', taskId)
  await expect(page.getByTestId('quick-task-stop')).toBeVisible()
  await page.reload()
  await expect(page.getByTestId('quick-task-id')).toHaveAttribute('data-task-id', taskId)
  await page.getByRole('button', { name: /^1\s*投入内容$/ }).click()
  await expect(page.getByTestId('quick-input-upload').locator('input')).toBeDisabled()
  await expect(page.getByTestId('quick-task-runtime')).toContainText('quick-running-run')
  for (const width of [1280, 1024]) {
    await page.setViewportSize({ width, height: 900 })
    await expect(page.getByTestId('quick-task-stop')).toBeInViewport()
    await expect(page.locator('.project-item').getByText(activeName, { exact: true })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath(`P04-app-step1-${width}.png`) })
  }
  await page.locator('.project-item').getByText(otherName, { exact: true }).click()
  await page.getByTestId('quick-task-entry').click()
  await expect(page.getByTestId('quick-task-id')).not.toHaveAttribute('data-task-id', taskId)
  await expect(page.getByTestId('quick-task-runtime')).toHaveCount(0)
  await page.getByTestId('quick-text-input').fill('另一个项目的输入')
  await expect(page.getByTestId('quick-text-next')).toBeEnabled()
  await page.locator('.project-item').getByText(activeName, { exact: true }).click()
  await page.getByTestId('quick-task-entry').click()
  await expect(page.getByTestId('quick-task-id')).toHaveAttribute('data-task-id', taskId)
  await expect(page.getByTestId('quick-task-stop')).toBeVisible()
  await expect(page.locator('.quick-launch-grid select')).toBeDisabled()
})
