import { expect, test } from '@playwright/test'

const baseURL = process.env.E2E_BASE_URL ?? `http://127.0.0.1:${process.env.LWS_E2E_FRONTEND_PORT ?? '15173'}`

test('new announcement task prompts to continue or discard a stopped unfinished task', async ({ page, request }) => {
  const projectName = `E2E Announcement Lifecycle ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'announcement', description: 'Announcement lifecycle coverage.' },
  }).then((response) => response.json())
  const taskResponse = await request.post(`${baseURL}/api/projects/${project.id}/announcement-tasks`, {
    data: { text: '停服更新公告。', title: '未完成公告', languages: ['en'] },
  })
  expect(taskResponse.ok()).toBeTruthy()

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.locator('.proj-head .row-actions').getByRole('button', { name: '新公告任务', exact: true }).click()

  const dialog = page.getByRole('alertdialog')
  await expect(dialog).toContainText('已有未完成公告任务')
  await expect(dialog.getByRole('button', { name: '继续当前任务' })).toBeVisible()
  await expect(dialog.getByRole('button', { name: '放弃并新建' })).toBeVisible()
})

test('active announcement task wins over a newer stopped task without creating another task', async ({ page, request }) => {
  const projectName = `E2E Active Announcement ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'announcement', description: 'Active announcement recovery.' },
  }).then((response) => response.json())
  const projectSnapshot = await request.get(`${baseURL}/api/projects/${project.id}`).then((response) => response.json())
  const stoppedTask = {
    id: 'announcement-stopped-newer', project_id: project.id, title: '较新的暂停任务',
    source_artifact_id: 'artifact-stopped', source_format: 'txt', selected_languages: ['en'],
    status: 'source_ready', current_step: 2, metadata: {}, languages: [], artifacts: [],
    created_at: '2026-07-15T10:01:00Z', updated_at: '2026-07-15T10:01:00Z',
  }
  const activeTask = {
    id: 'announcement-active-older', project_id: project.id, title: '正在运行的公告',
    source_artifact_id: 'artifact-active', source_format: 'txt', selected_languages: ['en'],
    status: 'running', current_step: 7, metadata: {}, languages: [], artifacts: [],
    created_at: '2026-07-15T10:00:00Z', updated_at: '2026-07-15T10:00:00Z',
  }
  await page.route(`**/api/projects/${project.id}?**`, async (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ...projectSnapshot, announcement_tasks: [stoppedTask, activeTask] }),
    })
  })
  let createRequests = 0
  await page.route(`**/api/projects/${project.id}/announcement-tasks`, async (route) => {
    if (route.request().method() === 'POST') createRequests += 1
    await route.continue()
  })

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.locator('.proj-head .row-actions').getByRole('button', { name: '新公告任务', exact: true }).click()

  await expect(page.locator('.announcement-current-task')).toContainText('正在运行的公告')
  await expect(page.getByRole('alertdialog')).toHaveCount(0)
  expect(createRequests).toBe(0)
})

test('discard cancels every stopped announcement task before showing a clean first step', async ({ page, request }) => {
  const projectName = `E2E Discard Announcements ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'announcement', description: 'Discard announcement drafts.' },
  }).then((response) => response.json())
  const projectSnapshot = await request.get(`${baseURL}/api/projects/${project.id}`).then((response) => response.json())
  let remainingTasks = [
    {
      id: 'announcement-stopped-one', project_id: project.id, title: '暂停任务一',
      source_artifact_id: 'artifact-one', source_format: 'txt', selected_languages: ['en'],
      status: 'source_ready', current_step: 2, metadata: {}, languages: [], artifacts: [],
      created_at: '2026-07-15T10:00:00Z', updated_at: '2026-07-15T10:00:00Z',
    },
    {
      id: 'announcement-stopped-two', project_id: project.id, title: '暂停任务二',
      source_artifact_id: 'artifact-two', source_format: 'docx', selected_languages: ['ja'],
      status: 'failed', current_step: 7, metadata: {}, languages: [], artifacts: [],
      created_at: '2026-07-15T09:00:00Z', updated_at: '2026-07-15T09:00:00Z',
    },
  ]
  const canceledTaskIds: string[] = []
  await page.route(`**/api/projects/${project.id}?**`, async (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ...projectSnapshot, announcement_tasks: remainingTasks }),
    })
  })
  await page.route('**/api/announcement-tasks/*/cancel', async (route) => {
    const taskId = new URL(route.request().url()).pathname.split('/').at(-2) || ''
    const task = remainingTasks.find((item) => item.id === taskId)
    canceledTaskIds.push(taskId)
    remainingTasks = remainingTasks.filter((item) => item.id !== taskId)
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ task: { ...task, status: 'canceled' } }),
    })
  })

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.locator('.proj-head .row-actions').getByRole('button', { name: '新公告任务', exact: true }).click()
  await page.getByRole('alertdialog').getByRole('button', { name: '放弃并新建' }).click()

  await expect.poll(() => [...canceledTaskIds].sort(), { timeout: 3000 }).toEqual([
    'announcement-stopped-one',
    'announcement-stopped-two',
  ])
  await expect(page.locator('.announcement-current-task')).toHaveCount(0)
  await expect(page.locator('.panel-title', { hasText: '公告资料' })).toBeVisible()
})

test('delivered history opens exactly and start-next reuses the new-task decision', async ({ page, request }) => {
  const projectName = `E2E Delivered Announcement ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'announcement', description: 'Delivered announcement next task.' },
  }).then((response) => response.json())
  const projectSnapshot = await request.get(`${baseURL}/api/projects/${project.id}`).then((response) => response.json())
  const deliveryArtifact = {
    id: 'announcement-delivery-package', project_id: project.id, run_id: null,
    kind: 'announcement_delivery_package', label: '公告交付.zip', path: 'announcement-delivery.zip',
    size: 128, created_at: '2026-07-15T10:00:00Z', metadata: {},
  }
  const stoppedTask = {
    id: 'announcement-next-stopped', project_id: project.id, title: '另一项未完成公告',
    source_artifact_id: 'artifact-next', source_format: 'txt', selected_languages: ['en'],
    status: 'source_ready', current_step: 2, metadata: {}, languages: [], artifacts: [],
    created_at: '2026-07-15T11:00:00Z', updated_at: '2026-07-15T11:00:00Z',
  }
  const deliveredTask = {
    id: 'announcement-delivered', project_id: project.id, title: '已交付公告',
    source_artifact_id: 'artifact-delivered', source_format: 'txt', selected_languages: ['en'],
    status: 'delivered', current_step: 9, metadata: {}, languages: [], artifacts: [deliveryArtifact],
    created_at: '2026-07-15T10:00:00Z', updated_at: '2026-07-15T10:00:00Z',
  }
  await page.route(`**/api/projects/${project.id}?**`, async (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...projectSnapshot,
        artifacts: [deliveryArtifact],
        announcement_tasks: [stoppedTask, deliveredTask],
      }),
    })
  })

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  const deliveredRow = page.locator('.announcement-task-row', { hasText: '已交付公告' })
  await deliveredRow.getByRole('button', { name: '查看交付' }).click()

  await expect(page.getByRole('alertdialog')).toHaveCount(0)
  await expect(page.locator('.announcement-current-task')).toContainText('已交付公告')
  await expect(page.getByRole('button', { name: '返回项目', exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: '下载公告交付包', exact: true })).toHaveAttribute(
    'href',
    `/api/projects/${project.id}/artifacts/${deliveryArtifact.id}/download`,
  )
  const startNext = page.getByRole('button', { name: '开始下一公告任务', exact: true })
  await expect(startNext).toBeVisible()
  await startNext.click()
  await expect(page.getByRole('alertdialog')).toContainText('已有未完成公告任务')
})

test('delivered task with a missing package does not expose next-task actions', async ({ page, request }) => {
  const projectName = `E2E Missing Announcement Package ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'announcement', description: 'Missing delivery package guard.' },
  }).then((response) => response.json())
  const projectSnapshot = await request.get(`${baseURL}/api/projects/${project.id}`).then((response) => response.json())
  const missingPackage = {
    id: 'announcement-missing-package', project_id: project.id, run_id: null,
    kind: 'announcement_delivery_package', label: 'missing-announcement.zip', path: 'missing-announcement.zip',
    size: 128, created_at: '2026-07-15T10:00:00Z', metadata: {}, exists: false,
  }
  const deliveredTask = {
    id: 'announcement-delivered-missing', project_id: project.id, title: '交付文件已丢失',
    source_artifact_id: 'artifact-delivered-missing', source_format: 'txt', selected_languages: ['en'],
    status: 'delivered', current_step: 9, metadata: {}, languages: [], artifacts: [missingPackage],
    created_at: '2026-07-15T10:00:00Z', updated_at: '2026-07-15T10:00:00Z',
  }
  await page.route(`**/api/projects/${project.id}?**`, async (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...projectSnapshot,
        artifacts: [missingPackage],
        announcement_tasks: [deliveredTask],
      }),
    })
  })

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.locator('.announcement-task-row', { hasText: deliveredTask.title }).getByRole('button', { name: '查看交付' }).click()

  await expect(page.locator('.announcement-current-task')).toContainText(deliveredTask.title)
  await expect(page.getByRole('link', { name: '下载公告交付包', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '开始下一公告任务', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '返回项目', exact: true })).toHaveCount(0)
})

test('structured create conflict opens the returned unfinished task', async ({ page, request }) => {
  const projectName = `E2E Announcement Conflict ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'announcement', description: 'Announcement create conflict recovery.' },
  }).then((response) => response.json())
  const projectSnapshot = await request.get(`${baseURL}/api/projects/${project.id}`).then((response) => response.json())
  const sourceArtifact = {
    id: 'announcement-conflict-source', project_id: project.id, run_id: null,
    kind: 'asset', label: 'conflict_notice.txt', path: 'conflict_notice.txt', size: 64,
    created_at: '2026-07-15T10:00:00Z', metadata: { original_filename: 'conflict_notice.txt' },
  }
  const existingTask = {
    id: 'announcement-conflict-existing', project_id: project.id, title: '服务端已有公告',
    source_artifact_id: sourceArtifact.id, source_format: 'txt', selected_languages: ['en'],
    status: 'source_ready', current_step: 2, metadata: {}, languages: [], artifacts: [],
    created_at: '2026-07-15T10:01:00Z', updated_at: '2026-07-15T10:01:00Z',
  }
  let createAttempted = false
  await page.route(`**/api/projects/${project.id}?**`, async (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...projectSnapshot,
        artifacts: [sourceArtifact],
        announcement_tasks: createAttempted ? [existingTask] : [],
      }),
    })
  })
  await page.route(`**/api/projects/${project.id}/announcement-tasks`, async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    createAttempted = true
    await route.fulfill({
      status: 409,
      contentType: 'application/json',
      body: JSON.stringify({
        detail: {
          code: 'unfinished_announcement_task_exists',
          task_id: existingTask.id,
          status: existingTask.status,
        },
      }),
    })
  })

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.locator('.proj-head .row-actions').getByRole('button', { name: '新公告任务', exact: true }).click()
  await page.locator('.check-row', { hasText: 'conflict_notice.txt' }).locator('input').check()
  await page.getByRole('button', { name: '创建公告任务' }).click()

  await expect(page.locator('.announcement-current-task')).toContainText('服务端已有公告')
  await expect(page.locator('.inline-status')).not.toContainText('公告任务创建失败')
})

test('late T1 lookup response cannot replace T2 focus step, run polling, or status', async ({ page, request }) => {
  const projectName = `E2E Announcement Stale ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'announcement', description: 'Announcement stale response isolation.' },
  }).then((response) => response.json())
  const projectSnapshot = await request.get(`${baseURL}/api/projects/${project.id}`).then((response) => response.json())
  const t1 = {
    id: 'announcement-t1', project_id: project.id, title: '公告 T1',
    source_artifact_id: 'artifact-t1', source_format: 'txt', selected_languages: ['en'],
    status: 'terms_ready', current_step: 5, metadata: {}, languages: [], artifacts: [],
    created_at: '2026-07-15T10:00:00Z', updated_at: '2026-07-15T10:00:00Z',
  }
  const t1Finished = {
    ...t1,
    status: 'lookup_ready',
    current_step: 6,
    updated_at: '2026-07-15T10:02:00Z',
  }
  const t2 = {
    id: 'announcement-t2', project_id: project.id, title: '公告 T2',
    source_artifact_id: 'artifact-t2', source_format: 'txt', selected_languages: ['ja'],
    status: 'lookup_ready', current_step: 5, metadata: {}, languages: [], artifacts: [],
    created_at: '2026-07-15T10:01:00Z', updated_at: '2026-07-15T10:01:00Z',
  }
  const t1Run = {
    id: 'announcement-t1-late-run', project_id: project.id, kind: 'announcement_prepare', language: 'en',
    status: 'running', metadata: { task_id: t1.id }, artifacts: [], events: [],
    created_at: '2026-07-15T10:02:00Z', updated_at: '2026-07-15T10:02:00Z',
  }
  let actionRequested = false
  let actionReleased = false
  let postResponseProjectReads = 0
  let staleRunPolls = 0
  let releaseT1!: () => void
  const t1Gate = new Promise<void>((resolve) => { releaseT1 = resolve })
  await page.route(`**/api/projects/${project.id}?**`, async (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    if (actionReleased) postResponseProjectReads += 1
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...projectSnapshot,
        runs: actionReleased ? [t1Run] : [],
        announcement_tasks: [actionReleased ? t1Finished : t1, t2],
      }),
    })
  })
  await page.route(`**/api/announcement-tasks/${t1.id}/lookup-translations`, async (route) => {
    actionRequested = true
    await t1Gate
    actionReleased = true
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ task: t1Finished, run: t1Run, artifacts: [], summary: { detected_languages: ['en'] } }),
    })
  })
  await page.route(`**/api/runs/${t1Run.id}`, async (route) => {
    staleRunPolls += 1
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(t1Run) })
  })

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.locator('.announcement-task-row', { hasText: '公告 T1' }).getByRole('button', { name: '继续' }).click()
  await page.getByRole('button', { name: '反查术语译文' }).click()
  await expect.poll(() => actionRequested).toBe(true)

  await page.getByRole('button', { name: '返回项目概览' }).click()
  await page.locator('.announcement-task-row', { hasText: '公告 T2' }).getByRole('button', { name: '继续' }).click()
  await expect(page.locator('.announcement-current-task')).toContainText('公告 T2')
  await expect(page.locator('.panel-title', { hasText: '译文反查' })).toBeVisible()
  await expect(page.locator('.inline-status')).toContainText('公告任务已就绪')

  const t1Response = page.waitForResponse((response) => response.url().includes(`/api/announcement-tasks/${t1.id}/lookup-translations`))
  releaseT1()
  await t1Response
  await expect.poll(() => postResponseProjectReads).toBeGreaterThan(0)
  await page.waitForTimeout(200)

  await expect(page.locator('.announcement-current-task')).toContainText('公告 T2')
  await expect(page.locator('.panel-title', { hasText: '译文反查' })).toBeVisible()
  await expect(page.locator('.inline-status')).toContainText('公告任务已就绪')
  await page.waitForTimeout(2300)
  expect(staleRunPolls).toBe(0)
})

test('discard conflict opens the task that became active instead of canceling it', async ({ page, request }) => {
  const projectName = `E2E Announcement Discard Race ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'announcement', description: 'Conditional discard coverage.' },
  }).then((response) => response.json())
  const projectSnapshot = await request.get(`${baseURL}/api/projects/${project.id}`).then((response) => response.json())
  const stoppedTask = {
    id: 'announcement-discard-race', project_id: project.id, title: '即将开始运行的公告',
    source_artifact_id: 'artifact-discard-race', source_format: 'txt', selected_languages: ['en'],
    status: 'source_ready', current_step: 2, metadata: {}, languages: [], artifacts: [],
    created_at: '2026-07-15T10:00:00Z', updated_at: '2026-07-15T10:00:00Z',
  }
  let currentTask = stoppedTask
  let cancelPayload: unknown = null
  await page.route(`**/api/projects/${project.id}?**`, async (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ...projectSnapshot, announcement_tasks: [currentTask] }),
    })
  })
  await page.route(`**/api/announcement-tasks/${stoppedTask.id}/cancel`, async (route) => {
    cancelPayload = route.request().postDataJSON()
    currentTask = { ...stoppedTask, status: 'running', current_step: 7, updated_at: '2026-07-15T10:01:00Z' }
    await route.fulfill({
      status: 409,
      contentType: 'application/json',
      body: JSON.stringify({
        detail: {
          code: 'announcement_task_status_conflict',
          task_id: stoppedTask.id,
          status: 'running',
        },
      }),
    })
  })

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.locator('.proj-head .row-actions').getByRole('button', { name: '新公告任务', exact: true }).click()
  await page.getByRole('alertdialog').getByRole('button', { name: '放弃并新建' }).click()

  await expect(page.locator('.announcement-current-task')).toContainText(stoppedTask.title)
  await expect(page.locator('.announcement-current-task')).toContainText('后台翻译中')
  expect(cancelPayload).toEqual({ expected_statuses: ['source_ready'] })
})

test('a stopped task appearing after discard re-enters the lifecycle decision with a valid action scope', async ({ page, request }) => {
  const projectName = `E2E Announcement Late Stopped ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'announcement', description: 'Late stopped task decision coverage.' },
  }).then((response) => response.json())
  const projectSnapshot = await request.get(`${baseURL}/api/projects/${project.id}`).then((response) => response.json())
  const originalTask = {
    id: 'announcement-discard-original', project_id: project.id, title: '原未完成公告',
    source_artifact_id: 'artifact-discard-original', source_format: 'txt', selected_languages: ['en'],
    status: 'source_ready', current_step: 2, metadata: {}, languages: [], artifacts: [],
    created_at: '2026-07-15T10:00:00Z', updated_at: '2026-07-15T10:00:00Z',
  }
  const lateTask = {
    id: 'announcement-discard-late', project_id: project.id, title: '新出现的未完成公告',
    source_artifact_id: 'artifact-discard-late', source_format: 'txt', selected_languages: ['ja'],
    status: 'source_ready', current_step: 2, metadata: {}, languages: [], artifacts: [],
    created_at: '2026-07-15T10:01:00Z', updated_at: '2026-07-15T10:01:00Z',
  }
  const inspectedLateTask = { ...lateTask, status: 'constraints_ready', current_step: 3, updated_at: '2026-07-15T10:02:00Z' }
  let visibleTasks = [originalTask]
  let lateTaskActionRequested = false
  await page.route(`**/api/projects/${project.id}?**`, async (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ...projectSnapshot, announcement_tasks: visibleTasks }),
    })
  })
  await page.route(`**/api/announcement-tasks/${originalTask.id}/cancel`, async (route) => {
    visibleTasks = [lateTask]
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ task: { ...originalTask, status: 'canceled' } }),
    })
  })
  await page.route(`**/api/announcement-tasks/${lateTask.id}/inspect-constraints`, async (route) => {
    lateTaskActionRequested = true
    visibleTasks = [inspectedLateTask]
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ task: inspectedLateTask, summary: { detected_languages: ['ja'] } }),
    })
  })

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.locator('.proj-head .row-actions').getByRole('button', { name: '新公告任务', exact: true }).click()
  await page.getByRole('alertdialog').getByRole('button', { name: '放弃并新建' }).click()

  const secondDecision = page.getByRole('alertdialog')
  await expect(secondDecision).toContainText('已有未完成公告任务')
  await secondDecision.getByRole('button', { name: '继续当前任务' }).click()
  await expect(page.locator('.announcement-current-task')).toContainText(lateTask.title)

  await page.getByRole('button', { name: '识别语言与约束' }).click()
  await expect.poll(() => lateTaskActionRequested).toBe(true)
  await expect(page.locator('.panel-title', { hasText: '目标语言' })).toBeVisible()
  await expect(page.locator('.inline-status')).not.toContainText('正在执行公告任务')
})

test('late T1 announcement upload cannot change T2 status or selected assets', async ({ page, request }) => {
  const projectName = `E2E Announcement Upload Scope ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'announcement', description: 'Upload session isolation.' },
  }).then((response) => response.json())
  const projectSnapshot = await request.get(`${baseURL}/api/projects/${project.id}`).then((response) => response.json())
  const t1 = {
    id: 'announcement-upload-t1', project_id: project.id, title: '上传任务 T1',
    source_artifact_id: 'artifact-upload-t1', source_format: 'txt', selected_languages: ['en'],
    status: 'source_ready', current_step: 2, metadata: {}, languages: [], artifacts: [],
    created_at: '2026-07-15T10:00:00Z', updated_at: '2026-07-15T10:00:00Z',
  }
  const t2 = {
    id: 'announcement-upload-t2', project_id: project.id, title: '上传任务 T2',
    source_artifact_id: 'artifact-upload-t2', source_format: 'txt', selected_languages: ['ja'],
    status: 'lookup_ready', current_step: 5, metadata: {}, languages: [], artifacts: [],
    created_at: '2026-07-15T10:01:00Z', updated_at: '2026-07-15T10:01:00Z',
  }
  const uploadedArtifact = {
    id: 'announcement-late-constraint', project_id: project.id, run_id: null,
    kind: 'language_table', label: 'late-constraint.xlsx', path: 'late-constraint.xlsx', size: 64,
    created_at: '2026-07-15T10:02:00Z', metadata: { original_filename: 'late-constraint.xlsx' },
  }
  let uploadRequested = false
  let releaseUpload!: () => void
  const uploadGate = new Promise<void>((resolve) => { releaseUpload = resolve })
  await page.route(`**/api/projects/${project.id}?**`, async (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ...projectSnapshot, artifacts: [uploadedArtifact], announcement_tasks: [t1, t2] }),
    })
  })
  await page.route(`**/api/projects/${project.id}/files?*`, async (route) => {
    uploadRequested = true
    await uploadGate
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(uploadedArtifact) })
  })

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.locator('.announcement-task-row', { hasText: t1.title }).getByRole('button', { name: '继续' }).click()
  await page.locator('.upload-box', { hasText: '上传完整语言表' }).locator('input[type=file]').setInputFiles({
    name: 'late-constraint.xlsx',
    mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    buffer: Buffer.from('late upload'),
  })
  await expect.poll(() => uploadRequested).toBe(true)

  await page.getByRole('button', { name: '返回项目概览' }).click()
  await page.locator('.announcement-task-row', { hasText: t2.title }).getByRole('button', { name: '继续' }).click()
  await expect(page.locator('.announcement-current-task')).toContainText(t2.title)
  await expect(page.locator('.inline-status')).toContainText('公告任务已就绪')

  const uploadResponse = page.waitForResponse((response) => response.url().includes(`/api/projects/${project.id}/files?`))
  releaseUpload()
  await uploadResponse
  await page.waitForTimeout(250)

  await expect(page.locator('.announcement-current-task')).toContainText(t2.title)
  await expect(page.locator('.panel-title', { hasText: '译文反查' })).toBeVisible()
  await expect(page.locator('.inline-status')).toContainText('公告任务已就绪')
})

test('late T1 polling cannot clear a running T2 action or replace its status', async ({ page, request }) => {
  const projectName = `E2E Announcement Poll Scope ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'announcement', description: 'Polling session isolation.' },
  }).then((response) => response.json())
  const projectSnapshot = await request.get(`${baseURL}/api/projects/${project.id}`).then((response) => response.json())
  const t1 = {
    id: 'announcement-poll-t1', project_id: project.id, title: '轮询任务 T1',
    source_artifact_id: 'artifact-poll-t1', source_format: 'txt', selected_languages: ['en'],
    status: 'running', current_step: 7, metadata: {}, languages: [], artifacts: [],
    created_at: '2026-07-15T10:00:00Z', updated_at: '2026-07-15T10:00:00Z',
  }
  const t1Finished = { ...t1, status: 'translated', current_step: 8, updated_at: '2026-07-15T10:02:00Z' }
  const t2 = {
    id: 'announcement-poll-t2', project_id: project.id, title: '轮询任务 T2',
    source_artifact_id: 'artifact-poll-t2', source_format: 'txt', selected_languages: ['ja'],
    status: 'source_ready', current_step: 2, metadata: {}, languages: [], artifacts: [],
    created_at: '2026-07-15T10:01:00Z', updated_at: '2026-07-15T10:01:00Z',
  }
  let delayNextProjectRead = false
  let pollStarted = false
  let releasePoll!: () => void
  const pollGate = new Promise<void>((resolve) => { releasePoll = resolve })
  let releaseT2!: () => void
  const t2Gate = new Promise<void>((resolve) => { releaseT2 = resolve })
  await page.route(`**/api/projects/${project.id}?**`, async (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    if (delayNextProjectRead) {
      delayNextProjectRead = false
      pollStarted = true
      await pollGate
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ...projectSnapshot, announcement_tasks: [t1Finished, t2] }),
      }).catch(() => undefined)
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ...projectSnapshot, announcement_tasks: [t1, t2] }),
    })
  })
  await page.route(`**/api/announcement-tasks/${t2.id}/inspect-constraints`, async (route) => {
    await t2Gate
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ task: { ...t2, status: 'constraints_ready', current_step: 3 }, summary: {} }),
    })
  })

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.locator('.announcement-task-row', { hasText: t1.title }).getByRole('button', { name: '继续' }).click()
  delayNextProjectRead = true
  await expect.poll(() => pollStarted, { timeout: 4500 }).toBe(true)

  await page.getByRole('button', { name: '返回项目概览' }).click()
  await page.locator('.announcement-task-row', { hasText: t2.title }).getByRole('button', { name: '继续' }).click()
  const inspectButton = page.getByRole('button', { name: '识别语言与约束' })
  await inspectButton.click()
  await expect(inspectButton).toBeDisabled()
  await expect(page.locator('.inline-status')).toContainText('正在执行公告任务')

  releasePoll()
  await page.waitForTimeout(300)

  await expect(page.locator('.announcement-current-task')).toContainText(t2.title)
  await expect(inspectButton).toBeDisabled()
  await expect(page.locator('.inline-status')).toContainText('正在执行公告任务')

  const t2Response = page.waitForResponse((response) => response.url().includes(`/api/announcement-tasks/${t2.id}/inspect-constraints`))
  releaseT2()
  await t2Response
})
