import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

const baseURL = process.env.E2E_BASE_URL ?? `http://127.0.0.1:${process.env.LWS_E2E_FRONTEND_PORT ?? '15173'}`
type ArchiveKind = 'glossary' | 'translations'

async function createProject(request: APIRequestContext, suffix: string) {
  const response = await request.post(`${baseURL}/api/projects`, {
    data: { name: `E2E 归档读回 ${suffix} ${Date.now()}`, type: 'archive-readback', description: '隔离的归档读回与来源标识回归。' },
  })
  expect(response.ok()).toBeTruthy()
  return response.json()
}

function widePage(projectId: string, kind: ArchiveKind, target = 'Archive readback') {
  return {
    project_id: projectId,
    rows: [{
      source_key: '归档测试文本', source: '归档测试文本', entry_key: 'A-1', term_key: 'A-1', note: '', category: '', conflicts: [], languages: ['en'],
      translations: { en: { id: `${kind}-readback`, language: 'en', target, target_alt: '', source_type: 'imported', review_status: 'approved' } },
    }],
    total_rows: 1, page: 1, page_size: 100, total_pages: 1, languages: ['en'], coverage: { en: 1 }, revision: '1',
  }
}

async function openArchive(page: Page, projectName: string, kind: ArchiveKind) {
  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.getByRole('button', { name: kind === 'glossary' ? '术语表' : '译文归档', exact: true }).click()
}

async function prepareImport(page: Page, request: APIRequestContext, kind: ArchiveKind, options: { delayReadback?: boolean; failReadback?: boolean } = {}) {
  const project = await createProject(request, kind)
  const artifact = await request.post(`${baseURL}/api/projects/${project.id}/files?kind=${kind === 'glossary' ? 'term_base' : 'language_table'}`, {
    multipart: { file: { name: 'archive-readback.csv', mimeType: 'text/csv', buffer: Buffer.from('ID,CN,EN\nA-1,归档测试文本,Archive readback\n') } },
  }).then((response) => response.json())
  const projectSnapshot = await request.get(`${baseURL}/api/projects/${project.id}?include_archives=false`).then((response) => response.json())
  const counts = { commits: 0, projects: 0, batches: 0, wide: 0 }
  let releaseReadback = () => {}
  const readbackGate = new Promise<void>((resolve) => { releaseReadback = resolve })
  let completeReadback = () => {}
  const readbackDone = new Promise<void>((resolve) => { completeReadback = resolve })
  let readbackFailed = false

  await page.route(`**/api/projects/${project.id}?**`, async (route) => {
    if (route.request().method() !== 'GET' || !counts.commits) return route.continue()
    counts.projects += 1
    if (options.delayReadback) await readbackGate
    if (options.failReadback && !readbackFailed) {
      readbackFailed = true
      return route.fulfill({ status: 503, body: 'Readback temporarily unavailable' })
    }
    await route.fulfill({ json: { ...projectSnapshot, name: `${project.name}（服务器读回）` } })
    completeReadback()
  })
  await page.route(`**/api/projects/${project.id}/${kind}/import/analyze`, async (route) => {
    await route.fulfill({ json: {
      batch_id: 'aib-readback', token: 'ait-readback',
      artifact: { id: artifact.id, label: artifact.label, kind: artifact.kind, checksum: 'sha256-readback' },
      sheet: 'CSV', mode: 'merge', dataset_key: 'dataset-readback', languages: ['en'], columns: {},
      summary: { source_rows: 1, insert: 1, update: 0, unchanged: 0, skip: 0, clear: 0, deactivate: 0, protected: 0, conflict: 0 },
      changes: [], conflicts: [], can_commit: true,
    } })
  })
  await page.route(`**/api/projects/${project.id}/${kind}/import/commit?**`, async (route) => {
    expect(route.request().postDataJSON()).toMatchObject({ token: 'ait-readback' })
    expect(new URL(route.request().url()).searchParams.get('compact')).toBe('true')
    counts.commits += 1
    await route.fulfill({ json: { status: 'committed', batch_id: 'aib-readback', summary: { insert: 1 }, languages: ['en'], imported_count: 1, dataset_key: 'dataset-readback' } })
  })
  await page.route(`**/api/projects/${project.id}/${kind}/import/batches?**`, async (route) => {
    if (counts.commits) counts.batches += 1
    await route.fulfill({ json: { project_id: project.id, kind, batches: counts.commits ? [{ id: 'aib-readback', status: 'committed', dataset_key: 'dataset-readback', sheet_key: 'CSV', languages: ['en'], revision: '1' }] : [] } })
  })
  await page.route(`**/api/projects/${project.id}/${kind}/wide?**`, async (route) => {
    if (!counts.commits) return route.continue()
    counts.wide += 1
    await route.fulfill({ json: widePage(project.id, kind) })
  })
  await openArchive(page, project.name, kind)
  if (kind === 'glossary') {
    await page.getByRole('button', { name: '导入 / 生成 / 导出', exact: true }).click()
    await page.getByRole('button', { name: '导入已确认术语', exact: true }).click()
  } else {
    await page.getByRole('button', { name: '导入译文', exact: true }).first().click()
  }
  const dialog = page.getByRole('dialog', { name: kind === 'glossary' ? '导入已确认术语' : '安全导入译文归档' })
  if (await dialog.getByLabel('选择已有文件').isVisible()) await dialog.getByLabel('选择已有文件').selectOption(artifact.id)
  await dialog.getByTestId('archive-import-analyze').click()
  await expect(dialog.getByTestId('archive-import-stage-preview')).toHaveAttribute('aria-current', 'step')
  return { project, counts, dialog, releaseReadback, readbackDone }
}

for (const kind of ['glossary', 'translations'] as const) {
  test(`${kind} reuses the first committed project snapshot while retaining batch and wide readback`, async ({ page, request }) => {
    const { project, counts, dialog } = await prepareImport(page, request, kind)
    await dialog.getByTestId('archive-import-commit').click()
    await expect(dialog.getByTestId('archive-import-stage-success')).toHaveAttribute('aria-current', 'step')
    await dialog.getByRole('button', { name: '关闭并查看归档' }).click()
    await expect(page.getByText('Archive readback', { exact: true })).toBeVisible()
    expect(counts).toMatchObject({ commits: 1, projects: 1 })
    expect(counts.batches).toBeGreaterThanOrEqual(1)
    expect(counts.wide).toBeGreaterThanOrEqual(1)
    await expect(page.getByRole('heading', { name: `${project.name}（服务器读回）`, exact: true })).toBeVisible()
  })

  test(`${kind} discards a late committed snapshot after switching projects`, async ({ page, request }) => {
    const projectB = await createProject(request, `${kind} 项目 B`)
    const { project, counts, dialog, releaseReadback, readbackDone } = await prepareImport(page, request, kind, { delayReadback: true })
    let projectBReads = 0
    await page.route(`**/api/projects/${projectB.id}?**`, async (route) => {
      projectBReads += 1
      await route.continue()
    })
    await dialog.getByTestId('archive-import-commit').click()
    await expect.poll(() => counts.projects).toBe(1)
    await page.getByRole('button', { name: projectB.name }).evaluate((element: HTMLButtonElement) => element.click())
    await expect(page.getByRole('heading', { name: projectB.name, exact: true })).toBeVisible()
    const bReadsAfterSwitch = projectBReads
    releaseReadback()
    await readbackDone
    await page.waitForTimeout(100)
    await expect(dialog).toBeHidden()
    await expect(page.getByText(`${project.name}（服务器读回）`, { exact: true })).toBeHidden()
    await expect(page.getByText('Archive readback', { exact: true })).toBeHidden()
    expect(counts.projects).toBe(1)
    expect(counts.wide).toBe(0)
    expect(projectBReads).toBe(bReadsAfterSwitch)
    await expect(page.getByRole('heading', { name: project.name, exact: true })).toBeHidden()
  })

  test(`${kind} retries a failed readback without committing again or duplicating the project GET`, async ({ page, request }) => {
    const { counts, dialog } = await prepareImport(page, request, kind, { failReadback: true })
    await dialog.getByTestId('archive-import-commit').click()
    await expect(dialog.getByTestId('archive-import-stage-success')).toHaveAttribute('aria-current', 'step')
    await expect(dialog).toContainText('提交已完成，但自动读回失败')
    await dialog.getByRole('button', { name: '重试读回', exact: true }).click()
    await expect(dialog).not.toContainText('提交已完成，但自动读回失败')
    await dialog.getByRole('button', { name: '关闭并查看归档' }).click()
    await expect(page.getByText('Archive readback', { exact: true })).toBeVisible()
    expect(counts).toMatchObject({ commits: 1, projects: 2 })
    expect(counts.batches).toBeGreaterThanOrEqual(2)
    expect(counts.wide).toBeGreaterThanOrEqual(1)
  })
}

test('imported pending provenance identifies the correct language without marking approved translations pending', async ({ page, request }, testInfo) => {
  const project = await createProject(request, '语言待复核')
  await page.route(`**/api/projects/${project.id}/translations/wide?**`, async (route) => {
    const payload = widePage(project.id, 'translations', 'Pending English')
    payload.rows[0].languages = ['en', 'ko']
    payload.rows[0].translations.en.review_status = 'pending'
    Object.assign(payload.rows[0].translations, { ko: { id: 'translation-approved-ko', language: 'ko', target: '승인된 번역', target_alt: '', source_type: 'imported', review_status: 'approved' } })
    payload.languages = ['en', 'ko']
    await route.fulfill({ json: payload })
  })
  await page.setViewportSize({ width: 1440, height: 900 })
  await openArchive(page, project.name, 'translations')
  const table = page.locator('table.translation-archive-table')
  await expect(table).toContainText('Pending English')
  await page.getByTestId('archive-display-lang-ko').click()
  await expect(table).toContainText('승인된 번역')
  const badges = table.locator('.provenance-badge')
  await expect(badges.filter({ hasText: 'EN · 外部导入·待复核' })).toHaveCount(1)
  await expect(badges.filter({ hasText: 'KR · 外部导入' })).toHaveText('KR · 外部导入')
  await expect(badges.filter({ hasText: '待复核' })).toHaveCount(1)
  await expect(badges.filter({ hasText: 'EN ·' })).toHaveClass(/review/)
  await expect(table.getByRole('button', { name: /确认|复核/ })).toHaveCount(0)
  await page.screenshot({ path: testInfo.outputPath('archive-pending-languages-1440.png'), fullPage: true })
  await page.setViewportSize({ width: 1024, height: 768 })
  await table.scrollIntoViewIfNeeded()
  await expect(badges.filter({ hasText: 'EN · 外部导入·待复核' })).toBeInViewport()
  await expect(badges.filter({ hasText: 'KR · 外部导入' })).toBeInViewport()
  await page.screenshot({ path: testInfo.outputPath('archive-pending-languages-1024.png'), fullPage: true })
})
