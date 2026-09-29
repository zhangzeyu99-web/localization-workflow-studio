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
