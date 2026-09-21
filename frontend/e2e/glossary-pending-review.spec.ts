import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import path from 'node:path'

const baseURL = process.env.E2E_BASE_URL ?? `http://127.0.0.1:${process.env.LWS_E2E_FRONTEND_PORT ?? '15173'}`

async function setup(request: APIRequestContext, count = 1, commit = true) {
  const projectResponse = await request.post(`${baseURL}/api/projects`, { data: { name: `E2E 待复核 ${Date.now()} ${count}`, type: 'glossary-review' } })
  expect(projectResponse.ok()).toBeTruthy()
  const project = await projectResponse.json()
  for (let index = 0; index < count; index += 1) {
    const response = await request.post(`${baseURL}/api/projects/${project.id}/glossary`, {
      data: { term_key: `T-${String(index).padStart(3, '0')}`, source: `战力${index}`, target: `Power ${index}`, language: 'en' },
    })
    expect(response.ok()).toBeTruthy()
  }
  const csv = ['ID,CN,EN', ...Array.from({ length: count }, (_, index) => `T-${String(index).padStart(3, '0')},战力${index},Combat Power ${index}`)].join('\n')
  const upload = await request.post(`${baseURL}/api/projects/${project.id}/files?kind=term_base`, {
    multipart: { file: { name: 'pending-review.csv', mimeType: 'text/csv', buffer: Buffer.from(csv) } },
  })
  expect(upload.ok()).toBeTruthy()
  const artifact = await upload.json()
  let batchId = ''
  if (commit) {
    const analysis = await request.post(`${baseURL}/api/projects/${project.id}/glossary/import/analyze`, {
      data: { artifact_id: artifact.id, confirmed_glossary: true, mode: 'merge', override_protected: true },
    }).then((response) => response.json())
    expect(analysis.can_commit).toBe(true)
    const response = await request.post(`${baseURL}/api/projects/${project.id}/glossary/import/commit?compact=true`, { data: { token: analysis.token } })
    expect(response.ok()).toBeTruthy()
    batchId = (await response.json()).batch_id
  }
  return { project, artifact, batchId }
}

async function openGlossary(page: Page, projectName: string) {
  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.getByRole('button', { name: '术语表', exact: true }).click()
}

async function openPending(page: Page, projectName: string) {
  await openGlossary(page, projectName)
  await page.getByRole('button', { name: /^待复核/ }).click()
  await expect(page.getByRole('button', { name: '编辑并确认' }).first()).toBeVisible()
}

test('B real protected import opens pending review and confirms into the normal table', async ({ page, request }, testInfo) => {
  const { project, artifact } = await setup(request, 1, false)
  await openGlossary(page, project.name)
  await page.getByRole('button', { name: '导入 / 生成 / 导出', exact: true }).click()
  await page.getByRole('button', { name: '导入已确认术语', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '导入已确认术语' })
  if (await dialog.getByLabel('选择已有文件').isVisible()) await dialog.getByLabel('选择已有文件').selectOption(artifact.id)
  await dialog.getByTestId('archive-import-analyze').click()
  await expect(dialog.getByTestId('archive-import-commit')).toBeDisabled()
  await dialog.getByLabel('覆盖人工维护项并标记待复核；勾选后必须重新分析').click()
  await dialog.getByTestId('archive-import-analyze').click()
  await dialog.getByTestId('archive-import-commit').click()
  await expect(dialog).toContainText('本批次 1 条语言记录待复核')
  await dialog.getByRole('button', { name: '查看待复核术语' }).click()
  await expect(dialog).toBeHidden()
  await expect(page.getByRole('button', { name: /^待复核/ })).toHaveAttribute('aria-pressed', 'true')
  const section = page.getByTestId('pending-glossary-review')
  await expect(section).toContainText('Combat Power 0')
  for (const width of [1280, 1024]) {
    await page.setViewportSize({ width, height: 900 })
    await section.scrollIntoViewIfNeeded()
    await expect(section.getByRole('button', { name: '编辑并确认' })).toBeInViewport()
    await page.screenshot({ path: process.env.LWS_BC_ACCEPTANCE_DIR ? path.join(process.env.LWS_BC_ACCEPTANCE_DIR, `B-pending-${width}.png`) : testInfo.outputPath(`B-pending-${width}.png`), fullPage: true })
  }
  await section.getByRole('button', { name: '编辑并确认' }).click()
  await section.getByLabel('待复核译文', { exact: true }).fill('Combat Power Confirmed')
  for (const width of [1280, 1024]) {
    await page.setViewportSize({ width, height: 900 })
    await section.scrollIntoViewIfNeeded()
    await expect(section.getByRole('button', { name: '保存并确认' })).toBeInViewport()
    await page.screenshot({ path: process.env.LWS_BC_ACCEPTANCE_DIR ? path.join(process.env.LWS_BC_ACCEPTANCE_DIR, `B-editing-${width}.png`) : testInfo.outputPath(`B-editing-${width}.png`), fullPage: true })
  }
  await section.getByRole('button', { name: '保存并确认' }).click()
  await expect(section).toContainText('暂无待复核术语')
  await page.getByRole('button', { name: '已确认', exact: true }).click()
  await expect(page.getByText('Combat Power Confirmed', { exact: true })).toBeVisible()
  const terms = await request.get(`${baseURL}/api/projects/${project.id}/glossary`).then((response) => response.json())
  expect(terms).toHaveLength(1)
  expect(terms[0]).toMatchObject({ target: 'Combat Power Confirmed', confirmed: true, source_type: 'manual', review_status: 'approved' })
})

test('B stale revision is rejected without losing the draft and reload is explicit', async ({ page, request }) => {
  const { project } = await setup(request)
  await openPending(page, project.name)
  const section = page.getByTestId('pending-glossary-review')
  await section.getByRole('button', { name: '编辑并确认' }).click()
  await section.getByLabel('待复核译文', { exact: true }).fill('My unsaved draft')
  const pending = await request.get(`${baseURL}/api/projects/${project.id}/glossary/pending`).then((response) => response.json())
  const term = pending.items[0]
  const changed = await request.patch(`${baseURL}/api/projects/${project.id}/glossary/${term.id}`, { data: { target: 'Other operator confirmed', expected_revision: term.revision } })
  expect(changed.ok()).toBeTruthy()
  await section.getByRole('button', { name: '保存并确认' }).click()
  await expect(section.getByRole('alert')).toContainText('未覆盖新内容')
  await expect(section.getByLabel('待复核译文', { exact: true })).toHaveValue('My unsaved draft')
  await expect(section.getByRole('button', { name: '保存并确认' })).toBeDisabled()
  await section.getByRole('button', { name: '放弃编辑并载入最新结果' }).click()
  await expect(section).toContainText('暂无待复核术语')
  await page.getByRole('button', { name: '已确认', exact: true }).click()
  await expect(page.getByText('Other operator confirmed', { exact: true })).toBeVisible()
})

test('B failed confirmation keeps edits and double-click issues only one retry', async ({ page, request }) => {
  const { project } = await setup(request)
  await openPending(page, project.name)
  const section = page.getByTestId('pending-glossary-review')
  await section.getByRole('button', { name: '编辑并确认' }).click()
  await section.getByLabel('待复核译文', { exact: true }).fill('Retry safely')
  let saves = 0
  let release = () => {}
  const gate = new Promise<void>((resolve) => { release = resolve })
  await page.route(`**/api/projects/${project.id}/glossary/*`, async (route) => {
    if (route.request().method() !== 'PATCH') return route.continue()
    saves += 1
    if (saves === 1) return route.fulfill({ status: 503, json: { detail: '暂时无法保存' } })
    await gate
    return route.continue()
  })
  await section.getByRole('button', { name: '保存并确认' }).click()
  await expect(section.getByRole('alert')).toContainText('暂时无法保存')
  await expect(section.getByLabel('待复核译文', { exact: true })).toHaveValue('Retry safely')
  await section.getByRole('button', { name: '保存并确认' }).evaluate((element: HTMLButtonElement) => { element.click(); element.click() })
  await expect.poll(() => saves).toBe(2)
  await expect(section.getByLabel('待复核译文', { exact: true })).toBeDisabled()
  release()
  await expect(section).toContainText('暂无待复核术语')
  expect(saves).toBe(2)
})

test('B pending search pagination and later processing preserve the stored record', async ({ page, request }) => {
  const { project } = await setup(request, 21)
  await openPending(page, project.name)
  const section = page.getByTestId('pending-glossary-review')
  await expect(section).toContainText('共 21 条语言记录')
  await expect(section.getByRole('button', { name: '编辑并确认' })).toHaveCount(20)
  await section.getByRole('button', { name: '下一页' }).click()
  await expect(section.getByRole('button', { name: '编辑并确认' })).toHaveCount(1)
  await section.getByLabel('搜索待复核术语').fill('T-005')
  await expect(section).toContainText('Combat Power 5')
  await section.getByRole('button', { name: '编辑并确认' }).click()
  await section.getByLabel('待复核译文', { exact: true }).fill('Unconfirmed draft')
  await expect(section.getByLabel('搜索待复核术语')).toBeDisabled()
  await section.getByRole('button', { name: '稍后处理' }).click()
  await expect(section.getByText('Combat Power 5', { exact: true })).toBeVisible()
  const stored = await request.get(`${baseURL}/api/projects/${project.id}/glossary/pending?q=T-005`).then((response) => response.json())
  expect(stored.items[0]).toMatchObject({ target: 'Combat Power 5', confirmed: false })
})

test('B late pending response after switching projects never populates the new project', async ({ page, request }) => {
  const a = await setup(request)
  const b = await request.post(`${baseURL}/api/projects`, { data: { name: `E2E B empty ${Date.now()}` } }).then((response) => response.json())
  let release = () => {}
  let requested = false
  const gate = new Promise<void>((resolve) => { release = resolve })
  await page.route(`**/api/projects/${a.project.id}/glossary/pending?**`, async (route) => {
    if (new URL(route.request().url()).searchParams.get('page_size') === '1') return route.continue()
    requested = true
    await gate
    try { await route.continue() } catch { /* The previous project request was canceled. */ }
  })
  await openGlossary(page, a.project.name)
  await page.getByRole('button', { name: /^待复核/ }).click()
  await expect.poll(() => requested).toBe(true)
  await page.getByRole('button', { name: b.name }).click()
  await page.getByRole('button', { name: '术语表', exact: true }).click()
  await page.getByRole('button', { name: /^待复核/ }).click()
  release()
  await expect(page.getByTestId('pending-glossary-review')).toContainText('暂无待复核术语')
  await expect(page.getByText('Combat Power 0', { exact: true })).toHaveCount(0)
})

test('B member presentation can read pending terms without confirmation controls', async ({ page, request }) => {
  const { project } = await setup(request)
  // UI capability contract only; real authorization is covered by backend/auth tests.
  await page.route('**/api/auth/me', (route) => route.fulfill({ json: {
    id: 'read-only-reviewer', username: 'reader', display_name: '只读成员', role: 'member',
    auth_enabled: true, must_change_password: false, capabilities: ['project:read', 'task:run'],
  } }))
  await openGlossary(page, project.name)
  await page.getByRole('button', { name: /^待复核/ }).click()
  const section = page.getByTestId('pending-glossary-review')
  await expect(section).toContainText('Combat Power 0')
  await expect(section).toContainText('当前账号只读')
  await expect(section.getByRole('button', { name: /编辑并确认|保存并确认/ })).toHaveCount(0)
  await expect(page.getByTestId('manual-glossary-tools')).toHaveCount(0)
})

test('B importing while already in pending filter refreshes its list without changing tabs', async ({ page, request }) => {
  const { project, artifact } = await setup(request, 1, false)
  await openGlossary(page, project.name)
  await page.getByRole('button', { name: /^待复核/ }).click()
  await expect(page.getByTestId('pending-glossary-review')).toContainText('暂无待复核术语')
  await page.getByRole('button', { name: '导入 / 生成 / 导出', exact: true }).click()
  await page.getByRole('button', { name: '导入已确认术语', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '导入已确认术语' })
  if (await dialog.getByLabel('选择已有文件').isVisible()) await dialog.getByLabel('选择已有文件').selectOption(artifact.id)
  await dialog.getByTestId('archive-import-analyze').click()
  await dialog.getByLabel('覆盖人工维护项并标记待复核；勾选后必须重新分析').click()
  await dialog.getByTestId('archive-import-analyze').click()
  await dialog.getByTestId('archive-import-commit').click()
  await expect(dialog).toContainText('本批次 1 条语言记录待复核')
  await dialog.getByRole('button', { name: '查看待复核术语' }).click()
  await expect(page.getByTestId('pending-glossary-review')).toContainText('Combat Power 0')
  await page.getByRole('button', { name: '编辑并确认' }).click()
  await expect(page.getByRole('button', { name: '已确认', exact: true })).toBeDisabled()
  await expect(page.getByRole('button', { name: '导入 / 生成 / 导出', exact: true })).toBeDisabled()
})

test('B delayed confirmed-row save cannot discard a pending draft during internal refresh', async ({ page, request }) => {
  const { project } = await setup(request)
  expect((await request.post(`${baseURL}/api/projects/${project.id}/glossary`, {
    data: { term_key: 'CONFIRMED', source: '奖励', target: 'Reward', language: 'en' },
  })).ok()).toBeTruthy()
  await openGlossary(page, project.name)
  let release = () => {}
  let requested = false
  const gate = new Promise<void>((resolve) => { release = resolve })
  await page.route(`**/api/projects/${project.id}/glossary/by-source-key?**`, async (route) => {
    if (route.request().method() !== 'PATCH') return route.continue()
    const response = await route.fetch()
    requested = true
    await gate
    await route.fulfill({ response })
  })
  const confirmedRow = page.locator('.glossary-table tbody tr').first()
  await expect(confirmedRow).toContainText('Reward')
  await confirmedRow.getByRole('button', { name: '编辑', exact: true }).click()
  await confirmedRow.getByRole('button', { name: '保存', exact: true }).click()
  await expect.poll(() => requested).toBe(true)
  await page.getByRole('button', { name: /^待复核/ }).click()
  const section = page.getByTestId('pending-glossary-review')
  await section.getByRole('button', { name: '编辑并确认' }).click()
  await section.getByLabel('待复核译文', { exact: true }).fill('Draft survives delayed refresh')
  release()
  await expect(page.getByText(/词条已保存/)).toBeVisible()
  await expect(section.getByLabel('待复核译文', { exact: true })).toHaveValue('Draft survives delayed refresh')
  await section.getByRole('button', { name: '保存并确认' }).click()
  await expect(section).toContainText('暂无待复核术语')
  await page.getByRole('button', { name: '已确认', exact: true }).click()
  await expect(page.getByText('Draft survives delayed refresh', { exact: true })).toBeVisible()
})
