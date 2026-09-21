import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'

const baseURL = process.env.E2E_BASE_URL ?? `http://127.0.0.1:${process.env.LWS_E2E_FRONTEND_PORT ?? '15173'}`

async function createTermsTask(request: APIRequestContext, withTerm = true) {
  const projectResponse = await request.post(`${baseURL}/api/projects`, {
    data: { name: `E2E 公告术语确认 ${Date.now()} ${Math.random().toString(16).slice(2, 8)}`, type: 'announcement-review' },
  })
  expect(projectResponse.ok()).toBeTruthy()
  const project = await projectResponse.json()
  if (withTerm) {
    const termResponse = await request.post(`${baseURL}/api/projects/${project.id}/glossary`, {
      data: { term_key: 'T1', source: '秘境', target: 'Trial Realm', language: 'en', source_type: 'manual', confirmed: true },
    })
    expect(termResponse.ok()).toBeTruthy()
  }
  const created = await request.post(`${baseURL}/api/projects/${project.id}/announcement-tasks`, {
    data: { title: '公告术语确认测试', text: '本次更新开放秘境玩法。', languages: ['en'], include_project_archive: true },
  })
  expect(created.ok()).toBeTruthy()
  const task = await created.json()
  const inspected = await request.post(`${baseURL}/api/announcement-tasks/${task.id}/inspect-constraints`, {
    data: { languages: ['en'], confirm_languages: true, ai_supplement: false },
  })
  expect(inspected.ok()).toBeTruthy()
  return { projectId: project.id as string, taskId: task.id as string }
}

async function taskProject(request: APIRequestContext, projectId: string) {
  const response = await request.get(`${baseURL}/api/projects/${projectId}?include_archives=false`)
  expect(response.ok()).toBeTruthy()
  return response.json()
}

async function mountWorkflow(page: Page, project: any, taskId: string, reload = false) {
  if (reload) await page.reload()
  else await page.goto(baseURL)
  await page.evaluate(async ({ initialProject, initialTaskId }) => {
    const React = await import('/@id/react')
    const ReactDOMClient = await import('/@id/react-dom/client')
    const { AnnouncementWizard } = await import('/src/components/announcement/AnnouncementWorkflow.tsx')
    const createElement = React.createElement || React.default.createElement
    const useState = React.useState || React.default.useState
    const createRoot = ReactDOMClient.createRoot || ReactDOMClient.default.createRoot
    const host = document.createElement('div')
    document.body.replaceChildren(host)

    function Harness() {
      const [project, setProject] = useState(initialProject)
      const [taskId, setTaskId] = useState(initialTaskId)
      const [busy, setBusy] = useState(false)
      const [status, setStatus] = useState('准备就绪')
      ;(window as any).__termsReview = {
        replaceProject: (next: any, nextTaskId = taskId) => {
          if (next.id !== project.id || nextTaskId !== taskId) setBusy(false)
          setProject(next)
          setTaskId(nextTaskId)
        },
        patchTask: (patch: any) => setProject((current: any) => ({
          ...current,
          announcement_tasks: current.announcement_tasks.map((task: any) => task.id === taskId ? { ...task, ...patch } : task),
        })),
      }
      return createElement(AnnouncementWizard, {
        project, busy, status, jobQueues: null, settings: null,
        selectedLanguage: 'en', setSelectedLanguage: () => undefined,
        assetArtifacts: [], announcementText: '', setAnnouncementText: () => undefined,
        lookupResult: null, initialTaskId: taskId,
        onUploadAsset: async () => null, onUploadConstraint: async () => null,
        onUploadTermsFile: async (file: File) => {
          const body = new FormData()
          body.append('file', file)
          const response = await fetch(`/api/projects/${project.id}/files?kind=language_table`, { method: 'POST', body })
          return response.ok ? response.json() : null
        },
        onUploadResponse: async () => null, onCreateTask: async () => null,
        onTaskAction: async (id: string, endpoint: string, payload: any) => {
          setBusy(true)
          try {
            const response = await fetch(`/api/announcement-tasks/${id}/${endpoint}`, {
              method: 'POST', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ ...payload, ai_supplement: false }),
            })
            const result = await response.json()
            if (!response.ok) { setStatus(String(result.detail || '保存失败')); return null }
            setProject((current: any) => current.id !== result.task.project_id ? current : {
              ...current,
              announcement_tasks: current.announcement_tasks.map((task: any) => task.id === result.task.id ? result.task : task),
            })
            return result
          } catch (error) {
            setStatus(String(error))
            return null
          } finally {
            setBusy(false)
          }
        },
        onLookup: () => undefined, onBeginAnnouncementCancelHold: () => undefined,
        onCancelAnnouncementHold: () => undefined, announcementCancelHoldTaskId: '',
        onBack: () => undefined, onStartNext: () => undefined, confirm: async () => true,
      })
    }
    createRoot(host).render(createElement(Harness))
  }, { initialProject: project, initialTaskId: taskId })
  await expect(page.locator('.announcement-wizard')).toBeVisible()
}

async function expectStep(page: Page, step: number) {
  await expect(page.locator('.announcement-wizard').getByTestId('step-menu-toggle')).toContainText(`步骤 ${step}/9`)
}

async function extractTerms(page: Page, taskId: string) {
  const response = page.waitForResponse((item) => item.url().endsWith(`/api/announcement-tasks/${taskId}/extract-terms`) && item.request().method() === 'POST')
  await page.getByRole('button', { name: /^(提取术语并 AI 复查|仅本地提取术语)$/ }).click()
  expect((await response).ok()).toBeTruthy()
}

function firstTarget(page: Page) {
  return page.locator('.announcement-terms-table tbody tr').first().locator('input').nth(2)
}

async function prepareExtracted(page: Page, request: APIRequestContext, withTerm = true) {
  const fixture = await createTermsTask(request, withTerm)
  await mountWorkflow(page, await taskProject(request, fixture.projectId), fixture.taskId)
  await expectStep(page, 4)
  await extractTerms(page, fixture.taskId)
  await expectStep(page, 4)
  return fixture
}

async function importTerms(request: APIRequestContext, taskId: string, target: string) {
  const response = await request.post(`${baseURL}/api/announcement-tasks/${taskId}/import-terms`, {
    data: { languages: ['en'], terms: [{ id: 'T1', source: '秘境', translations: { en: target } }] },
  })
  expect(response.ok()).toBeTruthy()
  return response.json()
}

function countImports(page: Page) {
  const counter = { value: 0 }
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().endsWith('/import-terms')) counter.value += 1
  })
  return counter
}

test('real extraction stays on Step 4 for explicit review', async ({ page, request }) => {
  const imports = countImports(page)
  const fixture = await createTermsTask(request)
  await mountWorkflow(page, await taskProject(request, fixture.projectId), fixture.taskId)
  await expectStep(page, 4)
  await extractTerms(page, fixture.taskId)
  await expectStep(page, 4)
  await expect(page.locator('.announcement-terms-table tbody tr')).toHaveCount(1)
  await mountWorkflow(page, await taskProject(request, fixture.projectId), fixture.taskId, true)
  await expectStep(page, 4)
  await page.getByRole('button', { name: '确认并继续', exact: true }).click()
  await expectStep(page, 5)
  expect(imports.value).toBe(0)
  await mountWorkflow(page, await taskProject(request, fixture.projectId), fixture.taskId, true)
  await expectStep(page, 5)
  expect(imports.value).toBe(0)
})

test('real imported terms stay on Step 4 and clean continuation does not save again', async ({ page, request }) => {
  const fixture = await createTermsTask(request)
  await mountWorkflow(page, await taskProject(request, fixture.projectId), fixture.taskId)
  await expectStep(page, 4)
  const imports = countImports(page)
  const workbook = execFileSync(process.env.LWS_E2E_PYTHON || 'python', ['-X', 'utf8', '-c', [
    'from io import BytesIO', 'from openpyxl import Workbook', 'import sys',
    'wb=Workbook()', 'ws=wb.active', 'ws.append(["ID","CN","EN"])',
    'ws.append(["T1","\\u79d8\\u5883","Imported Realm"])',
    'out=BytesIO()', 'wb.save(out)', 'wb.close()', 'sys.stdout.buffer.write(out.getvalue())',
  ].join('\n')])
  await page.locator('label.upload-box', { hasText: '上传已提取术语表' }).locator('input[type="file"]').setInputFiles({
    name: 'announcement-terms.xlsx', mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer: workbook,
  })
  await expect(firstTarget(page)).toHaveValue('Imported Realm')
  await expectStep(page, 4)
  expect(imports.value).toBe(1)
  await page.getByRole('button', { name: '确认并继续', exact: true }).click()
  await expectStep(page, 5)
  expect(imports.value).toBe(1)
})

test('dirty save and continue posts once, freezes editing, and advances only after success', async ({ page, request }) => {
  const fixture = await prepareExtracted(page, request)
  await firstTarget(page).fill('Edited Realm')
  const imports = countImports(page)
  let release = () => {}
  const gate = new Promise<void>((resolve) => { release = resolve })
  await page.route(`**/api/announcement-tasks/${fixture.taskId}/import-terms`, async (route) => {
    const response = await route.fetch()
    await gate
    await route.fulfill({ response })
  })
  const saving = page.getByRole('button', { name: '保存并继续', exact: true })
  await saving.evaluate((button: HTMLButtonElement) => { button.click(); button.click() })
  await expect.poll(() => imports.value).toBe(1)
  await expectStep(page, 4)
  for (const input of await page.locator('.announcement-terms-table input').all()) await expect(input).toBeDisabled()
  await expect(page.locator('.announcement-terms-table').getByRole('button', { name: '删除', exact: true })).toBeDisabled()
  await expect(saving).toBeDisabled()
  release()
  await expectStep(page, 5)
  expect(imports.value).toBe(1)
  const saved = await request.get(`${baseURL}/api/announcement-tasks/${fixture.taskId}`).then((response) => response.json())
  expect(saved.metadata.terms[0].translations.en).toBe('Edited Realm')
})

test('failed save and continue preserves the draft on Step 4 and retries successfully', async ({ page, request }) => {
  const fixture = await prepareExtracted(page, request)
  const imports = countImports(page)
  let attempts = 0
  await page.route(`**/api/announcement-tasks/${fixture.taskId}/import-terms`, async (route) => {
    attempts += 1
    if (attempts === 1) await route.fulfill({ status: 503, json: { detail: '本地保存失败，请重试' } })
    else await route.continue()
  })
  await firstTarget(page).fill('Retry Realm')
  await page.getByRole('button', { name: '保存并继续', exact: true }).click()
  await expect(page.locator('.inline-status')).toContainText('本地保存失败，请重试')
  await expectStep(page, 4)
  await expect(firstTarget(page)).toHaveValue('Retry Realm')
  await expect(firstTarget(page)).toBeEnabled()
  await page.getByRole('button', { name: '保存并继续', exact: true }).click()
  await expectStep(page, 5)
  expect(imports.value).toBe(2)
})

test('save edits updates the real terms but stays on Step 4 until confirmation', async ({ page, request }) => {
  const fixture = await prepareExtracted(page, request)
  const imports = countImports(page)
  await firstTarget(page).fill('Saved Realm')
  const saved = page.waitForResponse((response) => response.url().endsWith(`/api/announcement-tasks/${fixture.taskId}/import-terms`))
  await page.getByRole('button', { name: '保存编辑', exact: true }).click()
  expect((await saved).ok()).toBeTruthy()
  await expectStep(page, 4)
  await expect(firstTarget(page)).toHaveValue('Saved Realm')
  await page.getByRole('button', { name: '确认并继续', exact: true }).click()
  await expectStep(page, 5)
  expect(imports.value).toBe(1)
})

test('ordinary updated_at polling preserves draft text and the current step', async ({ page, request }) => {
  await prepareExtracted(page, request)
  await firstTarget(page).fill('Unsaved Draft Realm')
  await page.evaluate(() => (window as any).__termsReview.patchTask({ updated_at: '2099-09-20T00:00:01Z' }))
  await expectStep(page, 4)
  await expect(firstTarget(page)).toHaveValue('Unsaved Draft Realm')
  await expect(page.getByText('服务器术语结果已更新', { exact: false })).toHaveCount(0)
  await page.getByRole('button', { name: '保存并继续', exact: true }).click()
  await expectStep(page, 5)
  await page.evaluate(() => (window as any).__termsReview.patchTask({ updated_at: '2099-09-20T00:00:02Z' }))
  await expectStep(page, 5)
})

test('no extraction cannot continue but an extracted zero-result can continue without a save', async ({ page, request }) => {
  const fixture = await createTermsTask(request, false)
  await mountWorkflow(page, await taskProject(request, fixture.projectId), fixture.taskId)
  await expectStep(page, 4)
  const imports = countImports(page)
  await expect(page.getByRole('button', { name: '确认并继续', exact: true })).toBeDisabled()
  await extractTerms(page, fixture.taskId)
  await expectStep(page, 4)
  await expect(page.getByText('没有命中可确认术语', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '确认并继续', exact: true }).click()
  await expectStep(page, 5)
  expect(imports.value).toBe(0)
})

test('a new server terms version preserves the draft, blocks saving, and allows explicit reload', async ({ page, request }) => {
  const fixture = await prepareExtracted(page, request)
  const imports = countImports(page)
  await firstTarget(page).fill('Local Draft Realm')
  await importTerms(request, fixture.taskId, 'Server New Realm')
  const updated = await taskProject(request, fixture.projectId)
  await page.evaluate((project) => (window as any).__termsReview.replaceProject(project), updated)
  await expect(page.getByText('服务器术语结果已更新', { exact: false })).toBeVisible()
  await expect(firstTarget(page)).toHaveValue('Local Draft Realm')
  await expectStep(page, 4)
  await expect(page.getByRole('button', { name: '保存编辑', exact: true })).toBeDisabled()
  await expect(page.getByRole('button', { name: '保存并继续', exact: true })).toBeDisabled()
  expect(imports.value).toBe(0)
  await page.getByRole('button', { name: '放弃编辑并载入最新结果', exact: true }).click()
  await expect(firstTarget(page)).toHaveValue('Server New Realm')
  await expect(page.getByText('服务器术语结果已更新', { exact: false })).toHaveCount(0)
  await page.getByRole('button', { name: '确认并继续', exact: true }).click()
  await expectStep(page, 5)
  expect(imports.value).toBe(0)
})

test('same-task server lookup progress cannot leave Step 4 or discard an unsaved terms draft', async ({ page, request }) => {
  const fixture = await prepareExtracted(page, request)
  await firstTarget(page).fill('Unsaved Before Lookup')
  const lookup = await request.post(`${baseURL}/api/announcement-tasks/${fixture.taskId}/lookup-translations`, {
    data: { languages: ['en'], include_project_archive: true, ai_supplement: false },
  })
  expect(lookup.ok()).toBeTruthy()
  expect((await lookup.json()).task.current_step).toBe(6)
  await page.evaluate((project) => (window as any).__termsReview.replaceProject(project), await taskProject(request, fixture.projectId))
  await expectStep(page, 4)
  await expect(firstTarget(page)).toHaveValue('Unsaved Before Lookup')
  await expect(page.getByRole('button', { name: '保存并继续', exact: true })).toBeEnabled()
})

test('A to B to A switching rejects a late save from the previous A session', async ({ page, request }) => {
  const fixtureA = await prepareExtracted(page, request)
  const projectA = await taskProject(request, fixtureA.projectId)
  const fixtureB = await createTermsTask(request)
  await importTerms(request, fixtureB.taskId, 'Task B Realm')
  const projectB = await taskProject(request, fixtureB.projectId)
  let release = () => {}
  const gate = new Promise<void>((resolve) => { release = resolve })
  let started = false
  await page.route(`**/api/announcement-tasks/${fixtureA.taskId}/import-terms`, async (route) => {
    const response = await route.fetch()
    started = true
    await gate
    await route.fulfill({ response })
  })
  await firstTarget(page).fill('Old A Session Saved Result')
  await page.getByRole('button', { name: '保存并继续', exact: true }).click()
  await expect.poll(() => started).toBeTruthy()
  await page.evaluate(({ project, taskId }) => (window as any).__termsReview.replaceProject(project, taskId), { project: projectB, taskId: fixtureB.taskId })
  await expect(firstTarget(page)).toHaveValue('Task B Realm')
  await page.evaluate(({ project, taskId }) => (window as any).__termsReview.replaceProject(project, taskId), { project: projectA, taskId: fixtureA.taskId })
  await expect(firstTarget(page)).toHaveValue('Trial Realm')
  await firstTarget(page).fill('New A Session Unsaved Draft')
  const completed = page.waitForResponse((response) => response.url().endsWith(`/api/announcement-tasks/${fixtureA.taskId}/import-terms`))
  release()
  await completed
  await expect(firstTarget(page)).toBeEnabled()
  await expectStep(page, 4)
  await expect(firstTarget(page)).toHaveValue('New A Session Unsaved Draft')
})

for (const endpoint of ['extract-terms', 'import-terms']) {
  test(`late ${endpoint} response cannot move or overwrite another task`, async ({ page, request }) => {
    const fixtureA = await prepareExtracted(page, request)
    const fixtureB = await createTermsTask(request)
    await importTerms(request, fixtureB.taskId, 'Task B Realm')
    const projectB = await taskProject(request, fixtureB.projectId)
    let release = () => {}
    const gate = new Promise<void>((resolve) => { release = resolve })
    let started = false
    await page.route(`**/api/announcement-tasks/${fixtureA.taskId}/${endpoint}`, async (route) => {
      const response = await route.fetch()
      started = true
      await gate
      await route.fulfill({ response })
    })
    if (endpoint === 'import-terms') {
      await firstTarget(page).fill('Late Task A Realm')
      await page.getByRole('button', { name: '保存并继续', exact: true }).click()
    } else {
      await page.getByRole('button', { name: /^(提取术语并 AI 复查|仅本地提取术语)$/ }).click()
    }
    await expect.poll(() => started).toBeTruthy()
    await page.evaluate(({ project, taskId }) => (window as any).__termsReview.replaceProject(project, taskId), { project: projectB, taskId: fixtureB.taskId })
    await expectStep(page, 4)
    await expect(firstTarget(page)).toHaveValue('Task B Realm')
    const completed = page.waitForResponse((response) => response.url().endsWith(`/api/announcement-tasks/${fixtureA.taskId}/${endpoint}`))
    release()
    await completed
    await expect(firstTarget(page)).toBeEnabled()
    await expectStep(page, 4)
    await expect(firstTarget(page)).toHaveValue('Task B Realm')
    await expect(page.getByRole('button', { name: '确认并继续', exact: true })).toBeEnabled()
  })
}

test('full application reviews and saves announcement terms at 1280 and 1024 widths', async ({ page, request }) => {
  const fixture = await createTermsTask(request)
  const extracted = await request.post(`${baseURL}/api/announcement-tasks/${fixture.taskId}/extract-terms`, {
    data: { languages: ['en'], ai_supplement: false },
  })
  expect(extracted.ok()).toBeTruthy()
  const project = await taskProject(request, fixture.projectId)
  const task = project.announcement_tasks.find((item: any) => item.id === fixture.taskId)
  const output = path.resolve(process.cwd(), '../output/process-review-2026-09-20/announcement-terms-acceptance')
  fs.mkdirSync(output, { recursive: true })
  await page.goto(baseURL)
  await page.getByRole('button', { name: project.name }).click()
  await page.locator('.announcement-task-row', { hasText: task.title }).getByRole('button', { name: '继续', exact: true }).click()
  await expectStep(page, 4)
  await expect(firstTarget(page)).toHaveValue('Trial Realm')
  await expect(page.getByRole('button', { name: '确认并继续', exact: true })).toBeEnabled()

  async function capture(state: string) {
    for (const width of [1280, 1024]) {
      await page.setViewportSize({ width, height: width === 1280 ? 900 : 768 })
      await expect(page.locator('.announcement-panel')).toBeVisible()
      if (state !== '03-confirmed-lookup') {
        await page.locator('.announcement-terms-table').evaluate((table) => table.scrollIntoView({ block: 'center', inline: 'nearest' }))
        // 保留既有表格横向滚动；截图要求首行在垂直方向完整展示。
        const row = await page.locator('.announcement-terms-table tbody tr').first().boundingBox()
        expect(row).not.toBeNull()
        expect(row!.y).toBeGreaterThanOrEqual(0)
        expect(row!.y + row!.height).toBeLessThanOrEqual(page.viewportSize()!.height)
        await expect(page.getByRole('button', { name: /^(确认并继续|保存并继续)$/ })).toBeInViewport({ ratio: 1 })
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
      await page.screenshot({ path: path.join(output, `${state}-${width}.png`), fullPage: true })
    }
  }

  await capture('01-clean-review')
  await firstTarget(page).fill('Reviewed Realm')
  await expect(page.getByRole('button', { name: '保存并继续', exact: true })).toBeEnabled()
  await capture('02-unsaved-review')
  const saved = page.waitForResponse((response) => response.url().endsWith(`/api/announcement-tasks/${fixture.taskId}/import-terms`))
  await page.getByRole('button', { name: '保存并继续', exact: true }).click()
  expect((await saved).ok()).toBeTruthy()
  await expectStep(page, 5)
  await capture('03-confirmed-lookup')
  await page.reload()
  await expectStep(page, 5)
})

test('full application does not confirm a stale save when a newer real API terms version wins readback', async ({ page, request }) => {
  const fixture = await createTermsTask(request)
  const extracted = await request.post(`${baseURL}/api/announcement-tasks/${fixture.taskId}/extract-terms`, {
    data: { languages: ['en'], ai_supplement: false },
  })
  expect(extracted.ok()).toBeTruthy()
  const project = await taskProject(request, fixture.projectId)
  const task = project.announcement_tasks.find((item: any) => item.id === fixture.taskId)
  await page.goto(baseURL)
  await page.getByRole('button', { name: project.name }).click()
  await page.locator('.announcement-task-row', { hasText: task.title }).getByRole('button', { name: '继续', exact: true }).click()
  await expectStep(page, 4)
  await firstTarget(page).fill('Local Save A Draft')

  let release = () => {}
  const gate = new Promise<void>((resolve) => { release = resolve })
  let serverSavedA = false
  let readbacks = 0
  const imports = countImports(page)
  page.on('request', (request) => {
    if (request.method() === 'GET' && request.url().includes(`/api/projects/${fixture.projectId}?`)) readbacks += 1
  })
  await page.route(`**/api/announcement-tasks/${fixture.taskId}/import-terms`, async (route) => {
    const response = await route.fetch()
    expect(response.ok()).toBeTruthy()
    serverSavedA = true
    await gate
    await route.fulfill({ response })
  })
  await page.getByRole('button', { name: '保存并继续', exact: true }).click()
  await expect.poll(() => serverSavedA).toBeTruthy()
  const newer = await importTerms(request, fixture.taskId, 'Newer Server B Realm')
  expect(newer.task.metadata.terms[0].translations.en).toBe('Newer Server B Realm')
  release()
  await expect(page.getByRole('alert').filter({ hasText: '服务器术语结果已更新' })).toBeVisible()
  await expectStep(page, 4)
  await expect(firstTarget(page)).toHaveValue('Local Save A Draft')
  await expect(page.getByRole('button', { name: '保存并继续', exact: true })).toBeDisabled()
  expect(imports.value).toBe(1)
  expect(readbacks).toBe(1)
  await page.getByRole('button', { name: '放弃编辑并载入最新结果', exact: true }).click()
  await expect(firstTarget(page)).toHaveValue('Newer Server B Realm')
})
