import { expect, test } from '@playwright/test'

const baseURL = process.env.E2E_BASE_URL ?? `http://127.0.0.1:${process.env.LWS_E2E_FRONTEND_PORT ?? '15173'}`
const storageKey = 'lws.session-navigation'

const selectWizardStep = async (page: any, step: number) => {
  await page.getByTestId('step-menu-toggle').click()
  await page.getByTestId(`step-${step}`).click()
}

test('page refresh refetches project data and resets a client-only formal scope to a clean entry', async ({ page, request }) => {
  const projectName = `E2E Refresh Restore ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'refresh-restore', description: 'Refresh restore coverage.' },
  }).then((response) => response.json())

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.locator('.view-tabs').getByRole('button', { name: '校对', exact: true }).click()
  await page.locator('.sidebar').getByRole('button', { name: /新翻译任务/ }).click()
  await selectWizardStep(page, 4)
  await expect(page.getByTestId('step-menu-toggle')).toContainText('判定输入')

  const stored = await page.evaluate((key) => JSON.parse(localStorage.getItem(key) || '{}'), storageKey)
  expect(Object.keys(stored).sort()).toEqual(['projectId', 'step', 'tab', 'taskScope', 'view'])
  expect(stored).toEqual({
    projectId: project.id,
    view: 'wizard',
    tab: 'meta',
    step: 4,
    taskScope: { kind: 'formal', taskId: expect.stringMatching(/^translation-task-/) },
  })

  const projectReload = page.waitForResponse((response) => (
    response.request().method() === 'GET'
    && new URL(response.url()).pathname === `/api/projects/${project.id}`
  ))
  await page.reload()
  expect((await projectReload).ok()).toBeTruthy()

  await expect(page.getByRole('heading', { name: '新翻译任务', exact: true })).toBeVisible()
  await expect(page.getByTestId('step-menu-toggle')).toContainText('1/9')
  await expect.poll(() => page.evaluate(({ key, previousTaskId }) => {
    const navigation = JSON.parse(localStorage.getItem(key) || '{}')
    return {
      step: navigation.step,
      replacedInvalidTask: Boolean(navigation.taskScope?.taskId && navigation.taskScope.taskId !== previousTaskId),
    }
  }, { key: storageKey, previousTaskId: stored.taskScope.taskId })).toEqual({ step: 1, replacedInvalidTask: true })
  await expect(page.locator('.project-item.active')).toContainText(projectName)
})

test('page refresh restores quick task and announcement views for the current project', async ({ page, request }) => {
  const projectName = `E2E View Restore ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'view-restore', description: 'Quick and announcement view restore coverage.' },
  }).then((response) => response.json())

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()

  await page.getByTestId('quick-task-entry').click()
  await expect(page.locator('.quick-steps')).toBeVisible()
  await expect.poll(() => page.evaluate((key) => JSON.parse(localStorage.getItem(key) || '{}').view, storageKey)).toBe('quick')
  const quickReload = page.waitForResponse((response) => (
    response.request().method() === 'GET'
    && new URL(response.url()).pathname === `/api/projects/${project.id}`
  ))
  await page.reload()
  expect((await quickReload).ok()).toBeTruthy()
  await expect(page.locator('.quick-steps')).toBeVisible()
  await expect(page.locator('.project-item.active')).toContainText(projectName)

  await page.getByRole('button', { name: projectName }).click()
  await expect(page.getByRole('heading', { name: projectName })).toBeVisible()
  await page.locator('main .proj-head').getByRole('button', { name: '新公告任务', exact: true }).click()
  await expect(page.getByRole('heading', { name: '公告翻译', exact: true })).toBeVisible()
  await expect.poll(() => page.evaluate((key) => JSON.parse(localStorage.getItem(key) || '{}').view, storageKey)).toBe('announcement')
  const announcementReload = page.waitForResponse((response) => (
    response.request().method() === 'GET'
    && new URL(response.url()).pathname === `/api/projects/${project.id}`
  ))
  await page.reload()
  expect((await announcementReload).ok()).toBeTruthy()
  await expect(page.getByRole('heading', { name: '公告翻译', exact: true })).toBeVisible()
  await expect(page.locator('.project-item.active')).toContainText(projectName)
})

test('navigation storage clamps the step, rejects unsupported enums, and ignores corrupt or deleted projects', async ({ page, request }) => {
  const projectName = `E2E Navigation Validation ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'refresh-validation', description: 'Navigation validation coverage.' },
  }).then((response) => response.json())

  await page.goto(baseURL)
  const parsed = await page.evaluate(async ({ key, projectId }) => {
    const { parseSessionNavigation } = await import('/src/sessionNavigation.ts')
    return {
      clamped: parseSessionNavigation(JSON.stringify({ projectId, view: 'wizard', tab: 'delivery', step: 99 })),
      formalScope: parseSessionNavigation(JSON.stringify({ projectId, view: 'wizard', tab: 'meta', step: 7, taskScope: { kind: 'formal', taskId: 'translation-task-restored' } })),
      quickScope: parseSessionNavigation(JSON.stringify({ projectId, view: 'quick', tab: 'meta', step: 3, taskScope: { kind: 'quick', taskId: 'quick-task-restored', runId: 'quick-run-restored' } })),
      malformedScope: parseSessionNavigation(JSON.stringify({ projectId, view: 'quick', tab: 'meta', step: 3, taskScope: { kind: 'quick', taskId: 'quick-task-restored' } })),
      invalidEnums: parseSessionNavigation(JSON.stringify({ projectId, view: 'unsupported', tab: 'internal', step: 4 })),
      corrupt: parseSessionNavigation('{not-json'),
      key,
    }
  }, { key: storageKey, projectId: project.id })
  expect(parsed.clamped).toEqual({ projectId: project.id, view: 'wizard', tab: 'delivery', step: 9 })
  expect(parsed.formalScope).toEqual({ projectId: project.id, view: 'wizard', tab: 'meta', step: 7, taskScope: { kind: 'formal', taskId: 'translation-task-restored' } })
  expect(parsed.quickScope).toEqual({ projectId: project.id, view: 'quick', tab: 'meta', step: 3, taskScope: { kind: 'quick', taskId: 'quick-task-restored', runId: 'quick-run-restored' } })
  expect(parsed.malformedScope).toEqual({ projectId: project.id, view: 'quick', tab: 'meta', step: 3 })
  expect(parsed.invalidEnums).toBeNull()
  expect(parsed.corrupt).toBeNull()

  await page.evaluate(({ key, projectId }) => localStorage.setItem(key, JSON.stringify({
    projectId,
    view: 'overview',
    tab: 'meta',
    step: 1,
    taskScope: { kind: 'quick', taskId: 'quick-task-history-only', runId: 'quick-run-history-only' },
  })), { key: storageKey, projectId: project.id })
  await page.reload()
  await expect.poll(() => page.evaluate((key) => Object.prototype.hasOwnProperty.call(
    JSON.parse(localStorage.getItem(key) || '{}'),
    'taskScope',
  ), storageKey)).toBe(false)

  await page.evaluate(({ key }) => localStorage.setItem(key, '{not-json'), { key: storageKey })
  await page.reload()
  await expect(page.locator('main')).toBeVisible()

  await page.evaluate(({ key }) => localStorage.setItem(key, JSON.stringify({
    projectId: 'project-that-no-longer-exists',
    view: 'wizard',
    tab: 'delivery',
    step: 9,
  })), { key: storageKey })
  await page.reload()
  await expect(page.getByRole('heading', { name: '新翻译任务', exact: true })).toHaveCount(0)
  await expect.poll(() => page.evaluate((key) => {
    const fallback = JSON.parse(localStorage.getItem(key) || '{}')
    return {
      hasValidProject: Boolean(fallback.projectId && fallback.projectId !== 'project-that-no-longer-exists'),
      view: fallback.view,
      tab: fallback.tab,
      step: fallback.step,
    }
  }, storageKey)).toEqual({ hasValidProject: true, view: 'overview', tab: 'meta', step: 1 })
})

test('reload restores the exact formal task scope when the project has two unfinished tasks', async ({ page, request }) => {
  const projectName = `E2E Formal Scope Restore ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'formal-scope-restore', description: 'Exact formal task restore coverage.' },
  }).then((response) => response.json())
  const snapshot = await request.get(`${baseURL}/api/projects/${project.id}`).then((response) => response.json())
  const artifact = (id: string, label: string, createdAt: string) => ({
    id,
    project_id: project.id,
    label,
    kind: 'language_table',
    role: 'language_source',
    path: `${id}.xlsx`,
    size: 10,
    created_at: createdAt,
    exists: true,
  })
  const run = (id: string, taskId: string, sourceArtifactId: string, updatedAt: string) => ({
    id,
    project_id: project.id,
    kind: 'translation',
    language: 'en',
    status: 'failed',
    created_at: updatedAt,
    updated_at: updatedAt,
    metadata: {
      task_origin: 'translation_run',
      translation_task_id: taskId,
      input_artifact_id: sourceArtifactId,
    },
    artifacts: [],
  })
  const restoredTaskId = 'translation-task-restore-old'
  const restoredSourceId = 'formal-source-old'
  const newerSourceId = 'formal-source-new'
  const detail = {
    ...snapshot,
    artifacts: [
      artifact(newerSourceId, 'newer-language-table.xlsx', '2026-07-16T11:00:00Z'),
      artifact(restoredSourceId, 'restored-language-table.xlsx', '2026-07-16T10:00:00Z'),
    ],
    runs: [
      run('formal-run-new', 'translation-task-newer', newerSourceId, '2026-07-16T11:00:00Z'),
      run('formal-run-old', restoredTaskId, restoredSourceId, '2026-07-16T10:00:00Z'),
    ],
    announcement_tasks: [],
  }
  await page.route(`**/api/projects/${project.id}?**`, async (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(detail) })
  })
  await page.addInitScript(({ key, value }) => localStorage.setItem(key, JSON.stringify(value)), {
    key: storageKey,
    value: {
      projectId: project.id,
      view: 'wizard',
      tab: 'meta',
      step: 7,
      taskScope: { kind: 'formal', taskId: restoredTaskId },
    },
  })

  await page.goto(baseURL)

  await expect.poll(() => page.evaluate((key) => JSON.parse(localStorage.getItem(key) || '{}').taskScope, storageKey)).toEqual({
    kind: 'formal',
    taskId: restoredTaskId,
  })
  await expect(page.locator('.step-panel.active .asset-select select')).toHaveValue(restoredSourceId)
})

test('reload restores the exact active quick task and run scope instead of an idle session', async ({ page, request }) => {
  const projectName = `E2E Quick Scope Restore ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'quick-scope-restore', description: 'Exact quick task restore coverage.' },
  }).then((response) => response.json())
  const snapshot = await request.get(`${baseURL}/api/projects/${project.id}`).then((response) => response.json())
  const restoredTaskId = 'quick-task-restore-queued'
  const restoredRunId = 'quick-run-restore-queued'
  const runs = [
    {
      id: 'quick-run-newer-delivered',
      project_id: project.id,
      kind: 'translation',
      language: 'ja',
      status: 'passed',
      created_at: '2026-07-16T11:00:00Z',
      updated_at: '2026-07-16T11:00:00Z',
      metadata: { task_origin: 'quick_task', translation_task_id: 'quick-task-newer-delivered', translation_task_state: 'delivered' },
      artifacts: [],
    },
    {
      id: restoredRunId,
      project_id: project.id,
      kind: 'translation',
      language: 'en',
      status: 'queued',
      created_at: '2026-07-16T10:00:00Z',
      updated_at: '2026-07-16T10:00:00Z',
      metadata: { task_origin: 'quick_task', translation_task_id: restoredTaskId },
      artifacts: [],
    },
  ]
  await page.route(`**/api/projects/${project.id}?**`, async (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ...snapshot, artifacts: [], runs, announcement_tasks: [] }),
    })
  })
  await page.addInitScript(({ key, value }) => localStorage.setItem(key, JSON.stringify(value)), {
    key: storageKey,
    value: {
      projectId: project.id,
      view: 'quick',
      tab: 'meta',
      step: 3,
      taskScope: { kind: 'quick', taskId: restoredTaskId, runId: restoredRunId },
    },
  })

  await page.goto(baseURL)

  await expect(page.getByTestId('quick-task-id')).toHaveAttribute('data-task-id', restoredTaskId, { timeout: 10000 })
  await expect(page.locator('.quick-task-card')).toContainText(restoredRunId)
  await expect.poll(() => page.evaluate((key) => JSON.parse(localStorage.getItem(key) || '{}').taskScope, storageKey)).toEqual({
    kind: 'quick',
    taskId: restoredTaskId,
    runId: restoredRunId,
  })
})

test('reload restores the specified announcement task scope', async ({ page, request }) => {
  const projectName = `E2E Announcement Scope Restore ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'announcement-scope-restore', description: 'Exact announcement task restore coverage.' },
  }).then((response) => response.json())
  const snapshot = await request.get(`${baseURL}/api/projects/${project.id}`).then((response) => response.json())
  const announcement = (id: string, title: string, updatedAt: string) => ({
    id,
    project_id: project.id,
    title,
    source_artifact_id: `source-${id}`,
    source_format: 'txt',
    selected_languages: ['en'],
    status: 'source_ready',
    current_step: 2,
    metadata: {},
    languages: [],
    artifacts: [],
    created_at: updatedAt,
    updated_at: updatedAt,
  })
  const restoredTaskId = 'announcement-task-restore-old'
  const detail = {
    ...snapshot,
    artifacts: [],
    runs: [],
    announcement_tasks: [
      announcement('announcement-task-newer', 'Newer announcement task', '2026-07-16T11:00:00Z'),
      announcement(restoredTaskId, 'Restored announcement task', '2026-07-16T10:00:00Z'),
    ],
  }
  await page.route(`**/api/projects/${project.id}?**`, async (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(detail) })
  })
  await page.addInitScript(({ key, value }) => localStorage.setItem(key, JSON.stringify(value)), {
    key: storageKey,
    value: {
      projectId: project.id,
      view: 'announcement',
      tab: 'meta',
      step: 2,
      taskScope: { kind: 'announcement', taskId: restoredTaskId },
    },
  })

  await page.goto(baseURL)

  await expect(page.locator('.announcement-current-task')).toContainText('Restored announcement task', { timeout: 10000 })
  await expect(page.locator('.announcement-current-task')).not.toContainText('Newer announcement task')
  await expect.poll(() => page.evaluate((key) => JSON.parse(localStorage.getItem(key) || '{}').taskScope, storageKey)).toEqual({
    kind: 'announcement',
    taskId: restoredTaskId,
  })
})

test('an invalid quick scope falls back to the current project lifecycle task', async ({ page, request }) => {
  const projectName = `E2E Invalid Quick Scope ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'quick-invalid-scope', description: 'Invalid quick task fallback coverage.' },
  }).then((response) => response.json())
  const snapshot = await request.get(`${baseURL}/api/projects/${project.id}`).then((response) => response.json())
  const fallbackTaskId = 'quick-task-current-project-active'
  const fallbackRunId = 'quick-run-current-project-active'
  const activeRun = {
    id: fallbackRunId,
    project_id: project.id,
    kind: 'translation',
    language: 'en',
    status: 'running',
    created_at: '2026-07-16T12:00:00Z',
    updated_at: '2026-07-16T12:00:00Z',
    metadata: { task_origin: 'quick_task', translation_task_id: fallbackTaskId },
    artifacts: [],
  }
  await page.route(`**/api/projects/${project.id}?**`, async (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ...snapshot, artifacts: [], runs: [activeRun], announcement_tasks: [] }),
    })
  })
  await page.addInitScript(({ key, value }) => localStorage.setItem(key, JSON.stringify(value)), {
    key: storageKey,
    value: {
      projectId: project.id,
      view: 'quick',
      tab: 'meta',
      step: 3,
      taskScope: { kind: 'quick', taskId: 'quick-task-from-another-project', runId: 'quick-run-from-another-project' },
    },
  })

  await page.goto(baseURL)

  await expect(page.getByTestId('quick-task-id')).toHaveAttribute('data-task-id', fallbackTaskId, { timeout: 10000 })
  await expect(page.locator('.quick-task-card')).toContainText(fallbackRunId)
})

test('a missing quick task scope restores the current lifecycle task instead of creating idle state', async ({ page, request }) => {
  const projectName = `E2E Missing Quick Scope ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'quick-missing-scope', description: 'Missing quick scope fallback coverage.' },
  }).then((response) => response.json())
  const snapshot = await request.get(`${baseURL}/api/projects/${project.id}`).then((response) => response.json())
  const taskId = 'quick-task-missing-scope-active'
  const runId = 'quick-run-missing-scope-active'
  const activeRun = {
    id: runId,
    project_id: project.id,
    kind: 'translation',
    language: 'en',
    status: 'running',
    created_at: '2026-07-16T12:00:00Z',
    updated_at: '2026-07-16T12:00:00Z',
    metadata: { task_origin: 'quick_task', translation_task_id: taskId },
    artifacts: [],
  }
  await page.route(`**/api/projects/${project.id}?**`, async (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ...snapshot, artifacts: [], runs: [activeRun], announcement_tasks: [] }),
    })
  })
  await page.addInitScript(({ key, value }) => localStorage.setItem(key, JSON.stringify(value)), {
    key: storageKey,
    value: { projectId: project.id, view: 'quick', tab: 'meta', step: 3 },
  })

  await page.goto(baseURL)

  await expect(page.getByTestId('quick-task-id')).toHaveAttribute('data-task-id', taskId, { timeout: 10000 })
  await expect(page.locator('.quick-task-card')).toContainText(runId)
})

test('a missing formal task scope restores the current lifecycle task', async ({ page, request }) => {
  const projectName = `E2E Missing Formal Scope ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'formal-missing-scope', description: 'Missing formal scope fallback coverage.' },
  }).then((response) => response.json())
  const snapshot = await request.get(`${baseURL}/api/projects/${project.id}`).then((response) => response.json())
  const taskId = 'translation-task-missing-scope-active'
  const sourceId = 'formal-source-missing-scope'
  const source = {
    id: sourceId,
    project_id: project.id,
    label: 'formal-missing-scope.xlsx',
    kind: 'language_table',
    role: 'language_source',
    path: 'formal-missing-scope.xlsx',
    size: 10,
    created_at: '2026-07-16T12:00:00Z',
    exists: true,
  }
  const activeRun = {
    id: 'formal-run-missing-scope',
    project_id: project.id,
    kind: 'translation',
    language: 'en',
    status: 'queued',
    created_at: '2026-07-16T12:00:00Z',
    updated_at: '2026-07-16T12:00:00Z',
    metadata: { task_origin: 'translation_run', translation_task_id: taskId, input_artifact_id: sourceId },
    artifacts: [],
  }
  await page.route(`**/api/projects/${project.id}?**`, async (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ...snapshot, artifacts: [source], runs: [activeRun], announcement_tasks: [] }),
    })
  })
  await page.addInitScript(({ key, value }) => localStorage.setItem(key, JSON.stringify(value)), {
    key: storageKey,
    value: { projectId: project.id, view: 'wizard', tab: 'meta', step: 1 },
  })

  await page.goto(baseURL)

  await expect.poll(() => page.evaluate((key) => JSON.parse(localStorage.getItem(key) || '{}').taskScope, storageKey)).toEqual({
    kind: 'formal',
    taskId,
  })
  await expect(page.getByTestId('step-menu-toggle')).toContainText('7/9')
  await expect(page.locator('.step-panel.active .asset-select select')).toHaveValue(sourceId)
})

test('a missing formal target falls back without inheriting the invalid scope step', async ({ page, request }) => {
  const projectName = `E2E Formal Scope Miss ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'formal-scope-miss', description: 'Formal exact miss step coverage.' },
  }).then((response) => response.json())
  const snapshot = await request.get(`${baseURL}/api/projects/${project.id}`).then((response) => response.json())
  const taskId = 'translation-task-fallback-active'
  const sourceId = 'formal-source-fallback-active'
  const source = {
    id: sourceId,
    project_id: project.id,
    label: 'formal-fallback-active.xlsx',
    kind: 'language_table',
    role: 'language_source',
    path: 'formal-fallback-active.xlsx',
    size: 10,
    created_at: '2026-07-16T12:00:00Z',
    exists: true,
  }
  const activeRun = {
    id: 'formal-run-fallback-active',
    project_id: project.id,
    kind: 'translation',
    language: 'en',
    status: 'queued',
    created_at: '2026-07-16T12:00:00Z',
    updated_at: '2026-07-16T12:00:00Z',
    metadata: { task_origin: 'translation_run', translation_task_id: taskId, input_artifact_id: sourceId },
    artifacts: [],
  }
  await page.route(`**/api/projects/${project.id}?**`, async (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ...snapshot, artifacts: [source], runs: [activeRun], announcement_tasks: [] }),
    })
  })
  await page.addInitScript(({ key, value }) => localStorage.setItem(key, JSON.stringify(value)), {
    key: storageKey,
    value: {
      projectId: project.id,
      view: 'wizard',
      tab: 'delivery',
      step: 9,
      taskScope: { kind: 'formal', taskId: 'translation-task-deleted' },
    },
  })

  await page.goto(baseURL)

  await expect.poll(() => page.evaluate((key) => JSON.parse(localStorage.getItem(key) || '{}').taskScope, storageKey)).toEqual({
    kind: 'formal',
    taskId,
  })
  await expect(page.getByTestId('step-menu-toggle')).toContainText('7/9')
  await expect(page.getByTestId('step-menu-toggle')).not.toContainText('9/9')
})

test('a malformed announcement scope restores the active lifecycle task', async ({ page, request }) => {
  const projectName = `E2E Malformed Announcement Scope ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'announcement-malformed-scope', description: 'Malformed announcement scope fallback coverage.' },
  }).then((response) => response.json())
  const snapshot = await request.get(`${baseURL}/api/projects/${project.id}`).then((response) => response.json())
  const task = (id: string, title: string, status: string, updatedAt: string) => ({
    id,
    project_id: project.id,
    title,
    source_artifact_id: `source-${id}`,
    source_format: 'txt',
    selected_languages: ['en'],
    status,
    current_step: status === 'running' ? 7 : 2,
    metadata: {},
    languages: [],
    artifacts: [],
    created_at: updatedAt,
    updated_at: updatedAt,
  })
  const activeTaskId = 'announcement-malformed-scope-active'
  const tasks = [
    task('announcement-malformed-scope-stopped', 'Stopped announcement chosen by list order', 'source_ready', '2026-07-16T13:00:00Z'),
    task(activeTaskId, 'Active announcement lifecycle task', 'running', '2026-07-16T12:00:00Z'),
  ]
  await page.route(`**/api/projects/${project.id}?**`, async (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ...snapshot, artifacts: [], runs: [], announcement_tasks: tasks }),
    })
  })
  await page.addInitScript(({ key, value }) => localStorage.setItem(key, JSON.stringify(value)), {
    key: storageKey,
    value: {
      projectId: project.id,
      view: 'announcement',
      tab: 'meta',
      step: 7,
      taskScope: { kind: 'quick', taskId: 'malformed-quick-scope-without-run' },
    },
  })

  await page.goto(baseURL)

  await expect(page.locator('.announcement-current-task')).toContainText('Active announcement lifecycle task', { timeout: 10000 })
  await expect.poll(() => page.evaluate((key) => JSON.parse(localStorage.getItem(key) || '{}').taskScope, storageKey)).toEqual({
    kind: 'announcement',
    taskId: activeTaskId,
  })
})

test('a canceled announcement exact scope is rejected in favor of the active lifecycle task', async ({ page, request }) => {
  const projectName = `E2E Canceled Announcement Scope ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'announcement-canceled-scope', description: 'Canceled announcement scope fallback coverage.' },
  }).then((response) => response.json())
  const snapshot = await request.get(`${baseURL}/api/projects/${project.id}`).then((response) => response.json())
  const task = (id: string, title: string, status: string, updatedAt: string) => ({
    id,
    project_id: project.id,
    title,
    source_artifact_id: `source-${id}`,
    source_format: 'txt',
    selected_languages: ['en'],
    status,
    current_step: status === 'running' ? 7 : 2,
    metadata: {},
    languages: [],
    artifacts: [],
    created_at: updatedAt,
    updated_at: updatedAt,
  })
  const canceledTaskId = 'announcement-canceled-scope-exact'
  const activeTaskId = 'announcement-canceled-scope-active'
  const tasks = [
    task(canceledTaskId, 'Canceled announcement exact task', 'canceled', '2026-07-16T14:00:00Z'),
    task('announcement-canceled-scope-stopped', 'Stopped announcement chosen by list order', 'source_ready', '2026-07-16T13:00:00Z'),
    task(activeTaskId, 'Active announcement fallback task', 'running', '2026-07-16T12:00:00Z'),
  ]
  await page.route(`**/api/projects/${project.id}?**`, async (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ...snapshot, artifacts: [], runs: [], announcement_tasks: tasks }),
    })
  })
  await page.addInitScript(({ key, value }) => localStorage.setItem(key, JSON.stringify(value)), {
    key: storageKey,
    value: {
      projectId: project.id,
      view: 'announcement',
      tab: 'meta',
      step: 7,
      taskScope: { kind: 'announcement', taskId: canceledTaskId },
    },
  })

  await page.goto(baseURL)

  await expect(page.locator('.announcement-current-task')).toContainText('Active announcement fallback task', { timeout: 10000 })
  await expect.poll(() => page.evaluate((key) => JSON.parse(localStorage.getItem(key) || '{}').taskScope, storageKey)).toEqual({
    kind: 'announcement',
    taskId: activeTaskId,
  })
})

test('an initial project detail failure preserves formal scope until a retry hydrates the exact task', async ({ page, request }) => {
  const projectName = `E2E Detail Retry Scope ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'detail-retry-scope', description: 'Detail retry scope coverage.' },
  }).then((response) => response.json())
  const snapshot = await request.get(`${baseURL}/api/projects/${project.id}`).then((response) => response.json())
  const taskId = 'translation-task-detail-retry-exact'
  const sourceId = 'formal-source-detail-retry'
  const source = {
    id: sourceId,
    project_id: project.id,
    label: 'formal-detail-retry.xlsx',
    kind: 'language_table',
    role: 'language_source',
    path: 'formal-detail-retry.xlsx',
    size: 10,
    created_at: '2026-07-16T12:00:00Z',
    exists: true,
  }
  const run = {
    id: 'formal-run-detail-retry',
    project_id: project.id,
    kind: 'translation',
    language: 'en',
    status: 'queued',
    created_at: '2026-07-16T12:00:00Z',
    updated_at: '2026-07-16T12:00:00Z',
    metadata: { task_origin: 'translation_run', translation_task_id: taskId, input_artifact_id: sourceId },
    artifacts: [],
  }
  const detail = { ...snapshot, artifacts: [source], runs: [run], announcement_tasks: [] }
  let detailCalls = 0
  let releaseSuccessfulRetry = () => undefined
  const successfulRetryGate = new Promise<void>((resolve) => { releaseSuccessfulRetry = resolve })
  await page.route(`**/api/projects/${project.id}?**`, async (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    detailCalls += 1
    if (detailCalls === 1) {
      await route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'temporary detail failure' }) })
      return
    }
    await successfulRetryGate
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(detail) })
  })
  await page.addInitScript(({ key, value }) => localStorage.setItem(key, JSON.stringify(value)), {
    key: storageKey,
    value: {
      projectId: project.id,
      view: 'wizard',
      tab: 'meta',
      step: 7,
      taskScope: { kind: 'formal', taskId },
    },
  })

  await page.goto(baseURL)

  try {
    await expect.poll(() => detailCalls, { timeout: 5000 }).toBe(2)
    await expect(page.getByText('正在加载项目...', { exact: true })).toBeVisible()
    await expect.poll(() => page.evaluate((key) => JSON.parse(localStorage.getItem(key) || '{}').taskScope, storageKey)).toEqual({
      kind: 'formal',
      taskId,
    })
  } finally {
    releaseSuccessfulRetry()
  }

  await expect.poll(() => page.evaluate((key) => JSON.parse(localStorage.getItem(key) || '{}').taskScope, storageKey)).toEqual({
    kind: 'formal',
    taskId,
  })
  await expect(page.getByTestId('step-menu-toggle')).toContainText('7/9')
  await expect(page.locator('.step-panel.active .asset-select select')).toHaveValue(sourceId)
})
