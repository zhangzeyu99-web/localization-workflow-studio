import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

const baseURL = process.env.E2E_BASE_URL ?? `http://127.0.0.1:${process.env.LWS_E2E_FRONTEND_PORT ?? '15173'}`

async function createProject(request: APIRequestContext, suffix: string) {
  return request.post(`${baseURL}/api/projects`, {
    data: {
      name: `E2E 安全导入 ${suffix} ${Date.now()}`,
      type: 'archive-import',
      description: '统一安全导入 UI 回归测试。',
    },
  }).then((response) => response.json())
}

async function openTranslationArchive(page: Page, projectName: string) {
  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.getByRole('button', { name: '译文归档', exact: true }).click()
  await expect(page.getByText('项目译文归档')).toBeVisible()
}

test('selecting or uploading a translation file never writes before explicit preview and commit', async ({ page, request }) => {
  const project = await createProject(request, '译文')
  const alternateArtifact = await request.post(`${baseURL}/api/projects/${project.id}/files?kind=language_table`, {
    multipart: {
      file: { name: 'alternate.csv', mimeType: 'text/csv', buffer: Buffer.from('ID,CN,EN\nA-2,领取奖励,Claim\n') },
    },
  }).then((response) => response.json())
  const projectSnapshot = await request.get(`${baseURL}/api/projects/${project.id}`).then((response) => response.json())
  const analyzeBodies: Array<Record<string, unknown>> = []
  let analyzeCalls = 0
  let commitCalls = 0
  let legacyImportCalls = 0
  let commitCompleted = false
  let postCommitProjectReads = 0
  let uploadedArtifactId = ''

  await page.route(`**/api/projects/${project.id}?**`, async (route) => {
    if (route.request().method() !== 'GET' || !commitCompleted) {
      await route.continue()
      return
    }
    postCommitProjectReads += 1
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...projectSnapshot,
        translations: [{
          id: 'translation-readback', entry_key: 'A-1', source: '开始游戏', target: 'Start (readback)', target_alt: '',
          language: 'en', sheet: 'Data', row_number: 2, note: '', source_type: 'imported', source_artifact_id: uploadedArtifactId,
          dataset_key: 'dataset-main', active: 1,
        }],
      }),
    })
  })

  await page.route(`**/api/projects/${project.id}/translations/import/analyze`, async (route) => {
    analyzeCalls += 1
    const body = route.request().postDataJSON() as Record<string, unknown>
    analyzeBodies.push(body)
    if (body.artifact_id !== alternateArtifact.id) uploadedArtifactId = String(body.artifact_id)
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        batch_id: 'aib-preview',
        token: 'ait-preview',
        artifact: { id: body.artifact_id, label: body.artifact_id === alternateArtifact.id ? alternateArtifact.label : 'safe-import.json', kind: 'language_table', checksum: 'sha256-preview' },
        sheet: 'Data',
        mode: 'merge',
        dataset_key: 'dataset-main',
        languages: ['en'],
        columns: { id: 'ID', source: 'CN', en: 'EN' },
        summary: { source_rows: 4, insert: 1, update: 1, unchanged: 1, skip: 1, clear: 0, deactivate: 0, protected: 0, conflict: 0 },
        changes: [],
        conflicts: [],
        can_commit: true,
      }),
    })
  })
  await page.route(`**/api/projects/${project.id}/translations/import/batches?**`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        project_id: project.id,
        kind: 'translations',
        batches: commitCompleted ? [{ id: 'aib-preview', status: 'committed', dataset_key: 'dataset-main', sheet_key: 'Data', languages: ['en'], revision: '1' }] : [],
      }),
    })
  })
  await page.route(`**/api/projects/${project.id}/translations/wide?**`, async (route) => {
    if (!commitCompleted) {
      await route.continue()
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        project_id: project.id,
        rows: [{
          source_key: '开始游戏', source: '开始游戏', entry_key: 'A-1', note: '', conflicts: [], languages: ['en'],
          translations: { en: { id: 'translation-readback', language: 'en', target: 'Start (readback)', target_alt: '', source_type: 'imported', review_status: 'approved' } },
        }],
        total_rows: 1, page: 1, page_size: 100, total_pages: 1, languages: ['en'], coverage: { en: 1 }, revision: '1',
      }),
    })
  })
  await page.route(`**/api/projects/${project.id}/translations/import/commit?**`, async (route) => {
    commitCalls += 1
    commitCompleted = true
    expect(new URL(route.request().url()).searchParams.get('compact')).toBe('true')
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'committed', batch_id: 'aib-preview', summary: { insert: 1, update: 1, unchanged: 1, skip: 1 }, language_summary: { en: { insert: 1, update: 1, unchanged: 1, skip: 1 } }, imported_count: 3, languages: ['en'] }) })
  })
  await page.route(`**/api/projects/${project.id}/translations/import`, async (route) => {
    legacyImportCalls += 1
    await route.fulfill({ status: 500, body: 'legacy import must not run' })
  })

  await openTranslationArchive(page, project.name)
  const opener = page.getByRole('button', { name: '导入译文', exact: true }).first()
  await opener.click()

  const dialog = page.getByRole('dialog', { name: '安全导入译文归档' })
  await expect(dialog).toHaveAttribute('aria-modal', 'true')
  await expect(dialog.getByRole('heading', { name: '安全导入译文归档' })).toHaveCSS('color', 'rgb(23, 32, 38)')
  const initialSourceSelect = dialog.getByLabel('选择已有文件')
  if (await initialSourceSelect.isVisible()) await expect(initialSourceSelect).toBeFocused()
  else await expect(dialog.getByTestId('archive-import-close')).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect(opener).toBeFocused()
  await opener.click()

  if (!await dialog.getByLabel('上传新文件').isVisible()) await dialog.getByRole('button', { name: '更换来源' }).click()
  await expect(dialog.getByLabel('上传新文件')).toHaveAttribute('accept', '.xlsx,.csv,.json')
  const uploadRequestPromise = page.waitForRequest((candidate) => (
    candidate.method() === 'POST'
    && candidate.url().includes(`/api/projects/${project.id}/files?kind=language_table`)
  ))
  await dialog.getByLabel('上传新文件').setInputFiles({
    name: 'safe-import.json',
    mimeType: 'application/json',
    buffer: Buffer.from(JSON.stringify({ entries: [{ entry_key: 'A-1', source: '开始游戏', language: 'en', target: 'Start' }] })),
  })
  await uploadRequestPromise

  await expect(dialog.getByText('safe-import.json', { exact: true })).toBeVisible()
  await expect(dialog.getByTestId('archive-import-stage-settings')).toHaveAttribute('aria-current', 'step')
  await expect(dialog.getByLabel('数据集归属').locator('option').first()).toHaveText('自动判断（匹配既有则更新，否则新建数据集）')
  await expect(dialog.getByTestId('archive-import-commit')).toBeDisabled()
  expect(analyzeCalls).toBe(0)
  expect(commitCalls).toBe(0)

  await dialog.getByTestId('archive-import-analyze').click()
  await expect(dialog.getByTestId('archive-import-stage-preview')).toHaveAttribute('aria-current', 'step')
  expect(analyzeBodies[0]).not.toHaveProperty('target_alt_column')
  await expect(dialog.getByTestId('archive-import-summary-insert')).toContainText('1')
  await expect(dialog.getByTestId('archive-import-summary-update')).toContainText('1')
  await expect(dialog.getByTestId('archive-import-summary-unchanged')).toContainText('1')
  await expect(dialog.getByTestId('archive-import-summary-skip')).toContainText('1')
  await expect(dialog.getByTestId('archive-import-commit')).toBeEnabled()
  expect(analyzeCalls).toBe(1)
  expect(commitCalls).toBe(0)

  await dialog.getByRole('button', { name: '返回设置' }).click()
  const koButton = dialog.getByTestId('archive-import-language-ko')
  await expect(koButton).toHaveAttribute('aria-pressed', 'false')
  await koButton.click()
  await expect(koButton).toHaveAttribute('aria-pressed', 'true')
  await expect(dialog.getByTestId('archive-import-commit')).toBeDisabled()
  await dialog.getByTestId('archive-import-analyze').click()
  await expect(dialog.getByTestId('archive-import-stage-preview')).toHaveAttribute('aria-current', 'step')

  await dialog.getByRole('button', { name: '返回设置' }).click()
  await dialog.getByRole('button', { name: '更换来源' }).click()
  await dialog.getByLabel('选择已有文件').selectOption(alternateArtifact.id)
  await expect(dialog.getByTestId('archive-import-commit')).toBeDisabled()
  await dialog.getByTestId('archive-import-analyze').click()
  await expect(dialog.getByTestId('archive-import-stage-preview')).toHaveAttribute('aria-current', 'step')
  await dialog.getByTestId('archive-import-commit').click()

  await expect(dialog.getByTestId('archive-import-stage-success')).toHaveAttribute('aria-current', 'step')
  await expect(dialog).toContainText('aib-preview')
  await expect(dialog.getByLabel('每语言提交统计')).toContainText('EN：3 条')
  expect(analyzeCalls).toBe(3)
  expect(commitCalls).toBe(1)
  expect(legacyImportCalls).toBe(0)
  await expect.poll(() => postCommitProjectReads, { timeout: 1000 }).toBeGreaterThanOrEqual(1)
  await dialog.getByRole('button', { name: '关闭并查看归档' }).click()
  await expect(dialog).toBeHidden()
  await expect(opener).toBeFocused()
  await expect(page.getByText('Start (readback)', { exact: true })).toBeVisible()
})

test('real T1 and edited T2 complete the UI analyze commit and persisted readback roundtrip', async ({ page, request }) => {
  const project = await createProject(request, '真实回路')
  let analyzeCalls = 0
  let commitCalls = 0
  let legacyImportCalls = 0
  page.on('request', (outgoing) => {
    const pathname = new URL(outgoing.url()).pathname
    if (pathname === `/api/projects/${project.id}/translations/import/analyze`) analyzeCalls += 1
    if (pathname === `/api/projects/${project.id}/translations/import/commit`) commitCalls += 1
    if (pathname === `/api/projects/${project.id}/translations/import`) legacyImportCalls += 1
  })

  await openTranslationArchive(page, project.name)
  await page.getByRole('button', { name: '导入译文', exact: true }).first().click()
  let dialog = page.getByRole('dialog', { name: '安全导入译文归档' })
  if (!await dialog.getByLabel('上传新文件').isVisible()) await dialog.getByRole('button', { name: '更换来源' }).click()
  await dialog.getByLabel('上传新文件').setInputFiles({
    name: 'roundtrip-t1.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from([
      'ID,CN,EN',
      'A-1,开始游戏,Start',
      'A-2,领取奖励,Claim',
      'A-4,设置,Settings',
    ].join('\n')),
  })

  await expect(dialog.getByTestId('archive-import-stage-settings')).toHaveAttribute('aria-current', 'step')
  let persisted = await request.get(`${baseURL}/api/projects/${project.id}/translations`).then((response) => response.json())
  expect(persisted).toEqual([])
  await dialog.getByTestId('archive-import-analyze').click()
  await expect(dialog.getByTestId('archive-import-stage-preview')).toHaveAttribute('aria-current', 'step')
  await expect(dialog.getByTestId('archive-import-summary-insert')).toContainText('3')
  persisted = await request.get(`${baseURL}/api/projects/${project.id}/translations`).then((response) => response.json())
  expect(persisted).toEqual([])
  await dialog.getByTestId('archive-import-commit').click()
  await expect(dialog.getByTestId('archive-import-stage-success')).toHaveAttribute('aria-current', 'step')
  await dialog.getByRole('button', { name: '关闭并查看归档' }).click()
  await expect(page.locator('table.translation-archive-table')).toContainText('Start')

  const t1Rows = await request.get(`${baseURL}/api/projects/${project.id}/translations`).then((response) => response.json()) as Array<Record<string, unknown>>
  expect(t1Rows).toHaveLength(3)
  const t1ByKey = new Map(t1Rows.map((row) => [row.entry_key, row]))
  expect(t1ByKey.get('A-1')?.target).toBe('Start')
  expect(t1ByKey.get('A-2')?.target).toBe('Claim')

  await page.getByRole('button', { name: '导入译文', exact: true }).first().click()
  dialog = page.getByRole('dialog', { name: '安全导入译文归档' })
  if (!await dialog.getByLabel('上传新文件').isVisible()) await dialog.getByRole('button', { name: '更换来源' }).click()
  await dialog.getByLabel('上传新文件').setInputFiles({
    name: 'roundtrip-t2.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from([
      'ID,CN,EN',
      'A-1,开始游戏,Launch',
      'A-2,领取奖励,',
      'A-3,退出游戏,Exit',
      'A-4,设置,Settings',
    ].join('\n')),
  })
  await dialog.getByTestId('archive-import-analyze').click()
  await expect(dialog.getByTestId('archive-import-stage-preview')).toHaveAttribute('aria-current', 'step')
  await expect(dialog.getByTestId('archive-import-summary-insert')).toContainText('1')
  await expect(dialog.getByTestId('archive-import-summary-update')).toContainText('1')
  await expect(dialog.getByTestId('archive-import-summary-unchanged')).toContainText('1')
  await expect(dialog.getByTestId('archive-import-summary-skip')).toContainText('1')

  const beforeT2Commit = await request.get(`${baseURL}/api/projects/${project.id}/translations`).then((response) => response.json()) as Array<Record<string, unknown>>
  const beforeT2ByKey = new Map(beforeT2Commit.map((row) => [row.entry_key, row]))
  expect(beforeT2ByKey.get('A-1')?.target).toBe('Start')
  expect(beforeT2ByKey.get('A-2')?.target).toBe('Claim')
  expect(beforeT2ByKey.has('A-3')).toBe(false)

  await dialog.getByTestId('archive-import-commit').click()
  await expect(dialog.getByTestId('archive-import-stage-success')).toHaveAttribute('aria-current', 'step')
  await dialog.getByRole('button', { name: '关闭并查看归档' }).click()
  const archiveTable = page.locator('table.translation-archive-table')
  await expect(archiveTable).toContainText('Launch')
  await expect(archiveTable).toContainText('Claim')
  await expect(archiveTable).toContainText('Exit')
  await expect(archiveTable).toContainText('Settings')

  const projectReadback = await request.get(`${baseURL}/api/projects/${project.id}`).then((response) => response.json())
  const projectByKey = new Map((projectReadback.translations as Array<Record<string, unknown>>).map((row) => [row.entry_key, row]))
  expect(projectByKey.get('A-1')?.target).toBe('Launch')
  expect(projectByKey.get('A-2')?.target).toBe('Claim')
  expect(projectByKey.get('A-3')?.target).toBe('Exit')
  expect(projectByKey.get('A-4')?.target).toBe('Settings')
  const wideReadback = await request.get(`${baseURL}/api/projects/${project.id}/translations/wide`).then((response) => response.json())
  expect(wideReadback.row_count).toBe(4)
  const wideExit = (wideReadback.rows as Array<Record<string, any>>).find((row) => row.entry_key === 'A-3')
  expect(wideExit?.translations.en.target).toBe('Exit')
  expect(analyzeCalls).toBe(2)
  expect(commitCalls).toBe(2)
  expect(legacyImportCalls).toBe(0)
})

test('structured sheet errors lead back to settings and snapshot requires lineage plus a second confirmation', async ({ page, request }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  const project = await createProject(request, '快照')
  const lineageArtifact = await request.post(`${baseURL}/api/projects/${project.id}/files?kind=language_table`, {
    multipart: {
      file: {
        name: 'lineage-base.csv',
        mimeType: 'text/csv',
        buffer: Buffer.from('ID,CN,EN\nA-0,基础文本,Base\n'),
      },
    },
  }).then((response) => response.json())
  const lineageAnalysis = await request.post(`${baseURL}/api/projects/${project.id}/translations/import/analyze`, {
    data: { artifact_id: lineageArtifact.id, languages: ['en'], mode: 'merge' },
  }).then((response) => response.json())
  const lineageCommit = await request.post(`${baseURL}/api/projects/${project.id}/translations/import/commit`, {
    data: { token: lineageAnalysis.token },
  })
  expect(lineageCommit.ok()).toBeTruthy()
  const datasetKey = lineageAnalysis.dataset_key as string
  const lineageSheet = lineageAnalysis.sheet as string
  const secondLineageArtifact = await request.post(`${baseURL}/api/projects/${project.id}/files?kind=language_table`, {
    multipart: {
      file: {
        name: 'lineage-other.json',
        mimeType: 'application/json',
        buffer: Buffer.from(JSON.stringify({ entries: [{ entry_key: 'B-1', source: '设置', target: 'Settings', language: 'en' }] })),
      },
    },
  }).then((response) => response.json())
  const secondLineageAnalysis = await request.post(`${baseURL}/api/projects/${project.id}/translations/import/analyze`, {
    data: { artifact_id: secondLineageArtifact.id, languages: ['en'], mode: 'merge', dataset_key: datasetKey },
  }).then((response) => response.json())
  const secondLineageCommit = await request.post(`${baseURL}/api/projects/${project.id}/translations/import/commit`, {
    data: { token: secondLineageAnalysis.token },
  })
  expect(secondLineageCommit.ok()).toBeTruthy()
  expect(secondLineageAnalysis.sheet).not.toBe(lineageSheet)
  const artifact = await request.post(`${baseURL}/api/projects/${project.id}/files?kind=language_table`, {
    multipart: {
      file: {
        name: 'snapshot-source.csv',
        mimeType: 'text/csv',
        buffer: Buffer.from('ID,CN,EN\nA-1,开始游戏,Start\n'),
      },
    },
  }).then((response) => response.json())
  let analyzeCalls = 0
  let commitCalls = 0
  const analyzeBodies: Array<Record<string, unknown>> = []

  await page.route(`**/api/projects/${project.id}/translations/import/analyze`, async (route) => {
    analyzeCalls += 1
    const body = route.request().postDataJSON() as Record<string, unknown>
    analyzeBodies.push(body)
    if (analyzeCalls === 1) {
      await route.fulfill({
        status: 422,
        contentType: 'application/json',
        body: JSON.stringify({ detail: { code: 'sheet_selection_required', message: '请选择一个工作表。', sheets: ['Data', 'Archive'] } }),
      })
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        batch_id: body.mode === 'snapshot' ? 'aib-snapshot' : 'aib-lineage',
        token: body.mode === 'snapshot' ? 'ait-snapshot' : 'ait-lineage',
        artifact: { id: artifact.id, label: artifact.label, kind: artifact.kind, checksum: 'sha256-snapshot' },
        sheet: body.sheet || 'Archive',
        mode: body.mode,
        dataset_key: datasetKey,
        languages: ['en'],
        columns: { id: 'ID', source: 'CN', en: 'EN' },
        summary: { source_rows: 2, insert: 0, update: 1, unchanged: 0, skip: 0, clear: 0, deactivate: body.mode === 'snapshot' ? 1 : 0, protected: 0, conflict: 0 },
        changes: [],
        conflicts: [],
        can_commit: true,
      }),
    })
  })
  await page.route(`**/api/projects/${project.id}/translations/import/commit?**`, async (route) => {
    commitCalls += 1
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'committed', batch_id: 'aib-snapshot', summary: { update: 1, deactivate: 1 }, languages: ['en'], dataset_key: datasetKey }) })
  })

  await openTranslationArchive(page, project.name)
  await page.getByRole('button', { name: '导入译文', exact: true }).first().click()
  const dialog = page.getByRole('dialog', { name: '安全导入译文归档' })
  const sourceSelect = dialog.getByLabel('选择已有文件')
  if (await sourceSelect.isVisible()) await sourceSelect.selectOption(artifact.id)
  else await expect(dialog).toContainText('snapshot-source.csv')
  await dialog.getByTestId('archive-import-analyze').click()
  await expect(dialog.getByRole('alert')).toContainText('请选择一个工作表')
  await expect(dialog.getByLabel('工作表')).toBeVisible()
  await dialog.getByLabel('工作表').selectOption('Archive')
  await dialog.getByTestId('archive-import-analyze').click()
  await expect(dialog.getByTestId('archive-import-stage-preview')).toHaveAttribute('aria-current', 'step')

  await dialog.getByRole('button', { name: '返回设置' }).click()
  await dialog.getByText('高级列映射（留空自动识别）', { exact: true }).click()
  await dialog.getByLabel('ID 列', { exact: true }).fill('ID')
  await expect(dialog.getByTestId('archive-import-commit')).toBeDisabled()
  await dialog.getByTestId('archive-import-analyze').click()
  await expect(dialog.getByTestId('archive-import-stage-preview')).toHaveAttribute('aria-current', 'step')

  await dialog.getByRole('button', { name: '返回设置' }).click()
  await dialog.getByTestId('archive-import-mode-snapshot').click()
  await expect(dialog.getByTestId('archive-import-mode-snapshot')).toHaveAttribute('aria-pressed', 'true')
  await expect(dialog.getByTestId('archive-import-commit')).toBeDisabled()
  await expect(dialog.getByLabel('覆盖数据集').locator('option').filter({ hasText: datasetKey })).toHaveCount(2)
  await dialog.getByLabel('覆盖数据集').selectOption({ label: `${datasetKey} · ${lineageSheet}` })
  await dialog.getByTestId('archive-import-analyze').click()
  expect(analyzeBodies.at(-1)).toMatchObject({ dataset_key: datasetKey, sheet: lineageSheet, mode: 'snapshot' })
  await expect(dialog).toContainText('将停用 1 条当前数据集内、但本次文件缺失的译文')
  await dialog.screenshot({ path: '../.tmp/sdd/archive-import-task3a-snapshot-preview.png' })

  await dialog.getByRole('button', { name: '返回设置' }).click()
  await dialog.getByLabel('覆盖数据集').selectOption('')
  await expect(dialog.getByTestId('archive-import-commit')).toBeDisabled()
  await dialog.getByLabel('覆盖数据集').selectOption({ label: `${datasetKey} · ${lineageSheet}` })
  await dialog.getByTestId('archive-import-analyze').click()
  await expect(dialog.getByTestId('archive-import-stage-preview')).toHaveAttribute('aria-current', 'step')
  expect(analyzeCalls).toBe(5)

  await dialog.getByTestId('archive-import-commit').click()
  const snapshotConfirm = dialog.getByRole('alertdialog')
  await expect(snapshotConfirm).toContainText(datasetKey)
  const confirmButton = snapshotConfirm.getByRole('button', { name: '确认覆盖并提交' })
  const cancelButton = snapshotConfirm.getByRole('button', { name: '取消' })
  await expect(confirmButton).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(cancelButton).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(snapshotConfirm).toBeHidden()
  await expect(dialog).toBeVisible()
  await expect(dialog.getByTestId('archive-import-commit')).toBeFocused()
  expect(commitCalls).toBe(0)
  await dialog.getByTestId('archive-import-commit').click()
  await dialog.getByRole('button', { name: '确认覆盖并提交' }).click()
  await expect(dialog.getByTestId('archive-import-stage-success')).toHaveAttribute('aria-current', 'step')
  expect(commitCalls).toBe(1)
})

test('confirmed glossary import is isolated from candidate scanning and protected rows require re-analysis', async ({ page, request }) => {
  const project = await createProject(request, '术语')
  const artifact = await request.post(`${baseURL}/api/projects/${project.id}/files?kind=term_base`, {
    multipart: {
      file: {
        name: 'confirmed-terms.csv',
        mimeType: 'text/csv',
        buffer: Buffer.from('ID,CN,EN\nT-1,战力,Combat Power\n'),
      },
    },
  }).then((response) => response.json())
  const analyzeBodies: Array<Record<string, unknown>> = []
  let commitCalls = 0
  let legacyImportCalls = 0

  await page.route(`**/api/projects/${project.id}/glossary/import/analyze`, async (route) => {
    const body = route.request().postDataJSON() as Record<string, unknown>
    analyzeBodies.push(body)
    const override = body.override_protected === true
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        batch_id: override ? 'aib-glossary-safe' : 'aib-glossary-blocked',
        token: override ? 'ait-glossary-safe' : 'ait-glossary-blocked',
        artifact: { id: artifact.id, label: artifact.label, kind: artifact.kind, checksum: 'sha256-glossary' },
        sheet: 'Glossary',
        mode: 'merge',
        dataset_key: 'glossary-main',
        languages: ['en'],
        columns: { id: 'ID', source: 'CN', en: 'EN' },
        summary: { source_rows: 1, insert: 0, update: override ? 1 : 0, unchanged: 0, skip: 0, clear: 0, deactivate: 0, protected: 1, conflict: override ? 0 : 1 },
        changes: [],
        conflicts: override ? [] : [{ code: 'protected_source', message: '人工或精选术语默认禁止覆盖。', source: '战力' }],
        can_commit: override,
      }),
    })
  })
  await page.route(`**/api/projects/${project.id}/glossary/import/commit?**`, async (route) => {
    commitCalls += 1
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'committed', batch_id: 'aib-glossary-safe', summary: { update: 1, protected: 1 }, languages: ['en'], dataset_key: 'glossary-main' }) })
  })
  await page.route(`**/api/projects/${project.id}/glossary/import`, async (route) => {
    legacyImportCalls += 1
    await route.fulfill({ status: 500, body: 'legacy import must not run' })
  })

  await page.goto(baseURL)
  await page.getByRole('button', { name: project.name }).click()
  await page.getByRole('button', { name: '术语表', exact: true }).click()
  await page.getByRole('button', { name: '导入 / 生成 / 导出', exact: true }).click()
  await expect(page.getByText('完整语言表不会直接写入项目术语库')).toBeVisible()
  await page.getByRole('button', { name: '导入已确认术语', exact: true }).click()

  const dialog = page.getByRole('dialog', { name: '导入已确认术语' })
  const sourceSelect = dialog.getByLabel('选择已有文件')
  if (await sourceSelect.isVisible()) await sourceSelect.selectOption(artifact.id)
  else await expect(dialog).toContainText('confirmed-terms.csv')
  await dialog.getByTestId('archive-import-analyze').click()

  expect(analyzeBodies[0]).toMatchObject({
    artifact_id: artifact.id,
    confirmed_glossary: true,
    mode: 'merge',
    override_protected: false,
  })
  await expect(dialog.getByRole('alert')).toContainText('人工或精选术语默认禁止覆盖')
  await expect(dialog.getByTestId('archive-import-commit')).toBeDisabled()
  expect(commitCalls).toBe(0)

  await dialog.getByLabel('覆盖人工维护项并标记待复核；勾选后必须重新分析').click()
  await expect(dialog.getByTestId('archive-import-stage-settings')).toHaveAttribute('aria-current', 'step')
  await expect(dialog.getByTestId('archive-import-commit')).toBeDisabled()
  await dialog.getByTestId('archive-import-analyze').click()
  expect(analyzeBodies[1]).toMatchObject({ confirmed_glossary: true, mode: 'merge', override_protected: true })
  await dialog.getByTestId('archive-import-commit').click()
  await expect(dialog.getByTestId('archive-import-stage-success')).toHaveAttribute('aria-current', 'step')
  expect(commitCalls).toBe(1)
  expect(legacyImportCalls).toBe(0)
})

test('a structured 409 invalidates the preview token and requires a fresh analysis', async ({ page, request }) => {
  const project = await createProject(request, '409')
  const artifact = await request.post(`${baseURL}/api/projects/${project.id}/files?kind=language_table`, {
    multipart: {
      file: { name: 'stale.csv', mimeType: 'text/csv', buffer: Buffer.from('ID,CN,EN\nA-1,开始游戏,Start\n') },
    },
  }).then((response) => response.json())

  await page.route(`**/api/projects/${project.id}/translations/import/analyze`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        batch_id: 'aib-before-conflict', token: 'ait-before-conflict',
        artifact: { id: artifact.id, label: artifact.label, kind: artifact.kind, checksum: 'sha256-stale' },
        sheet: 'CSV', mode: 'merge', dataset_key: 'dataset-stale', languages: ['en'], columns: {},
        summary: { source_rows: 1, insert: 1, update: 0, unchanged: 0, skip: 0, clear: 0, deactivate: 0, protected: 0, conflict: 0 },
        changes: [], conflicts: [], can_commit: true,
      }),
    })
  })
  await page.route(`**/api/projects/${project.id}/translations/import/commit?**`, async (route) => {
    await route.fulfill({
      status: 409,
      contentType: 'application/json',
      body: JSON.stringify({ detail: { code: 'stale_state', message: '归档状态已变化，请重新分析。', batch_id: 'aib-before-conflict' } }),
    })
  })

  await openTranslationArchive(page, project.name)
  await page.getByRole('button', { name: '导入译文', exact: true }).first().click()
  const dialog = page.getByRole('dialog', { name: '安全导入译文归档' })
  if (await dialog.getByLabel('选择已有文件').isVisible()) await dialog.getByLabel('选择已有文件').selectOption(artifact.id)
  await dialog.getByTestId('archive-import-analyze').click()
  await dialog.getByTestId('archive-import-commit').click()

  await expect(dialog.getByRole('alert')).toContainText('归档状态已变化，请重新分析')
  await expect(dialog.getByTestId('archive-import-stage-settings')).toHaveAttribute('aria-current', 'step')
  await expect(dialog.getByTestId('archive-import-commit')).toBeDisabled()
})

test('a late analyze response from project A cannot populate project B', async ({ page, request }) => {
  const projectA = await createProject(request, '项目 A')
  const projectB = await createProject(request, '项目 B')
  const artifact = await request.post(`${baseURL}/api/projects/${projectA.id}/files?kind=language_table`, {
    multipart: {
      file: { name: 'project-a.csv', mimeType: 'text/csv', buffer: Buffer.from('ID,CN,EN\nA-1,开始游戏,Start\n') },
    },
  }).then((response) => response.json())
  let releaseAnalyze: (() => void) | undefined
  const analyzeGate = new Promise<void>((resolve) => { releaseAnalyze = resolve })

  await page.route(`**/api/projects/${projectA.id}/translations/import/analyze`, async (route) => {
    await analyzeGate
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        batch_id: 'aib-project-a-late', token: 'ait-project-a-late',
        artifact: { id: artifact.id, label: artifact.label, kind: artifact.kind, checksum: 'sha256-a' },
        sheet: 'CSV', mode: 'merge', dataset_key: 'dataset-a', languages: ['en'], columns: {},
        summary: { source_rows: 1, insert: 1, update: 0, unchanged: 0, skip: 0, clear: 0, deactivate: 0, protected: 0, conflict: 0 },
        changes: [], conflicts: [], can_commit: true,
      }),
    })
  })

  await openTranslationArchive(page, projectA.name)
  await page.getByRole('button', { name: '导入译文', exact: true }).first().click()
  const dialog = page.getByRole('dialog', { name: '安全导入译文归档' })
  if (await dialog.getByLabel('选择已有文件').isVisible()) await dialog.getByLabel('选择已有文件').selectOption(artifact.id)
  await dialog.getByTestId('archive-import-analyze').click()
  await expect(dialog.getByRole('status')).toContainText('正在分析差异')

  await page.getByRole('button', { name: projectB.name }).evaluate((element: HTMLButtonElement) => element.click())
  await expect(page.getByRole('heading', { name: projectB.name, exact: true })).toBeVisible()
  releaseAnalyze?.()
  await page.waitForTimeout(200)
  await expect(page.getByText('aib-project-a-late', { exact: true })).toBeHidden()
  await expect(dialog).toBeHidden()
})
