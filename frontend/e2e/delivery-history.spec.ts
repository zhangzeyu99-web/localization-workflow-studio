import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'

const baseURL = process.env.E2E_BASE_URL ?? `http://127.0.0.1:${process.env.LWS_E2E_FRONTEND_PORT ?? '15173'}`
test.use({ acceptDownloads: true })

async function createProject(request: APIRequestContext) {
  const response = await request.post(`${baseURL}/api/projects`, {
    data: { name: `E2E 交付版本 ${Date.now()}`, type: 'delivery-review', description: 'Synthetic delivery history acceptance.' },
  })
  expect(response.ok()).toBeTruthy()
  return response.json()
}

async function openDelivery(page: Page, projectName: string) {
  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.getByRole('button', { name: '交付', exact: true }).click()
}

function deliverable(runId: string, status: string, overrides: Record<string, unknown> = {}) {
  return {
    run_id: runId,
    translation_task_id: 'translation-task-identified',
    task_code: 'T', task_id: 'identified', task_label: 'T-identified', task_type: '翻译任务',
    language: 'EN', created_at: '2026-09-20T10:00:00Z', updated_at: '2026-09-20T10:00:00Z',
    status, processed_rows: 1, source_rows: 1, translated_rows: 1,
    input_label: '任务原文.xlsx', qa_status: status, qa_hard_errors: status === 'failed' ? 1 : 0,
    qa_soft_warnings: 0, files: {}, ...overrides,
  }
}

async function jsonOk(response: Awaited<ReturnType<APIRequestContext['post']>>) {
  expect(response.ok(), await response.text()).toBeTruthy()
  return response.json()
}

async function prepareQa(request: APIRequestContext, projectId: string, taskId: string, target: string, quick = false, sourceRunId?: string) {
  await jsonOk(await request.patch(`${baseURL}/api/settings`, { data: { provider: 'test-fake', model: 'test-fake-localization', api_key: '', batch_size: 1 } }))
  const buffer = execFileSync(process.env.LWS_E2E_PYTHON || 'python', ['-X', 'utf8', '-c', `
import io, sys
from openpyxl import Workbook
book = Workbook()
sheet = book.active
sheet.title = 'Language'
sheet.append(['ID', 'CN', 'EN'])
sheet.append(['row-1', '开始游戏', sys.argv[1]])
output = io.BytesIO()
book.save(output)
book.close()
sys.stdout.buffer.write(output.getvalue())
`, target])
  const artifact = await jsonOk(await request.post(`${baseURL}/api/projects/${projectId}/files?kind=final_workbook`, { multipart: {
    file: { name: `delivery-${target.replace(/\W/g, '')}.xlsx`, mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer },
  } }))
  const run = await jsonOk(await request.post(`${baseURL}/api/runs`, { data: {
    project_id: projectId, kind: 'qa', language: 'en', input_artifact_id: artifact.id,
    translation_task_id: taskId || null, task_origin: quick ? 'quick_task' : 'translation_run', source_run_id: sourceRunId || null,
  } }))
  await jsonOk(await request.post(`${baseURL}/api/runs/${run.id}/qa`))
  return jsonOk(await request.get(`${baseURL}/api/runs/${run.id}`))
}

async function generate(request: APIRequestContext, projectId: string, runId: string) {
  return jsonOk(await request.post(`${baseURL}/api/projects/${projectId}/delivery-package?run_id=${encodeURIComponent(runId)}`))
}

const digest = (buffer: Buffer) => createHash('sha256').update(buffer).digest('hex')

test('current failed result stays primary and older passed delivery is read-only history', async ({ page, request }) => {
  const project = await createProject(request)
  await jsonOk(await request.patch(`${baseURL}/api/projects/${project.id}/harness`, { data: { forbidden_translations: ['Forbidden Brand'] } }))
  const failed = await prepareQa(request, project.id, 'translation-task-identified', 'Forbidden Brand')
  expect(failed.status).toBe('failed')
  await page.route(`**/api/projects/${project.id}/deliverables`, (route) => route.fulfill({ json: {
    project_id: project.id,
    deliverables: [
      deliverable(failed.id, 'failed', { created_at: '2026-09-20T11:00:00Z', updated_at: '2026-09-20T11:00:00Z' }),
      deliverable('previous-passed', 'passed', { files: { final: { kind: 'final', filename: 'previous.xlsx', path: '', download_url: '/previous.xlsx' } } }),
    ],
  } }))
  await page.route(`**/api/projects/${project.id}/delivery-history`, (route) => route.fulfill({ json: {
    project_id: project.id,
    current_tasks: [{ task_id: 'translation-task-identified', task_kind: 'translation', language: 'EN', run_id: failed.id, status: 'failed', qa_status: 'failed', qa_hard_errors: 1, input_label: '任务原文.xlsx', current_version_id: null, can_generate: false }],
    versions: [{ version_id: 'previous-version', task_id: 'translation-task-identified', task_kind: 'translation', language: 'EN', run_id: 'previous-passed', generated_at: '2026-09-20T10:00:00Z', qa_snapshot: { status: 'passed', hard_errors: 0, soft_warnings: 0 }, files: [{ kind: 'final', filename: 'previous.xlsx', path: '', download_url: '/previous.xlsx' }], is_current: false, history_complete: true }],
  } }))
  await openDelivery(page, project.name)
  const current = page.getByTestId('delivery-current')
  await expect(current).toContainText('当前任务结果')
  await expect(current).toContainText('QA 未通过')
  await expect(current.getByRole('button', { name: '处理当前任务' })).toBeVisible()
  await expect(current.getByRole('link', { name: '下载最终译文' })).toHaveCount(0)
  const history = page.getByTestId('delivery-history')
  await expect(history).not.toHaveAttribute('open', '')
  await history.locator('summary').click()
  await expect(history).toContainText('上一可用版')
  await expect(history.getByRole('link', { name: '下载最终译文' })).toBeVisible()
  await expect(history.getByRole('button')).toHaveCount(0)
  // 真实 App + API 失败 Run，历史响应为明确的展示契约 fixture；不声称已交付任务可以续跑。
  const output = path.resolve('..', 'output', 'process-review-2026-09-20', 'bc-acceptance')
  fs.mkdirSync(output, { recursive: true })
  for (const width of [1280, 1024]) {
    await page.setViewportSize({ width, height: width === 1280 ? 900 : 768 })
    if (await history.getAttribute('open') !== null) await history.locator('summary').click()
    await current.scrollIntoViewIfNeeded()
    const metrics = await page.evaluate(() => ({ width: innerWidth, documentWidth: document.documentElement.scrollWidth, mainOverflow: document.querySelector('.main')!.scrollWidth - document.querySelector('.main')!.clientWidth }))
    expect(metrics.documentWidth).toBeLessThanOrEqual(metrics.width)
    expect(metrics.mainOverflow).toBeLessThanOrEqual(1)
    await expect(current.getByRole('button', { name: '处理当前任务' })).toBeEnabled()
    await expect(current.getByRole('button', { name: '处理当前任务' })).toBeInViewport()
    await page.screenshot({ path: path.join(output, `C-current-failed-${width}.png`), fullPage: true })
    await history.locator('summary').click()
    await history.locator('.delivery-line').first().scrollIntoViewIfNeeded()
    await expect(history.getByText('上一可用版', { exact: true })).toBeInViewport()
    await page.screenshot({ path: path.join(output, `C-history-expanded-${width}.png`), fullPage: true })
  }
})

test('real formal delivery regeneration preserves its old download and history cannot restore a task', async ({ page, request }) => {
  const project = await createProject(request)
  const run = await prepareQa(request, project.id, `translation-task-${project.id}`, 'Start Game')
  expect(run.status).toBe('passed')
  const first = await generate(request, project.id, run.id)
  const oldFile = first.files.find((file: any) => file.kind === 'final')
  const oldBytes = await (await request.get(`${baseURL}${oldFile.download_url}`)).body()
  await openDelivery(page, project.name)
  await expect(page.getByTestId('delivery-current')).toContainText('QA 已通过')
  await page.getByRole('button', { name: '重新生成交付', exact: true }).click()
  const history = page.getByTestId('delivery-history')
  await expect(history).toBeVisible()
  await expect(history).not.toHaveAttribute('open', '')
  const writes: string[] = []
  page.on('request', (request) => { if (['POST', 'PATCH', 'DELETE'].includes(request.method())) writes.push(request.url()) })
  await history.locator('summary').click()
  await expect(history.getByRole('link', { name: '下载最终译文' })).toHaveAttribute('href', oldFile.download_url)
  const downloadEvent = page.waitForEvent('download')
  await history.getByRole('link', { name: '下载最终译文' }).click()
  expect((await downloadEvent).suggestedFilename()).toBe(oldFile.filename)
  await expect(history).toBeVisible()
  await expect(history.getByRole('button')).toHaveCount(0)
  expect(digest(await (await request.get(`${baseURL}${oldFile.download_url}`)).body())).toBe(digest(oldBytes))
  expect(writes).toEqual([])
  await page.locator('main').getByRole('button', { name: '新翻译任务', exact: true }).click()
  await expect(page.getByRole('heading', { name: '新翻译任务', exact: true })).toBeVisible()
  await expect(page.getByTestId('confirm-modal')).toHaveCount(0)
  await page.getByTestId('step-menu-toggle').click()
  await page.getByTestId('step-4').click()
  await expect(page.locator('.step-panel.active label.asset-select select')).toHaveValue('')
  await expect(page.locator('.workflow-file-link')).toHaveCount(0)
})

test('delivery regeneration remains clickable while same-project history revalidates', async ({ page, request }) => {
  const project = await createProject(request)
  const taskId = `translation-task-${project.id}`
  const run = await prepareQa(request, project.id, taskId, 'Start Game')
  expect(run.status).toBe('passed')
  await generate(request, project.id, run.id)

  let releaseDeliverables!: () => void
  const heldDeliverables = new Promise<void>((resolve) => { releaseDeliverables = resolve })
  let deliverablesReady!: () => void
  const deliverablesFetched = new Promise<void>((resolve) => { deliverablesReady = resolve })
  let holdFirstDeliverables = true
  await page.route(`**/api/projects/${project.id}/deliverables`, async (route) => {
    if (!holdFirstDeliverables) { await route.continue(); return }
    holdFirstDeliverables = false
    const response = await route.fetch()
    deliverablesReady()
    await heldDeliverables
    await route.fulfill({ response }).catch(() => {})
  })

  let revalidate = false
  let releaseHistory!: () => void
  const heldHistory = new Promise<void>((resolve) => { releaseHistory = resolve })
  let historyStarted!: () => void
  const historyRevalidating = new Promise<void>((resolve) => { historyStarted = resolve })
  await page.route(`**/api/projects/${project.id}/delivery-history`, async (route) => {
    if (revalidate) { historyStarted(); await heldHistory }
    await route.continue().catch(() => {})
  })

  const generatedRunIds: string[] = []
  page.on('request', (request) => {
    const url = new URL(request.url())
    if (request.method() === 'POST' && url.pathname === `/api/projects/${project.id}/delivery-package`) generatedRunIds.push(url.searchParams.get('run_id') || '')
  })
  try {
    await openDelivery(page, project.name)
    await deliverablesFetched
    const button = page.getByTestId(`delivery-generate-${run.id}`)
    await expect(button).toHaveText('重新生成交付')
    await expect(button).toBeEnabled()
    await button.hover()
    await page.mouse.down()
    // 在按下与抬起之间让旧接口回包触发后台重读，避免依赖随机请求速度。
    revalidate = true
    releaseDeliverables()
    await historyRevalidating
    await expect(button).toBeEnabled()
    const generatedResponse = page.waitForResponse((response) => response.request().method() === 'POST'
      && new URL(response.url()).pathname === `/api/projects/${project.id}/delivery-package`
      && new URL(response.url()).searchParams.get('run_id') === run.id)
    await page.mouse.up()
    const response = await generatedResponse
    expect(response.ok()).toBeTruthy()
    expect((await response.json()).deliverable).toMatchObject({ run_id: run.id, translation_task_id: taskId })
    expect(generatedRunIds).toEqual([run.id])
    releaseHistory()
    await expect(button).toBeEnabled()
    const history = await jsonOk(await request.get(`${baseURL}/api/projects/${project.id}/delivery-history`))
    expect(history.current_tasks[0]).toMatchObject({ task_id: taskId, run_id: run.id })
    expect(history.versions.filter((version: any) => version.task_id === taskId && version.run_id === run.id)).toHaveLength(2)
  } finally {
    try {
      await page.mouse.move(0, 0)
      await page.mouse.up()
    } finally {
      releaseDeliverables()
      releaseHistory()
    }
  }
})

test('real delivered quick history keeps the latest failed result read-only above its previous versions', async ({ page, request }) => {
  const project = await createProject(request)
  const taskId = `quick-task-${project.id}`
  const oldRun = await prepareQa(request, project.id, taskId, 'Start Game', true)
  await jsonOk(await request.patch(`${baseURL}/api/projects/${project.id}/harness`, { data: { forbidden_translations: ['Forbidden Brand'] } }))
  const failed = await prepareQa(request, project.id, taskId, 'Forbidden Brand', true, oldRun.id)
  expect(failed.status).toBe('failed')
  const first = await generate(request, project.id, oldRun.id)
  const firstFile = first.files.find((file: any) => file.kind === 'final')
  const firstDigest = digest(await (await request.get(`${baseURL}${firstFile.download_url}`)).body())
  await generate(request, project.id, oldRun.id)
  await openDelivery(page, project.name)
  const current = page.getByTestId('delivery-current')
  await expect(current.locator('.delivery-line')).toHaveCount(1)
  await expect(page.getByTestId(`delivery-current-${failed.id}`)).toContainText('QA 未通过')
  await expect(current.getByRole('link')).toHaveCount(0)
  await expect(current).toContainText('已结束')
  await expect(current.getByRole('button', { name: '处理当前任务' })).toHaveCount(0)
  const history = page.getByTestId('delivery-history')
  await expect(history).not.toHaveAttribute('open', '')
  await history.locator('summary').click()
  await expect(history.locator('.delivery-line')).toHaveCount(2)
  await expect(history.getByText('上一可用版', { exact: true })).toHaveCount(1)
  const versions = await jsonOk(await request.get(`${baseURL}/api/projects/${project.id}/delivery-history`))
  expect(versions.current_tasks[0].run_id).toBe(failed.id)
  expect(versions.current_tasks[0].task_state).toBe('delivered')
  expect(versions.versions.every((version: any) => version.qa_snapshot.status === 'passed')).toBeTruthy()
  expect((await request.get(`${baseURL}${firstFile.download_url}`)).ok()).toBeTruthy()
  expect(digest(await (await request.get(`${baseURL}${firstFile.download_url}`)).body())).toBe(firstDigest)
  await expect(history.getByRole('button')).toHaveCount(0)
})

test('real open quick task processing repairs its latest failed run before delivery', async ({ page, request }) => {
  const project = await createProject(request)
  const taskId = `quick-task-${project.id}`
  const oldRun = await prepareQa(request, project.id, taskId, 'Start Game', true)
  await jsonOk(await request.patch(`${baseURL}/api/projects/${project.id}/harness`, { data: { forbidden_translations: ['Forbidden Brand'] } }))
  const failed = await prepareQa(request, project.id, taskId, 'Forbidden Brand', true, oldRun.id)
  expect(failed.status).toBe('failed')
  await openDelivery(page, project.name)
  await page.getByTestId(`delivery-current-${failed.id}`).getByRole('button', { name: '处理当前任务' }).click()
  await expect(page.locator('.view-tab.active')).toContainText('校对')
  await expect(page.getByTestId('qa-outcome-panel')).toContainText('QA 未通过')
  await page.getByTestId('failed-row-editor').locator('summary').click()
  for (const input of await page.locator('[data-testid^="manual-fix-input-"]').all()) await input.fill('Start Game')
  await expect(page.getByTestId('manual-fix-rerun')).toBeEnabled()
  const repairedResponse = page.waitForResponse((response) => response.request().method() === 'POST'
    && new URL(response.url()).pathname === `/api/runs/${failed.id}/manual-fixes/start`)
  await page.getByTestId('manual-fix-rerun').click()
  const response = await repairedResponse
  expect(response.ok()).toBeTruthy()
  const repaired = await response.json()
  expect(repaired.manual_fixes).toHaveLength(1)
  expect(repaired.qa_run.metadata.translation_task_id).toBe(taskId)
  await expect.poll(async () => (await jsonOk(await request.get(`${baseURL}/api/runs/${repaired.qa_run.id}`))).status).toBe('passed')
  await expect(page.getByTestId('qa-outcome-panel')).toContainText('QA 已通过')
  await page.getByRole('button', { name: '交付', exact: true }).click()
  await expect(page.getByTestId(`delivery-current-${repaired.qa_run.id}`)).toContainText('QA 已通过')
})

test('real forced announcement delivery keeps current QA downloads and immutable historical packages', async ({ page, request }) => {
  const project = await createProject(request)
  const task = await jsonOk(await request.post(`${baseURL}/api/projects/${project.id}/announcement-tasks`, { data: {
    title: '公告交付版本测试', text: '英雄奖励 {0}', languages: ['en'],
  } }))
  const action = (name: string, data: Record<string, unknown> = {}) => request.post(`${baseURL}/api/announcement-tasks/${task.id}/${name}`, { data: { languages: ['en'], ai_supplement: false, ...data } }).then(jsonOk)
  await action('inspect-constraints', { confirm_languages: true })
  await action('import-terms', { terms: [{ source: '英雄', translations: { en: '英雄' } }] })
  await action('lookup-translations')
  const prepared = await action('prepare')
  const response = await jsonOk(await request.post(`${baseURL}/api/projects/${project.id}/files?kind=asset`, { multipart: {
    file: { name: 'synthetic-announcement-response.jsonl', mimeType: 'application/jsonl', buffer: Buffer.from(prepared.task.metadata.segments.map((segment: any) => JSON.stringify({ para_id: segment.id, translation: '英雄奖励 {0}' })).join('\n') + '\n', 'utf8') },
  } }))
  await action('import-ai', { response_artifact_ids: [response.id] })
  const applied = await action('apply')
  expect(applied.summary.hard_blockers).toBeGreaterThan(0)
  const first = await action('deliver', { date_stamp: '20260921', force: true })
  expect(first.summary.forced).toBe(true)
  let historyData = await jsonOk(await request.get(`${baseURL}/api/projects/${project.id}/delivery-history`))
  const firstVersion = historyData.versions[0]
  const firstUrl = firstVersion.files[0].download_url
  const firstDigest = digest(await (await request.get(`${baseURL}${firstUrl}`)).body())
  await action('deliver', { date_stamp: '20260921', force: true })
  historyData = await jsonOk(await request.get(`${baseURL}/api/projects/${project.id}/delivery-history`))
  expect(historyData.versions).toHaveLength(2)
  expect(historyData.versions.every((version: any) => version.qa_snapshot.status === 'failed')).toBeTruthy()
  await openDelivery(page, project.name)
  const current = page.getByTestId('delivery-current')
  await expect(current).toContainText('QA 未通过')
  await expect(current.getByRole('link', { name: '下载交付包' })).toBeVisible()
  await expect(current.getByRole('link', { name: '下载 QA 摘要' })).toBeVisible()
  await expect(current.getByRole('link', { name: /下载成品/ })).toBeVisible()
  await expect(current.getByTestId('delivery-missing-qa-summary')).toHaveCount(0)
  for (const link of await current.getByRole('link').all()) {
    expect((await request.get(`${baseURL}${await link.getAttribute('href')}`)).ok()).toBeTruthy()
  }
  const history = page.getByTestId('delivery-history')
  await history.locator('summary').click()
  await expect(history.getByRole('link')).toHaveCount(1)
  await expect(history.getByRole('link', { name: '下载交付包' })).toHaveAttribute('href', firstUrl)
  await expect(history.getByRole('button')).toHaveCount(0)
  expect(digest(await (await request.get(`${baseURL}${firstUrl}`)).body())).toBe(firstDigest)
})

test('real legacy delivery without a task id remains read-only history', async ({ page, request }) => {
  const project = await createProject(request)
  const run = await prepareQa(request, project.id, '', 'Start Game')
  const delivery = await generate(request, project.id, run.id)
  await openDelivery(page, project.name)
  await expect(page.getByTestId('delivery-current').locator('.delivery-line')).toHaveCount(0)
  const history = page.getByTestId('delivery-history')
  await expect(history).not.toHaveAttribute('open', '')
  await history.locator('summary').click()
  await expect(history).toContainText('历史信息不完整')
  await expect(history).toContainText('无任务 ID')
  await expect(history.getByRole('button')).toHaveCount(0)
  await expect(history.getByRole('link', { name: '下载最终译文' })).toHaveAttribute('href', delivery.files.find((file: any) => file.kind === 'final').download_url)
})

test('real partial merged delivery names missing languages and historical partial is not a complete available version', async ({ page, request }) => {
  const project = await createProject(request)
  const taskId = `translation-task-${project.id}`
  const run = await prepareQa(request, project.id, taskId, 'Start Game')
  const merge = () => request.post(`${baseURL}/api/projects/${project.id}/delivery-package/merged`, { data: {
    input_artifact_id: run.metadata.input_artifact_id, translation_task_id: taskId, languages: ['en', 'ko'],
  } }).then(jsonOk)
  const first = await merge()
  expect(first.skipped_languages).toContain('KR')
  await merge()
  await openDelivery(page, project.name)
  const merged = page.getByTestId('delivery-current').locator('.delivery-line').filter({ hasText: '多语言合并' })
  await expect(merged).toContainText('部分交付')
  await expect(merged).toContainText('未交付语言：KR')
  await expect(merged).toContainText('已结束')
  await expect(merged.getByRole('button', { name: '处理当前任务' })).toHaveCount(0)
  const history = page.getByTestId('delivery-history')
  await history.locator('summary').click()
  await expect(history).toContainText('部分交付')
  await expect(history.getByText('上一可用版', { exact: true })).toHaveCount(0)
})

test('late history response cannot cross projects and returning starts collapsed', async ({ page, request }) => {
  const first = await createProject(request)
  const second = await createProject(request)
  let release!: () => void
  const delayed = new Promise<void>((resolve) => { release = resolve })
  let started!: () => void
  const requested = new Promise<void>((resolve) => { started = resolve })
  let firstRequest = true
  const snapshot = (projectId: string, label: string) => ({ project_id: projectId, current_tasks: [], versions: [{
    version_id: label, task_id: null, task_kind: 'translation', language: label, run_id: label, generated_at: '',
    qa_snapshot: { status: 'unknown', hard_errors: null, soft_warnings: null }, files: [], is_current: false, history_complete: false,
  }] })
  await page.route(`**/api/projects/${first.id}/delivery-history`, async (route) => {
    if (firstRequest) { firstRequest = false; started(); await delayed }
    await route.fulfill({ json: snapshot(first.id, 'PROJECT-A-HISTORY') }).catch(() => {})
  })
  await page.route(`**/api/projects/${second.id}/delivery-history`, (route) => route.fulfill({ json: snapshot(second.id, 'PROJECT-B-HISTORY') }))
  await openDelivery(page, first.name)
  await requested
  await page.getByRole('button', { name: second.name }).click()
  await page.getByRole('button', { name: '交付', exact: true }).click()
  const history = page.getByTestId('delivery-history')
  await history.locator('summary').click()
  await expect(history).toContainText('PROJECT-B-HISTORY')
  release()
  await expect(history).not.toContainText('PROJECT-A-HISTORY')
  await page.getByRole('button', { name: first.name }).click()
  await expect(history).not.toHaveAttribute('open', '')
  await history.locator('summary').click()
  await expect(history).toContainText('PROJECT-A-HISTORY')
  await expect(history).toContainText('生成时间未知')
  await expect(history).toContainText('QA 尚无完整结论')
})

test('closed tasks cannot revive, TXT needs no workbook summary, and missing files are not a previous available version', async ({ page, request }) => {
  const project = await createProject(request)
  const task = { task_id: 'task-closed', task_kind: 'quick', language: 'EN', run_id: 'closed', status: 'failed', qa_status: 'failed', qa_hard_errors: 1, input_label: '已放弃任务', current_version_id: null, can_generate: false, task_state: 'abandoned' }
  await page.route(`**/api/projects/${project.id}/delivery-history`, (route) => route.fulfill({ json: {
    project_id: project.id,
    current_tasks: [task, { ...task, task_id: 'task-txt', task_state: '', run_id: 'txt', input_label: '纯文本任务', current_version_id: 'txt-version', can_generate: true }],
    versions: [
      { version_id: 'txt-version', task_id: 'task-txt', task_kind: 'quick', language: 'EN', run_id: 'txt', generated_at: '2026-09-21T01:00:00Z', qa_snapshot: { status: 'failed', hard_errors: 1, soft_warnings: 0 }, files: [{ kind: 'final', filename: 'result.txt', path: '', download_url: '/result.txt' }], is_current: true, history_complete: true },
      { version_id: 'missing-previous', task_id: 'task-txt', task_kind: 'quick', language: 'EN', run_id: 'old-txt', generated_at: '2026-09-20T01:00:00Z', qa_snapshot: { status: 'passed', hard_errors: 0, soft_warnings: 0 }, files: [{ kind: 'final', filename: 'missing.txt', path: '', download_url: '', available: false }, { kind: 'qa_summary', filename: 'summary.xlsx', path: '', download_url: '/summary.xlsx', available: true }], is_current: false, history_complete: true, available: false },
    ],
  } }))
  await openDelivery(page, project.name)
  const closed = page.getByTestId('delivery-current-closed')
  await expect(closed).toContainText('已结束')
  await expect(closed.getByRole('button')).toHaveCount(0)
  await expect(page.getByTestId('delivery-current-txt').getByTestId('delivery-missing-qa-summary')).toHaveCount(0)
  const history = page.getByTestId('delivery-history')
  await history.locator('summary').click()
  await expect(history).toContainText('部分文件已缺失')
  await expect(history.getByText('上一可用版', { exact: true })).toHaveCount(0)
  await expect(history.getByRole('link', { name: '下载最终译文' })).toHaveCount(0)
  const missingCurrentRun = await page.evaluate(async () => {
    const { deliveryProcessingRun } = await import('/src/domain/deliveries.ts')
    return deliveryProcessingRun({ id: 'project-scope', runs: [{
      id: 'older-kr', project_id: 'project-scope', language: 'ko', status: 'failed', metadata: { translation_task_id: 'same-task' },
    }] }, { task_id: 'same-task', task_kind: 'merged', language: 'EN', run_id: 'current-en-not-yet-synced' })?.id || null
  })
  expect(missingCurrentRun).toBeNull()
})
