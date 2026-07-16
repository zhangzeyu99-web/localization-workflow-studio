import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import path from 'node:path'

const baseURL = process.env.E2E_BASE_URL ?? `http://127.0.0.1:${process.env.LWS_E2E_FRONTEND_PORT ?? '15173'}`

async function createQuickProject(page: Page, request: APIRequestContext, suffix: string) {
  await request.patch(`${baseURL}/api/settings`, {
    data: { provider: 'test-fake', model: 'test-fake-localization', batch_size: 1 },
  })
  const name = `E2E Quick Lifecycle ${suffix} ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name, type: 'quick-task', description: 'Quick lifecycle route-mock coverage.' },
  }).then((response) => response.json())
  await page.goto(baseURL)
  await page.getByRole('button', { name }).click()
  await page.getByTestId('quick-task-entry').click()
  await expect(page.getByRole('heading', { name: '快速任务', exact: true })).toBeVisible()
  return project
}

async function preparePastedQuickTask(page: Page, text = '开始游戏') {
  await page.getByTestId('quick-text-input').fill(text)
  await page.getByTestId('quick-text-next').click()
  await expect(page.getByTestId('quick-reference-next')).toBeVisible()
  await page.getByTestId('quick-reference-next').click()
  await expect(page.getByTestId('quick-task-start')).toBeVisible()
}

test('quick lifecycle groups identified runs, ignores legacy for recovery, and prefers running tasks', async ({ page }) => {
  await page.goto(baseURL)
  const result = await page.evaluate(async () => {
    const { groupQuickTasks, selectQuickTaskLifecycle } = await import('/src/domain/quickTaskLifecycle.ts')
    const run = (id: string, status: string, taskId?: string, state?: string, updated = id) => ({
      id,
      project_id: 'project-1',
      kind: 'translation',
      language: 'en',
      status,
      created_at: updated,
      updated_at: updated,
      metadata: {
        task_origin: 'quick_task',
        ...(taskId ? { translation_task_id: taskId } : {}),
        ...(state ? { translation_task_state: state, translation_task_state_updated_at: updated } : {}),
      },
    })
    const runs = [
      run('legacy', 'running'),
      run('stopped-newer', 'failed', 'quick-task-stopped', undefined, '2026-07-15T10:00:00Z'),
      run('queued', 'queued', 'quick-task-queued', undefined, '2026-07-15T09:00:00Z'),
      run('running', 'running', 'quick-task-running', undefined, '2026-07-15T08:00:00Z'),
      run('delivered', 'passed', 'quick-task-delivered', 'delivered', '2026-07-15T11:00:00Z'),
    ] as any
    const groups = groupQuickTasks(runs)
    const lifecycle = selectQuickTaskLifecycle(runs)
    const terminalAndLegacyOnly = selectQuickTaskLifecycle([
      run('legacy-only', 'running'),
      run('delivered-only', 'passed', 'quick-task-delivered-only', 'delivered'),
    ] as any)
    return {
      groupIds: groups.map((group: any) => group.taskId),
      legacy: groups.filter((group: any) => group.legacy).length,
      activeTaskId: lifecycle.activeTask?.taskId,
      stoppedTaskIds: lifecycle.stoppedTasks.map((group: any) => group.taskId),
      terminalAndLegacyActive: terminalAndLegacyOnly.activeTask?.taskId || '',
      terminalAndLegacyStopped: terminalAndLegacyOnly.stoppedTasks.length,
    }
  })

  expect(result.groupIds).toContain('quick-task-delivered')
  expect(result.legacy).toBe(1)
  expect(result.activeTaskId).toBe('quick-task-running')
  expect(result.stoppedTaskIds).toEqual(['quick-task-stopped'])
  expect(result.terminalAndLegacyActive).toBe('')
  expect(result.terminalAndLegacyStopped).toBe(0)
})

test('TXT T1 auto-delivers with browser readback and starts a clean T2 with a distinct task id', async ({ page, request }) => {
  const createBodies: any[] = []
  let runSequence = 0
  let projectId = ''

  await page.route('**/api/runs', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    const body = route.request().postDataJSON()
    createBodies.push(body)
    runSequence += 1
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: `quick-run-${runSequence}`,
        project_id: body.project_id,
        kind: body.kind,
        language: body.language,
        status: 'created',
        created_at: `2026-07-15T10:0${runSequence}:00Z`,
        updated_at: `2026-07-15T10:0${runSequence}:00Z`,
        metadata: {
          task_origin: body.task_origin,
          translation_task_id: body.translation_task_id,
          input_artifact_id: body.input_artifact_id,
        },
        artifacts: [],
      }),
    })
  })
  await page.route('**/api/runs/quick-run-*/translate/start', async (route) => {
    const id = route.request().url().match(/quick-run-\d+/)?.[0] || 'quick-run-1'
    const body = createBodies[Number(id.split('-').at(-1)) - 1]
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id,
        project_id: body.project_id,
        kind: 'translation',
        language: body.language,
        status: 'passed',
        created_at: '2026-07-15T10:00:00Z',
        updated_at: '2026-07-15T10:00:01Z',
        metadata: {
          task_origin: 'quick_task',
          translation_task_id: body.translation_task_id,
          input_artifact_id: body.input_artifact_id,
        },
        artifacts: [],
      }),
    })
  })
  await page.route('**/api/projects/*/delivery-package?run_id=*', async (route) => {
    const runId = new URL(route.request().url()).searchParams.get('run_id') || 'quick-run-1'
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        files: [{ kind: 'final', filename: `${runId}.txt`, path: `${runId}.txt`, download_url: `/api/projects/${projectId}/delivery/${runId}.txt` }],
        deliverable: { run_id: runId },
        archive: null,
      }),
    })
  })
  await page.route('**/api/projects/*/delivery/quick-run-*.txt', async (route) => {
    await route.fulfill({ status: 200, contentType: 'text/plain; charset=utf-8', body: 'TestFake Start Game' })
  })

  const project = await createQuickProject(page, request, 'T1-T2')
  projectId = project.id
  const firstTaskId = await page.getByTestId('quick-task-id').getAttribute('data-task-id')
  await preparePastedQuickTask(page)
  await page.getByTestId('quick-task-start').click()

  await expect(page.getByTestId('quick-delivery-result')).toContainText('TestFake Start Game')
  await expect(page.getByTestId('quick-start-next-task')).toBeVisible()
  expect(createBodies[0].task_origin).toBe('quick_task')
  expect(createBodies[0].translation_task_id).toBe(firstTaskId)

  for (const viewport of [{ width: 1024, height: 768 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport)
    const dimensions = await page.evaluate(() => ({
      pageWidth: document.documentElement.scrollWidth,
      viewportWidth: document.documentElement.clientWidth,
      contentOverflow: document.querySelector('.main-content')!.scrollWidth - document.querySelector('.main-content')!.clientWidth,
    }))
    expect(dimensions.pageWidth).toBeLessThanOrEqual(dimensions.viewportWidth + 1)
    expect(dimensions.contentOverflow).toBeLessThanOrEqual(1)
  }
  await page.setViewportSize({ width: 1280, height: 800 })

  await page.getByTestId('quick-start-next-task').click()
  await expect(page.getByTestId('quick-text-input')).toHaveValue('')
  const secondTaskId = await page.getByTestId('quick-task-id').getAttribute('data-task-id')
  expect(secondTaskId).not.toBe(firstTaskId)

  await preparePastedQuickTask(page)
  await page.getByTestId('quick-task-start').click()
  await expect(page.getByTestId('quick-delivery-result')).toBeVisible()
  expect(createBodies).toHaveLength(2)
  expect(createBodies[1].translation_task_id).toBe(secondTaskId)
})

for (const mismatch of ['run_id', 'translation_task_id'] as const) {
  test(`delivery response with mismatched ${mismatch} is rejected before browser readback`, async ({ page, request }) => {
    const currentRunId = `quick-run-delivery-${mismatch}`
    let projectId = ''
    let taskId = ''
    let downloadReads = 0

    await page.route('**/api/runs', async (route) => {
      if (route.request().method() !== 'POST') return route.continue()
      const body = route.request().postDataJSON()
      taskId = body.translation_task_id
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: currentRunId,
          project_id: body.project_id,
          kind: 'translation',
          language: body.language,
          status: 'created',
          created_at: '2026-07-15T10:00:00Z',
          updated_at: '2026-07-15T10:00:00Z',
          metadata: { task_origin: 'quick_task', translation_task_id: taskId, input_artifact_id: body.input_artifact_id },
          artifacts: [],
        }),
      })
    })
    await page.route(`**/api/runs/${currentRunId}/translate/start`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: currentRunId,
          project_id: projectId,
          kind: 'translation',
          language: 'en',
          status: 'passed',
          created_at: '2026-07-15T10:00:00Z',
          updated_at: '2026-07-15T10:00:01Z',
          metadata: { task_origin: 'quick_task', translation_task_id: taskId },
          artifacts: [],
        }),
      })
    })
    await page.route(`**/api/projects/*/delivery-package?run_id=${currentRunId}`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          files: [{ kind: 'final', filename: 'stale.txt', path: 'stale.txt', download_url: `/api/projects/${projectId}/delivery/stale.txt` }],
          deliverable: {
            run_id: mismatch === 'run_id' ? 'quick-run-old-task' : currentRunId,
            translation_task_id: mismatch === 'translation_task_id' ? 'quick-task-old' : taskId,
          },
          archive: null,
        }),
      })
    })
    await page.route('**/api/projects/*/delivery/stale.txt', async (route) => {
      downloadReads += 1
      await route.fulfill({ status: 200, contentType: 'text/plain; charset=utf-8', body: 'stale translation' })
    })

    const project = await createQuickProject(page, request, `Delivery Identity ${mismatch}`)
    projectId = project.id
    await preparePastedQuickTask(page, '交付身份隔离')
    await page.getByTestId('quick-task-start').click()

    await expect(page.getByTestId('quick-delivery-error')).toContainText('交付响应与当前快速任务不匹配')
    await expect(page.getByTestId('quick-delivery-result')).toHaveCount(0)
    expect(downloadReads).toBe(0)
  })
}

test('delivery generation failure keeps the same quick task and retries in place', async ({ page, request }) => {
  let deliveryAttempts = 0
  let createdTaskId = ''
  let projectId = ''

  await page.route('**/api/runs', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    const body = route.request().postDataJSON()
    createdTaskId = body.translation_task_id
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ id: 'quick-run-retry', project_id: body.project_id, kind: 'translation', language: body.language, status: 'created', created_at: '2026-07-15T10:00:00Z', updated_at: '2026-07-15T10:00:00Z', metadata: { task_origin: 'quick_task', translation_task_id: body.translation_task_id, input_artifact_id: body.input_artifact_id }, artifacts: [] }),
    })
  })
  await page.route('**/api/runs/quick-run-retry/translate/start', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: 'quick-run-retry', project_id: projectId, kind: 'translation', language: 'en', status: 'passed', created_at: '2026-07-15T10:00:00Z', updated_at: '2026-07-15T10:00:01Z', metadata: { task_origin: 'quick_task', translation_task_id: createdTaskId }, artifacts: [] }) })
  })
  await page.route('**/api/projects/*/delivery-package?run_id=quick-run-retry', async (route) => {
    deliveryAttempts += 1
    if (deliveryAttempts === 1) {
      await route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'delivery unavailable' }) })
      return
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ files: [{ kind: 'final', filename: 'retry.txt', path: 'retry.txt', download_url: `/api/projects/${projectId}/delivery/retry.txt` }], deliverable: { run_id: 'quick-run-retry' }, archive: null }) })
  })
  await page.route('**/api/projects/*/delivery/retry.txt', async (route) => {
    await route.fulfill({ status: 200, contentType: 'text/plain; charset=utf-8', body: 'Retry delivery content' })
  })

  const project = await createQuickProject(page, request, 'Retry')
  projectId = project.id
  await preparePastedQuickTask(page)
  await page.getByTestId('quick-task-start').click()
  await expect(page.getByTestId('quick-delivery-error')).toContainText('delivery unavailable')
  await expect(page.getByTestId('quick-start-next-task')).toHaveCount(0)
  const taskIdBeforeRetry = await page.getByTestId('quick-task-id').getAttribute('data-task-id')

  await page.getByTestId('quick-delivery-retry').click()
  await expect(page.getByTestId('quick-delivery-result')).toContainText('Retry delivery content')
  expect(await page.getByTestId('quick-task-id').getAttribute('data-task-id')).toBe(taskIdBeforeRetry)
  expect(deliveryAttempts).toBe(2)
})

test('browser readback failure retries the same server delivery without a second POST', async ({ page, request }) => {
  let projectId = ''
  let taskId = ''
  let deliveryPosts = 0
  let downloadReads = 0
  await page.route('**/api/runs', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    const body = route.request().postDataJSON()
    taskId = body.translation_task_id
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: 'quick-run-readback', project_id: body.project_id, kind: 'translation', language: 'en', status: 'created', created_at: '2026-07-15T10:00:00Z', updated_at: '2026-07-15T10:00:00Z', metadata: { task_origin: 'quick_task', translation_task_id: taskId, input_artifact_id: body.input_artifact_id }, artifacts: [] }) })
  })
  await page.route('**/api/runs/quick-run-readback/translate/start', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: 'quick-run-readback', project_id: projectId, kind: 'translation', language: 'en', status: 'passed', created_at: '2026-07-15T10:00:00Z', updated_at: '2026-07-15T10:00:01Z', metadata: { task_origin: 'quick_task', translation_task_id: taskId }, artifacts: [] }) })
  })
  await page.route('**/api/projects/*/delivery-package?run_id=quick-run-readback', async (route) => {
    deliveryPosts += 1
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ files: [{ kind: 'final', filename: 'readback.txt', path: 'readback.txt', download_url: `/api/projects/${projectId}/delivery/readback.txt` }], deliverable: { run_id: 'quick-run-readback' }, archive: null }) })
  })
  await page.route('**/api/projects/*/delivery/readback.txt', async (route) => {
    downloadReads += 1
    if (downloadReads === 1) {
      await route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'download unavailable' }) })
      return
    }
    await route.fulfill({ status: 200, contentType: 'text/plain; charset=utf-8', body: 'Readback recovered' })
  })

  const project = await createQuickProject(page, request, 'Readback Retry')
  projectId = project.id
  await preparePastedQuickTask(page)
  await page.getByTestId('quick-task-start').click()
  await expect(page.getByTestId('quick-delivery-error')).toContainText('读回失败')
  await expect(page.getByTestId('quick-delivery-retry')).toHaveText('重试读取交付')
  await page.getByTestId('quick-delivery-retry').click()
  await expect(page.getByTestId('quick-delivery-result')).toContainText('Readback recovered')
  expect(deliveryPosts).toBe(1)
  expect(downloadReads).toBe(2)
})

for (const objective of ['translation', 'qa'] as const) {
  test(`spreadsheet ${objective} T1 delivers and opens a clean T2`, async ({ page, request }) => {
    const workbook = path.resolve('..', 'examples', 'synthetic-language.xlsx')
    let projectId = ''
    let createdTaskId = ''
    await page.route('**/api/runs', async (route) => {
      if (route.request().method() !== 'POST') return route.continue()
      const body = route.request().postDataJSON()
      createdTaskId = body.translation_task_id
      expect(body.kind).toBe(objective === 'qa' ? 'qa' : 'translation')
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ id: `quick-${objective}-workbook-run`, project_id: body.project_id, kind: body.kind, language: body.language, status: 'created', created_at: '2026-07-15T10:00:00Z', updated_at: '2026-07-15T10:00:00Z', metadata: { task_origin: 'quick_task', translation_task_id: body.translation_task_id, input_artifact_id: body.input_artifact_id }, artifacts: [] }),
      })
    })
    const endpoint = objective === 'qa' ? 'qa' : 'translate'
    await page.route(`**/api/runs/quick-${objective}-workbook-run/${endpoint}/start`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ id: `quick-${objective}-workbook-run`, project_id: projectId, kind: objective === 'qa' ? 'qa' : 'translation', language: 'en', status: 'passed', created_at: '2026-07-15T10:00:00Z', updated_at: '2026-07-15T10:00:01Z', metadata: { task_origin: 'quick_task', translation_task_id: createdTaskId }, artifacts: [] }),
      })
    })
    await page.route(`**/api/projects/*/delivery-package?run_id=quick-${objective}-workbook-run`, async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ files: [{ kind: 'final', filename: `${objective}-final.xlsx`, path: `${objective}-final.xlsx`, download_url: `/api/projects/${projectId}/delivery/${objective}-final.xlsx` }], deliverable: { run_id: `quick-${objective}-workbook-run` }, archive: null }) })
    })
    await page.route(`**/api/projects/*/delivery/${objective}-final.xlsx`, async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', body: Buffer.from([0x50, 0x4b, 0x03, 0x04]) })
    })

    const project = await createQuickProject(page, request, `Workbook ${objective}`)
    projectId = project.id
    const firstTaskId = await page.getByTestId('quick-task-id').getAttribute('data-task-id')
    await page.getByTestId('quick-mode-upload').click()
    await page.getByTestId('quick-input-upload').locator('input[type="file"]').setInputFiles(workbook)
    await expect(page.getByTestId('quick-reference-next')).toBeVisible()
    await page.getByTestId('quick-reference-next').click()
    await page.getByTestId(objective === 'qa' ? 'quick-objective-qa' : 'quick-objective-translate').click()
    await page.getByTestId('quick-task-start').click()
    await expect(page.getByTestId('quick-delivery-result')).toContainText(`${objective}-final.xlsx`)
    expect(createdTaskId).toBe(firstTaskId)

    await page.getByTestId('quick-start-next-task').click()
    await expect(page.getByTestId('quick-text-input')).toHaveValue('')
    expect(await page.getByTestId('quick-task-id').getAttribute('data-task-id')).not.toBe(firstTaskId)
  })
}

test('abandon decision rechecks the final snapshot and restores a newly active quick task', async ({ page, request }) => {
  const name = `E2E Quick Race ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name, type: 'quick-task', description: 'Quick entry race coverage.' },
  }).then((response) => response.json())
  await page.goto(baseURL)
  await page.getByRole('button', { name }).click()
  await expect(page.getByTestId('overview-quick-task')).toBeVisible()

  const baseRun = {
    project_id: project.id,
    kind: 'translation',
    language: 'en',
    created_at: '2026-07-15T10:00:00Z',
    updated_at: '2026-07-15T10:00:00Z',
    artifacts: [],
  }
  const stopped = {
    ...baseRun,
    id: 'quick-race-stopped-run',
    status: 'failed',
    metadata: { task_origin: 'quick_task', translation_task_id: 'quick-task-race-stopped' },
  }
  const active = {
    ...baseRun,
    id: 'quick-race-active-run',
    status: 'running',
    updated_at: '2026-07-15T10:01:00Z',
    metadata: { task_origin: 'quick_task', translation_task_id: 'quick-task-race-active' },
  }
  let projectReads = 0
  await page.route(`**/api/projects/${project.id}?**`, async (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    projectReads += 1
    const runs = projectReads >= 3 ? [active, stopped] : [stopped]
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...project, artifacts: [], runs, announcement_tasks: [] }) })
  })
  await page.route(`**/api/projects/${project.id}/translation-tasks/quick-task-race-stopped/abandon`, async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ project_id: project.id, translation_task_id: 'quick-task-race-stopped', state: 'abandoned' }) })
  })

  await page.getByTestId('quick-task-entry').click()
  await expect(page.getByRole('alertdialog')).toContainText('已有未完成快速任务')
  await page.getByTestId('confirm-modal-confirm').click()

  await expect(page.getByTestId('quick-task-id')).toHaveAttribute('data-task-id', 'quick-task-race-active')
  await expect(page.getByText('quick-race-active-run', { exact: false })).toBeVisible()
})

test('a delayed create response is canceled after switching to T2 and never starts the stale run', async ({ page, request }) => {
  const project = await createQuickProject(page, request, 'Stale Create')
  await preparePastedQuickTask(page, '相同输入')
  const firstTaskId = await page.getByTestId('quick-task-id').getAttribute('data-task-id')
  let releaseCreate!: () => void
  const createGate = new Promise<void>((resolve) => { releaseCreate = resolve })
  let markCreateSeen!: () => void
  const createSeen = new Promise<void>((resolve) => { markCreateSeen = resolve })
  let cancelCalls = 0
  let startCalls = 0

  await page.route('**/api/runs', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    const body = route.request().postDataJSON()
    markCreateSeen()
    await createGate
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: 'quick-run-stale-create',
        project_id: project.id,
        kind: 'translation',
        language: 'en',
        status: 'created',
        created_at: '2026-07-15T10:00:00Z',
        updated_at: '2026-07-15T10:00:00Z',
        metadata: { task_origin: 'quick_task', translation_task_id: body.translation_task_id, input_artifact_id: body.input_artifact_id },
        artifacts: [],
      }),
    })
  })
  await page.route('**/api/runs/quick-run-stale-create/translate/start', async (route) => {
    startCalls += 1
    await route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'stale run must not start' }) })
  })
  await page.route('**/api/runs/quick-run-stale-create/translate/cancel', async (route) => {
    cancelCalls += 1
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ id: 'quick-run-stale-create', project_id: project.id, kind: 'translation', language: 'en', status: 'canceled', created_at: '2026-07-15T10:00:00Z', updated_at: '2026-07-15T10:00:01Z', metadata: { task_origin: 'quick_task', translation_task_id: firstTaskId, translation_task_state: 'canceled' }, artifacts: [] }),
    })
  })

  await page.getByTestId('quick-task-start').click()
  await createSeen
  await page.getByTestId('quick-task-entry').click()
  await expect(page.getByTestId('quick-text-input')).toHaveValue('')
  const secondTaskId = await page.getByTestId('quick-task-id').getAttribute('data-task-id')
  expect(secondTaskId).not.toBe(firstTaskId)

  releaseCreate()
  await expect.poll(() => cancelCalls).toBe(1)
  expect(startCalls).toBe(0)
  await expect(page.getByTestId('quick-task-id')).toHaveAttribute('data-task-id', secondTaskId || '')
  await expect(page.getByTestId('quick-text-input')).toHaveValue('')
})

test('leaving quick for a formal task invalidates a delayed create before it can start', async ({ page, request }) => {
  const project = await createQuickProject(page, request, 'Leave Quick During Create')
  await preparePastedQuickTask(page, '离开快速任务')
  const taskId = await page.getByTestId('quick-task-id').getAttribute('data-task-id')
  let releaseCreate!: () => void
  const createGate = new Promise<void>((resolve) => { releaseCreate = resolve })
  let markCreateSeen!: () => void
  const createSeen = new Promise<void>((resolve) => { markCreateSeen = resolve })
  let startCalls = 0
  let cancelCalls = 0

  await page.route('**/api/runs', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    const body = route.request().postDataJSON()
    markCreateSeen()
    await createGate
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: 'quick-run-leave-create',
        project_id: project.id,
        kind: 'translation',
        language: 'en',
        status: 'created',
        created_at: '2026-07-15T10:00:00Z',
        updated_at: '2026-07-15T10:00:00Z',
        metadata: { task_origin: 'quick_task', translation_task_id: body.translation_task_id, input_artifact_id: body.input_artifact_id },
        artifacts: [],
      }),
    })
  })
  await page.route('**/api/runs/quick-run-leave-create/translate/start', async (route) => {
    startCalls += 1
    await route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'stale quick run must not start' }) })
  })
  await page.route('**/api/runs/quick-run-leave-create/translate/cancel', async (route) => {
    cancelCalls += 1
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: 'quick-run-leave-create',
        project_id: project.id,
        kind: 'translation',
        language: 'en',
        status: 'canceled',
        created_at: '2026-07-15T10:00:00Z',
        updated_at: '2026-07-15T10:00:01Z',
        metadata: { task_origin: 'quick_task', translation_task_id: taskId, translation_task_state: 'canceled' },
        artifacts: [],
      }),
    })
  })

  await page.getByTestId('quick-task-start').click()
  await createSeen
  await page.locator('.sidebar').getByRole('button', { name: /新翻译任务/ }).click()
  await expect(page.getByRole('heading', { name: '新翻译任务', exact: true })).toBeVisible()
  releaseCreate()

  await expect.poll(() => cancelCalls).toBe(1)
  expect(startCalls).toBe(0)
  await expect(page.getByRole('heading', { name: '新翻译任务', exact: true })).toBeVisible()
})

test('leaving quick while delivery is pending ignores the stale package response', async ({ page, request }) => {
  let projectId = ''
  let taskId = ''
  let releaseDelivery!: () => void
  const deliveryGate = new Promise<void>((resolve) => { releaseDelivery = resolve })
  let markDeliverySeen!: () => void
  const deliverySeen = new Promise<void>((resolve) => { markDeliverySeen = resolve })
  let downloadReads = 0

  await page.route('**/api/runs', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    const body = route.request().postDataJSON()
    taskId = body.translation_task_id
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: 'quick-run-delivery-scope', project_id: body.project_id, kind: 'translation', language: 'en', status: 'created', created_at: '2026-07-15T10:00:00Z', updated_at: '2026-07-15T10:00:00Z', metadata: { task_origin: 'quick_task', translation_task_id: taskId, input_artifact_id: body.input_artifact_id }, artifacts: [] }) })
  })
  await page.route('**/api/runs/quick-run-delivery-scope/translate/start', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: 'quick-run-delivery-scope', project_id: projectId, kind: 'translation', language: 'en', status: 'passed', created_at: '2026-07-15T10:00:00Z', updated_at: '2026-07-15T10:00:01Z', metadata: { task_origin: 'quick_task', translation_task_id: taskId }, artifacts: [] }) })
  })
  await page.route('**/api/projects/*/delivery-package?run_id=quick-run-delivery-scope', async (route) => {
    markDeliverySeen()
    await deliveryGate
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ files: [{ kind: 'final', filename: 'stale-delivery.txt', path: 'stale-delivery.txt', download_url: `/api/projects/${projectId}/delivery/stale-delivery.txt` }], deliverable: { run_id: 'quick-run-delivery-scope' }, archive: null }) })
  })
  await page.route('**/api/projects/*/delivery/stale-delivery.txt', async (route) => {
    downloadReads += 1
    await route.fulfill({ status: 200, contentType: 'text/plain; charset=utf-8', body: 'stale delivery' })
  })

  const project = await createQuickProject(page, request, 'Leave During Delivery')
  projectId = project.id
  await preparePastedQuickTask(page, '交付响应隔离')
  await page.getByTestId('quick-task-start').click()
  await deliverySeen
  await page.locator('.sidebar').getByRole('button', { name: /新翻译任务/ }).click()
  await expect(page.getByRole('heading', { name: '新翻译任务', exact: true })).toBeVisible()
  releaseDelivery()

  await page.waitForTimeout(400)
  expect(downloadReads).toBe(0)
})

test('leaving quick while browser readback is pending prevents a stale project refresh', async ({ page, request }) => {
  let projectId = ''
  let taskId = ''
  let releaseReadback!: () => void
  const readbackGate = new Promise<void>((resolve) => { releaseReadback = resolve })
  let markReadbackSeen!: () => void
  const readbackSeen = new Promise<void>((resolve) => { markReadbackSeen = resolve })
  let projectReads = 0

  await page.route('**/api/runs', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    const body = route.request().postDataJSON()
    taskId = body.translation_task_id
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: 'quick-run-readback-scope', project_id: body.project_id, kind: 'translation', language: 'en', status: 'created', created_at: '2026-07-15T10:00:00Z', updated_at: '2026-07-15T10:00:00Z', metadata: { task_origin: 'quick_task', translation_task_id: taskId, input_artifact_id: body.input_artifact_id }, artifacts: [] }) })
  })
  await page.route('**/api/runs/quick-run-readback-scope/translate/start', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: 'quick-run-readback-scope', project_id: projectId, kind: 'translation', language: 'en', status: 'passed', created_at: '2026-07-15T10:00:00Z', updated_at: '2026-07-15T10:00:01Z', metadata: { task_origin: 'quick_task', translation_task_id: taskId }, artifacts: [] }) })
  })
  await page.route('**/api/projects/*/delivery-package?run_id=quick-run-readback-scope', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ files: [{ kind: 'final', filename: 'delayed-readback.txt', path: 'delayed-readback.txt', download_url: `/api/projects/${projectId}/delivery/delayed-readback.txt` }], deliverable: { run_id: 'quick-run-readback-scope' }, archive: null }) })
  })
  await page.route('**/api/projects/*/delivery/delayed-readback.txt', async (route) => {
    markReadbackSeen()
    await readbackGate
    await route.fulfill({ status: 200, contentType: 'text/plain; charset=utf-8', body: 'delayed readback' })
  })

  const project = await createQuickProject(page, request, 'Leave During Readback')
  projectId = project.id
  await page.route(`**/api/projects/${project.id}?**`, async (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    projectReads += 1
    await route.continue()
  })
  await preparePastedQuickTask(page, '读回结果隔离')
  await page.getByTestId('quick-task-start').click()
  await readbackSeen
  await page.locator('.sidebar').getByRole('button', { name: /新翻译任务/ }).click()
  await expect(page.getByRole('heading', { name: '新翻译任务', exact: true })).toBeVisible()
  const readsAfterLeaving = projectReads
  releaseReadback()

  await page.waitForTimeout(400)
  expect(projectReads).toBe(readsAfterLeaving)
})

test('lease conflict refreshes the canceled task and leaves no queued ghost', async ({ page, request }) => {
  const project = await createQuickProject(page, request, 'Lease Conflict')
  await preparePastedQuickTask(page, '租约冲突')
  const firstTaskId = await page.getByTestId('quick-task-id').getAttribute('data-task-id')
  const canceledRun = {
    id: 'quick-run-lease-conflict',
    project_id: project.id,
    kind: 'translation',
    language: 'en',
    status: 'canceled',
    created_at: '2026-07-15T10:00:00Z',
    updated_at: '2026-07-15T10:00:01Z',
    metadata: { task_origin: 'quick_task', translation_task_id: firstTaskId, translation_task_state: 'canceled' },
    artifacts: [],
  }
  await page.route('**/api/runs', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    const body = route.request().postDataJSON()
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...canceledRun, status: 'created', metadata: { ...canceledRun.metadata, translation_task_state: undefined, input_artifact_id: body.input_artifact_id } }) })
  })
  await page.route('**/api/runs/quick-run-lease-conflict/translate/start', async (route) => {
    await route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: { code: 'project_busy', active_job_id: 'another-job' } }) })
  })
  await page.route(`**/api/projects/${project.id}?**`, async (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...project, runs: [canceledRun], announcement_tasks: [] }) })
  })

  await page.getByTestId('quick-task-start').click()
  await expect(page.getByText('已取消', { exact: true })).toBeVisible()
  await expect(page.getByTestId('quick-task-start')).toBeDisabled()
  await expect(page.getByText('排队中', { exact: true })).toHaveCount(0)

  await page.getByTestId('quick-task-entry').click()
  await expect(page.getByTestId('quick-text-input')).toHaveValue('')
  expect(await page.getByTestId('quick-task-id').getAttribute('data-task-id')).not.toBe(firstTaskId)
})

for (const kind of ['translation', 'qa'] as const) {
  test(`active quick ${kind} can be stopped through its own endpoint`, async ({ page, request }) => {
    const name = `E2E Quick Stop ${kind} ${Date.now()}`
    const project = await request.post(`${baseURL}/api/projects`, {
      data: { name, type: 'quick-task', description: 'Quick stop coverage.' },
    }).then((response) => response.json())
    await page.goto(baseURL)
    await page.getByRole('button', { name }).click()
    await expect(page.getByTestId('overview-quick-task')).toBeVisible()
    const taskId = `quick-task-stop-${kind}`
    const runId = `quick-run-stop-${kind}`
    let stopped = false
    let cancelCalls = 0
    await page.route(`**/api/projects/${project.id}?**`, async (route) => {
      if (route.request().method() !== 'GET') return route.continue()
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ...project,
          artifacts: [],
          announcement_tasks: [],
          runs: [{
            id: runId,
            project_id: project.id,
            kind,
            language: 'en',
            status: stopped ? 'canceled' : 'running',
            created_at: '2026-07-15T10:00:00Z',
            updated_at: '2026-07-15T10:00:01Z',
            metadata: { task_origin: 'quick_task', translation_task_id: taskId, ...(stopped ? { translation_task_state: 'canceled' } : {}) },
            artifacts: [],
          }],
        }),
      })
    })
    const endpoint = kind === 'qa' ? 'qa' : 'translate'
    await page.route(`**/api/runs/${runId}/${endpoint}/cancel`, async (route) => {
      cancelCalls += 1
      stopped = true
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ id: runId, project_id: project.id, kind, language: 'en', status: 'canceled', created_at: '2026-07-15T10:00:00Z', updated_at: '2026-07-15T10:00:02Z', metadata: { task_origin: 'quick_task', translation_task_id: taskId, translation_task_state: 'canceled' }, artifacts: [] }),
      })
    })

    await page.getByTestId('quick-task-entry').click()
    await expect(page.getByTestId('quick-task-id')).toHaveAttribute('data-task-id', taskId)
    await page.getByTestId('quick-task-stop').click()
    await expect.poll(() => cancelCalls).toBe(1)
    await expect(page.getByTestId('quick-task-stop')).toHaveCount(0)
    await expect(page.getByText('快速任务已停止', { exact: false })).toBeVisible()
  })
}

test('history previews the selected task files without replacing the live active task', async ({ page, request }) => {
  const name = `E2E Quick History ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name, type: 'quick-task', description: 'Quick history exact selection.' },
  }).then((response) => response.json())
  await page.goto(baseURL)
  await page.getByRole('button', { name }).click()
  await expect(page.getByTestId('overview-quick-task')).toBeVisible()
  const run = (id: string, taskId: string, kind: 'translation' | 'qa', language: string, state: string, status: string, updated: string) => ({
    id,
    project_id: project.id,
    kind,
    language,
    status,
    created_at: updated,
    updated_at: updated,
    metadata: { task_origin: 'quick_task', translation_task_id: taskId, ...(state ? { translation_task_state: state, translation_task_state_updated_at: updated } : {}) },
    artifacts: [],
  })
  const runs = [
    run('quick-history-active-run', 'quick-task-history-active', 'translation', 'en', '', 'running', '2026-07-15T12:00:00Z'),
    run('quick-history-t2-run', 'quick-task-history-t2', 'translation', 'kr', 'delivered', 'passed', '2026-07-15T11:00:00Z'),
    run('quick-history-t1-run', 'quick-task-history-t1', 'qa', 'en', 'delivered', 'passed', '2026-07-15T10:00:00Z'),
  ]
  await page.route(`**/api/projects/${project.id}?**`, async (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...project, artifacts: [], announcement_tasks: [], runs }) })
  })
  await page.route(`**/api/projects/${project.id}/deliverables`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        project_id: project.id,
        deliverables: [
          { run_id: 'quick-history-t2-run', files: { final: { kind: 'final', filename: 'T2-final.xlsx', path: 'T2-final.xlsx', download_url: `/api/projects/${project.id}/delivery/T2-final.xlsx` }, outputs: [] } },
          { run_id: 'quick-history-t1-run', files: { final: { kind: 'final', filename: 'T1-final.xlsx', path: 'T1-final.xlsx', download_url: `/api/projects/${project.id}/delivery/T1-final.xlsx` }, outputs: [] } },
        ],
      }),
    })
  })

  await page.getByTestId('quick-task-entry').click()
  await expect(page.getByTestId('quick-task-id')).toHaveAttribute('data-task-id', 'quick-task-history-active')
  const t1Row = page.locator('.quick-history-card tbody tr').filter({ hasText: '快速校对' })
  await t1Row.getByRole('button', { name: '查看交付' }).click()
  await expect(page.getByRole('link', { name: /T1-final\.xlsx/ })).toBeVisible()
  await expect(page.getByRole('link', { name: /T2-final\.xlsx/ })).toHaveCount(0)

  await page.getByRole('button', { name: '返回项目概览', exact: true }).click()
  await page.getByTestId('quick-task-entry').click()
  await expect(page.getByTestId('quick-task-id')).toHaveAttribute('data-task-id', 'quick-task-history-active')
})

test('history detail opens the exact terminal quick QA run as read-only', async ({ page, request }) => {
  const name = `E2E Quick Exact Detail ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name, type: 'quick-task', description: 'Quick exact detail coverage.' },
  }).then((response) => response.json())
  const formalRun = {
    id: 'formal-newer-run',
    project_id: project.id,
    kind: 'qa',
    language: 'en',
    status: 'passed',
    created_at: '2026-07-15T12:00:00Z',
    updated_at: '2026-07-15T12:00:00Z',
    metadata: { task_origin: 'translation_run', translation_task_id: 'translation-task-newer', quality: { hard_errors: 0 } },
    artifacts: [],
  }
  const quickRun = {
    id: 'quick-history-exact-qa',
    project_id: project.id,
    kind: 'qa',
    language: 'en',
    status: 'failed',
    created_at: '2026-07-15T10:00:00Z',
    updated_at: '2026-07-15T10:00:01Z',
    metadata: {
      task_origin: 'quick_task',
      translation_task_id: 'quick-task-history-exact',
      translation_task_state: 'canceled',
      translation_task_state_updated_at: '2026-07-15T10:00:02Z',
      quality: { hard_errors: 1 },
    },
    artifacts: [],
  }
  const quickTranslationRun = {
    ...quickRun,
    id: 'quick-history-exact-translation',
    kind: 'translation',
    created_at: '2026-07-15T09:00:00Z',
    updated_at: '2026-07-15T09:00:01Z',
    metadata: {
      ...quickRun.metadata,
      translation_task_id: 'quick-task-history-exact-translation',
      translation_task_state_updated_at: '2026-07-15T09:00:02Z',
    },
  }
  await page.route(`**/api/projects/${project.id}?**`, async (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...project, artifacts: [], announcement_tasks: [], runs: [formalRun, quickRun, quickTranslationRun] }) })
  })
  await page.goto(baseURL)
  await page.getByRole('button', { name }).click()
  await page.getByTestId('quick-task-entry').click()
  const selectedRow = page.locator('.quick-history-card tbody tr').filter({ hasText: '快速校对' })
  await selectedRow.getByRole('button', { name: '查看详情' }).click()

  await expect(page.locator('.view-tab.active')).toContainText('校对')
  await expect(page.getByTestId('qa-outcome-panel')).toContainText('QA 未通过')
  await expect(page.getByText('历史终态快速任务仅供查看。')).toBeVisible()
  await expect(page.getByRole('button', { name: /修复并重跑/ })).toHaveCount(0)

  await page.getByTestId('quick-task-entry').click()
  const translationRow = page.locator('.quick-history-card tbody tr').filter({ hasText: '快速翻译' })
  await translationRow.getByRole('button', { name: '查看详情' }).click()
  await expect(page.locator('.view-tab.active')).toContainText('翻译')
  await expect(page.getByTestId('formal-translate')).toHaveCount(0)
  await expect(page.getByText('历史终态快速任务仅供查看。')).toBeVisible()
})

test('focused quick QA model repair polls through to its new result run without losing focus', async ({ page, request }) => {
  const name = `E2E Quick Repair Focus ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name, type: 'quick-task', description: 'Quick repair focus coverage.' },
  }).then((response) => response.json())
  const taskId = 'quick-task-repair-focus'
  const sourceRun = {
    id: 'quick-repair-source',
    project_id: project.id,
    kind: 'qa',
    language: 'en',
    status: 'failed',
    created_at: '2026-07-15T10:00:00Z',
    updated_at: '2026-07-15T10:00:01Z',
    metadata: { task_origin: 'quick_task', translation_task_id: taskId, quality: { hard_errors: 1 } },
    artifacts: [],
  }
  const formalArtifact = { id: 'formal-qa-artifact', project_id: project.id, label: 'formal-newer.xlsx', kind: 'qa_final_workbook', role: 'qa_final_workbook', path: 'formal-newer.xlsx', size: 10, created_at: '2026-07-15T12:00:00Z', run_id: 'formal-newer-qa' }
  const resultArtifact = { id: 'quick-result-artifact', project_id: project.id, label: 'quick-result.xlsx', kind: 'qa_final_workbook', role: 'qa_final_workbook', path: 'quick-result.xlsx', size: 10, created_at: '2026-07-15T11:00:00Z', run_id: 'quick-repair-result' }
  const formalRun = {
    id: 'formal-newer-qa',
    project_id: project.id,
    kind: 'qa',
    language: 'en',
    status: 'passed',
    created_at: '2026-07-15T12:00:00Z',
    updated_at: '2026-07-15T12:00:00Z',
    metadata: { task_origin: 'translation_run', translation_task_id: 'translation-task-newer', quality: { hard_errors: 0 } },
    artifacts: [formalArtifact],
  }
  const resultRun = {
    id: 'quick-repair-result',
    project_id: project.id,
    kind: 'qa',
    language: 'en',
    status: 'passed',
    created_at: '2026-07-15T11:00:00Z',
    updated_at: '2026-07-15T11:00:01Z',
    metadata: { task_origin: 'quick_task', translation_task_id: taskId, quality: { hard_errors: 0 }, model_fix_source_run_id: sourceRun.id },
    artifacts: [resultArtifact],
  }
  let modelStarted = false
  let resultAvailable = false

  await page.route(`**/api/projects/${project.id}?**`, async (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    const runs = resultAvailable
      ? [formalRun, resultRun, sourceRun]
      : modelStarted
        ? [formalRun, { ...sourceRun, status: 'running', metadata: { ...sourceRun.metadata, model_fix_status: 'running' } }]
        : [formalRun, sourceRun]
    const artifacts = resultAvailable ? [formalArtifact, resultArtifact] : [formalArtifact]
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...project, artifacts, announcement_tasks: [], runs }) })
  })
  await page.route('**/api/runs/quick-repair-source/quality-issues', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ issues: [{ id: 'repair-issue-1', source: '开始游戏', rule_source: 'rule', severity: 'hard', sheet: 'Sheet1', row: 2, check_type: 'translation', message: 'needs repair', current_translation: 'Start' }] }) })
  })
  await page.route('**/api/runs/quick-repair-source/model-fixes/start', async (route) => {
    modelStarted = true
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...sourceRun, status: 'running', updated_at: '2026-07-15T10:00:02Z', metadata: { ...sourceRun.metadata, model_fix_status: 'running' } }) })
  })
  await page.route('**/api/runs/quick-repair-source', async (route) => {
    resultAvailable = true
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...sourceRun, status: 'failed', updated_at: '2026-07-15T10:00:03Z', metadata: { ...sourceRun.metadata, model_fix_status: 'completed', model_fix_result_run_id: resultRun.id } }) })
  })
  await page.route('**/api/runs/quick-repair-result', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(resultRun) })
  })

  await page.goto(baseURL)
  await page.getByRole('button', { name }).click()
  await page.getByTestId('quick-task-entry').click()
  await expect(page.getByRole('alertdialog')).toContainText('已有未完成快速任务')
  await page.getByTestId('confirm-modal-cancel').click()
  await expect(page.getByTestId('quick-task-id')).toHaveAttribute('data-task-id', taskId)
  await page.getByRole('button', { name: '查看详情', exact: true }).first().click()

  await expect(page.getByRole('button', { name: /修复并重跑/ })).toBeEnabled()
  await page.getByRole('button', { name: /修复并重跑/ }).click()
  await expect(page.getByTestId('qa-download-final'), { timeout: 10000 }).toHaveAttribute('href', /quick-result-artifact/)
  await expect(page.getByTestId('qa-outcome-panel')).toContainText('QA 已通过')
})

test('quick run polling stops affecting formal overview after leaving the quick view', async ({ page, request }) => {
  const name = `E2E Quick Poll Isolation ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name, type: 'quick-task', description: 'Quick poll isolation coverage.' },
  }).then((response) => response.json())
  const taskId = 'quick-task-poll-isolation'
  const runningRun = {
    id: 'quick-run-poll-isolation',
    project_id: project.id,
    kind: 'translation',
    language: 'en',
    status: 'running',
    created_at: '2026-07-15T10:00:00Z',
    updated_at: '2026-07-15T10:00:01Z',
    metadata: { task_origin: 'quick_task', translation_task_id: taskId },
    artifacts: [],
  }
  let projectReads = 0
  let runPassed = false

  await page.route(`**/api/projects/${project.id}?**`, async (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    projectReads += 1
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...project, artifacts: [], announcement_tasks: [], runs: [runningRun] }) })
  })
  await page.route('**/api/runs/quick-run-poll-isolation', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(runPassed ? { ...runningRun, status: 'passed', updated_at: '2026-07-15T10:00:02Z' } : runningRun),
    })
  })

  await page.goto(baseURL)
  await page.getByRole('button', { name }).click()
  await page.getByTestId('quick-task-entry').click()
  await expect(page.getByTestId('quick-task-id')).toHaveAttribute('data-task-id', taskId)
  const readsBeforeSnapshot = projectReads
  await expect.poll(() => projectReads, { timeout: 9000 }).toBeGreaterThan(readsBeforeSnapshot)
  await page.waitForTimeout(250)

  await page.getByRole('button', { name: '返回项目概览', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('准备就绪')
  runPassed = true
  await page.waitForTimeout(2600)
  await expect(page.getByRole('status')).toContainText('准备就绪')
})

test('abandon 409 refreshes lifecycle state and restores the task that became active', async ({ page, request }) => {
  const name = `E2E Quick Abandon 409 ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name, type: 'quick-task', description: 'Quick abandon conflict coverage.' },
  }).then((response) => response.json())
  const baseRun = {
    project_id: project.id,
    kind: 'translation',
    language: 'en',
    created_at: '2026-07-15T10:00:00Z',
    updated_at: '2026-07-15T10:00:00Z',
    artifacts: [],
  }
  const stopped = { ...baseRun, id: 'quick-409-stopped-run', status: 'failed', metadata: { task_origin: 'quick_task', translation_task_id: 'quick-task-409-stopped' } }
  const active = { ...baseRun, id: 'quick-409-active-run', status: 'running', updated_at: '2026-07-15T10:01:00Z', metadata: { task_origin: 'quick_task', translation_task_id: 'quick-task-409-active' } }
  let abandonAttempted = false

  await page.route(`**/api/projects/${project.id}?**`, async (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...project, artifacts: [], announcement_tasks: [], runs: abandonAttempted ? [active, stopped] : [stopped] }) })
  })
  await page.route(`**/api/projects/${project.id}/translation-tasks/quick-task-409-stopped/abandon`, async (route) => {
    abandonAttempted = true
    await route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: { code: 'task_became_active', task_id: 'quick-task-409-active' } }) })
  })

  await page.goto(baseURL)
  await page.getByRole('button', { name }).click()
  await page.getByTestId('quick-task-entry').click()
  await expect(page.getByRole('alertdialog')).toContainText('已有未完成快速任务')
  await page.getByTestId('confirm-modal-confirm').click()

  await expect(page.getByTestId('quick-task-id')).toHaveAttribute('data-task-id', 'quick-task-409-active')
  await expect(page.getByText('quick-409-active-run', { exact: false })).toBeVisible()
})

test('formal translation remains actionable after returning from a project whose latest run is a delivered quick task', async ({ page, request }) => {
  await request.patch(`${baseURL}/api/settings`, {
    data: { provider: 'test-fake', model: 'test-fake-localization', batch_size: 1 },
  })
  const name = `E2E Quick Formal Translation Isolation ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name, type: 'quick-task', description: 'Quick latest run must not block formal overview actions.' },
  }).then((response) => response.json())
  const source = {
    id: 'formal-source-after-quick',
    project_id: project.id,
    label: 'formal-source-after-quick.xlsx',
    kind: 'language_table',
    role: 'language_source',
    path: 'formal-source-after-quick.xlsx',
    size: 100,
    created_at: '2026-07-15T10:00:00Z',
  }
  const term = {
    id: 'formal-term-after-quick',
    project_id: project.id,
    label: 'formal-term-after-quick.xlsx',
    kind: 'term_base',
    role: 'glossary_curated',
    path: 'formal-term-after-quick.xlsx',
    size: 100,
    created_at: '2026-07-15T10:00:00Z',
  }
  const quickRun = {
    id: 'latest-delivered-quick-translation',
    project_id: project.id,
    kind: 'translation',
    language: 'en',
    status: 'passed',
    created_at: '2026-07-15T12:00:00Z',
    updated_at: '2026-07-15T12:00:01Z',
    metadata: {
      task_origin: 'quick_task',
      translation_task_id: 'quick-task-latest-delivered-translation',
      translation_task_state: 'delivered',
      translation_task_state_updated_at: '2026-07-15T12:00:02Z',
      input_artifact_id: source.id,
      quality: { passed: true },
    },
    artifacts: [],
  }
  const formalRun = {
    id: 'formal-run-after-delivered-quick',
    project_id: project.id,
    kind: 'translation',
    language: 'en',
    status: 'created',
    created_at: '2026-07-15T13:00:00Z',
    updated_at: '2026-07-15T13:00:00Z',
    metadata: { task_origin: 'translation_run', input_artifact_id: source.id },
    artifacts: [],
  }
  let formalCreateBody: Record<string, unknown> | null = null
  let formalStartCalls = 0

  await page.route(`**/api/projects/${project.id}?**`, async (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ...project, artifacts: [source, term], announcement_tasks: [], runs: [quickRun] }),
    })
  })
  await page.route(`**/api/projects/${project.id}/artifacts/${source.id}/translation-readiness?**`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        artifact_id: source.id,
        label: source.label,
        target_language: 'en',
        source_rows: 2,
        translated_rows: 0,
        empty_target_rows: 2,
        cjk_target_rows: 0,
        needs_translation: true,
        ready_for_translation: true,
        ready_for_qa: false,
        reason: 'target_column_empty',
        batch_size: 1,
        estimated_batches: 2,
        input_mode: 'needs_translation',
        next_step: 5,
      }),
    })
  })
  await page.route('**/api/runs', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    formalCreateBody = route.request().postDataJSON()
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(formalRun) })
  })
  await page.route(`**/api/runs/${formalRun.id}/translate/start`, async (route) => {
    formalStartCalls += 1
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ...formalRun, status: 'queued', updated_at: '2026-07-15T13:00:01Z' }),
    })
  })

  await page.goto(baseURL)
  await page.getByRole('button', { name }).click()
  await page.getByTestId('quick-task-entry').click()
  await expect(page.getByTestId('quick-task-id')).toBeVisible()
  await page.locator('.proj-head').getByRole('button').click()
  await page.locator('.view-tabs .view-tab').nth(2).click()

  await expect(page.getByTestId('formal-translate')).toBeEnabled()
  await page.getByTestId('formal-translate').click()
  await expect.poll(() => formalStartCalls, { timeout: 3000 }).toBe(1)
  expect(formalCreateBody?.translation_task_id ?? null).toBeNull()
})

test('direct QA starts normally after returning from a project whose latest run is a delivered quick QA', async ({ page, request }) => {
  const name = `E2E Quick Formal QA Isolation ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name, type: 'quick-task', description: 'Quick latest QA must not discard a formal direct QA start.' },
  }).then((response) => response.json())
  const qaArtifact = {
    id: 'formal-qa-input-after-quick',
    project_id: project.id,
    label: 'formal-qa-input-after-quick.xlsx',
    kind: 'qa_final_workbook',
    role: 'translation_workbook',
    path: 'formal-qa-input-after-quick.xlsx',
    size: 100,
    created_at: '2026-07-15T10:00:00Z',
    run_id: 'latest-delivered-quick-qa',
  }
  const quickRun = {
    id: 'latest-delivered-quick-qa',
    project_id: project.id,
    kind: 'qa',
    language: 'en',
    status: 'failed',
    created_at: '2026-07-15T12:00:00Z',
    updated_at: '2026-07-15T12:00:01Z',
    metadata: {
      task_origin: 'quick_task',
      translation_task_id: 'quick-task-latest-delivered-qa',
      translation_task_state: 'delivered',
      translation_task_state_updated_at: '2026-07-15T12:00:02Z',
      input_artifact_id: qaArtifact.id,
      quality: { passed: false, hard_errors: 1 },
    },
    artifacts: [qaArtifact],
  }
  const formalQaRun = {
    id: 'formal-qa-run-after-delivered-quick',
    project_id: project.id,
    kind: 'qa',
    language: 'en',
    status: 'created',
    created_at: '2026-07-15T13:00:00Z',
    updated_at: '2026-07-15T13:00:00Z',
    metadata: { task_origin: 'direct_import', input_artifact_id: qaArtifact.id },
    artifacts: [],
  }
  let qaCreateBody: Record<string, unknown> | null = null
  let qaStartCalls = 0

  await page.route(`**/api/projects/${project.id}?**`, async (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ...project, artifacts: [qaArtifact], announcement_tasks: [], runs: [quickRun] }),
    })
  })
  await page.route('**/api/runs', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    qaCreateBody = route.request().postDataJSON()
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(formalQaRun) })
  })
  await page.route(`**/api/runs/${formalQaRun.id}/qa/start`, async (route) => {
    qaStartCalls += 1
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ...formalQaRun, status: 'queued', updated_at: '2026-07-15T13:00:01Z' }),
    })
  })

  await page.goto(baseURL)
  await page.getByRole('button', { name }).click()
  await page.getByTestId('quick-task-entry').click()
  await expect(page.getByTestId('quick-task-id')).toBeVisible()
  await page.locator('.proj-head').getByRole('button').click()
  await page.locator('.view-tabs .view-tab').nth(3).click()

  await expect(page.getByTestId('qa-rerun')).toBeVisible()
  await page.getByTestId('qa-rerun').click()
  await expect.poll(() => qaCreateBody, { timeout: 3000 }).not.toBeNull()
  await expect.poll(() => qaStartCalls, { timeout: 3000 }).toBe(1)
  expect(qaCreateBody?.translation_task_id ?? null).toBeNull()
})
