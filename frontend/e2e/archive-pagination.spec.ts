import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

const baseURL = process.env.E2E_BASE_URL ?? `http://127.0.0.1:${process.env.LWS_E2E_FRONTEND_PORT ?? '15173'}`

async function createProject(request: APIRequestContext, suffix: string) {
  return request.post(`${baseURL}/api/projects`, {
    data: {
      name: `E2E 归档分页 ${suffix} ${Date.now()}`,
      type: 'archive-pagination',
      description: '归档服务端分页与轻量项目快照回归。',
    },
  }).then((response) => response.json())
}

async function openProject(page: Page, projectName: string) {
  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await expect(page.getByRole('heading', { name: projectName, exact: true })).toBeVisible()
}

async function selectWizardStep(page: Page, step: number) {
  await page.getByTestId('step-menu-toggle').click()
  await page.getByTestId(`step-${step}`).click()
}

test('project hydration requests a light snapshot and overview counts archives from stats', async ({ page, request }) => {
  const project = await createProject(request, '轻量快照')
  for (const [entryKey, source, target] of [
    ['A-1', '开始游戏', 'Start Game'],
    ['A-2', '领取奖励', 'Claim Reward'],
  ]) {
    const response = await request.post(`${baseURL}/api/projects/${project.id}/translations`, {
      data: { entry_key: entryKey, source, target, language: 'en' },
    })
    expect(response.ok()).toBeTruthy()
  }

  const detailQueries: URLSearchParams[] = []
  page.on('request', (outgoing) => {
    const url = new URL(outgoing.url())
    if (outgoing.method() === 'GET' && url.pathname === `/api/projects/${project.id}`) {
      detailQueries.push(url.searchParams)
    }
  })

  await openProject(page, project.name)
  await expect.poll(() => detailQueries.length).toBeGreaterThan(0)
  expect(detailQueries.every((query) => query.get('include_archives') === 'false')).toBe(true)
  await expect(page.locator('.stat-card', { hasText: '已归档文本' })).toContainText('2')
})

test('a light snapshot clears stale embedded archive arrays from project state', async ({ page, request }) => {
  const project = await createProject(request, '清理旧快照')
  await page.route('**/api/projects', async (route) => {
    if (route.request().method() !== 'GET') {
      await route.continue()
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([{
        ...project,
        translations: [{
          id: 'stale-translation',
          entry_key: 'STALE',
          source: '过期原文',
          target: 'STALE EMBEDDED TARGET',
          target_alt: '',
          language: 'en',
          sheet: '',
          row_number: 0,
          note: '',
          source_type: 'imported',
          source_artifact_id: '',
        }],
        glossary: [{
          id: 'stale-term',
          term_key: 'STALE',
          source: '过期术语',
          target: 'STALE EMBEDDED TERM',
          language: 'en',
          category: '',
          note: '',
          source_type: 'imported',
          confirmed: true,
        }],
      }]),
    })
  })

  await openProject(page, project.name)
  await page.getByRole('button', { name: '译文归档', exact: true }).click()
  await expect(page.getByText('STALE EMBEDDED TARGET', { exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: '术语表', exact: true }).click()
  await expect(page.getByText('STALE EMBEDDED TERM', { exact: true })).toHaveCount(0)
})

test('light hydration keeps archive stats inside the translation wizard without full embedding', async ({ page, request }) => {
  const project = await createProject(request, '向导统计')
  await request.post(`${baseURL}/api/projects/${project.id}/glossary`, {
    data: { term_key: 'POWER', source: '战力', target: 'Power', language: 'en', category: 'system', note: '' },
  })
  await request.post(`${baseURL}/api/projects/${project.id}/translations`, {
    data: { entry_key: 'CLAIM', source: '领取奖励', target: 'Claim', language: 'en', note: '' },
  })
  const template = await request.get(`${baseURL}/api/import-templates/language-table`)
  expect(template.ok()).toBeTruthy()
  const source = await request.post(`${baseURL}/api/projects/${project.id}/files?kind=language_table`, {
    multipart: { file: { name: 'wizard-light.xlsx', mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer: await template.body() } },
  }).then((response) => response.json())
  const detailQueries: URLSearchParams[] = []
  page.on('request', (outgoing) => {
    const url = new URL(outgoing.url())
    if (outgoing.method() === 'GET' && url.pathname === `/api/projects/${project.id}`) detailQueries.push(url.searchParams)
  })

  await openProject(page, project.name)
  await page.locator('main').getByRole('button', { name: '新翻译任务', exact: true }).click()
  await selectWizardStep(page, 4)
  const readiness = page.waitForResponse((response) => response.url().includes(`/artifacts/${source.id}/translation-readiness`) && response.ok())
  await page.locator('.step-panel.active label.asset-select select').selectOption(source.id)
  await readiness
  await page.getByTestId('step-menu-toggle').click()
  await expect(page.getByTestId('step-7')).toBeEnabled()
  await page.getByTestId('step-menu-toggle').click()
  await selectWizardStep(page, 7)

  const facts = page.locator('.workflow-fact-list')
  await expect(facts).toContainText('术语')
  await expect(facts).toContainText('1 条')
  await expect(facts).toContainText('历史译文')
  expect(detailQueries.length).toBeGreaterThan(0)
  expect(detailQueries.every((query) => query.get('include_archives') === 'false')).toBe(true)
})

test('blank-target archive languages stay visible and missing-language cells cannot fake a save', async ({ page, request }) => {
  const project = await createProject(request, '空译文语言')
  await request.post(`${baseURL}/api/projects/${project.id}/translations`, {
    data: { entry_key: 'BOTH', source: '战力', target: 'Power', language: 'en', note: '' },
  })
  await request.post(`${baseURL}/api/projects/${project.id}/translations`, {
    data: { entry_key: 'BOTH', source: '战力', target: '', language: 'ko', note: '' },
  })
  await request.post(`${baseURL}/api/projects/${project.id}/translations`, {
    data: { entry_key: 'KO-ONLY', source: '韩语专用', target: '', language: 'ko', note: '' },
  })

  await openProject(page, project.name)
  await page.getByRole('button', { name: '译文归档', exact: true }).click()

  const koreanToggle = page.getByTestId('archive-display-lang-ko')
  await expect(koreanToggle).toBeVisible()
  await koreanToggle.click()
  await expect(koreanToggle).toHaveAttribute('aria-pressed', 'true')

  await page.getByTestId('archive-search').fill('战力')
  const editableRow = page.locator('.translation-wide-table tbody tr').first()
  await editableRow.getByRole('button', { name: '编辑', exact: true }).click()
  await editableRow.locator('td').nth(3).locator('input').fill('전투력')
  await editableRow.getByRole('button', { name: '保存', exact: true }).click()
  await expect(editableRow).toContainText('전투력')

  await page.getByTestId('archive-search').fill('韩语专用')
  const missingEnglishRow = page.locator('.translation-wide-table tbody tr').first()
  await expect(missingEnglishRow).toContainText('韩语专用')
  await missingEnglishRow.getByRole('button', { name: '编辑', exact: true }).click()
  const missingEnglish = missingEnglishRow.getByLabel('EN 无归档记录')
  await expect(missingEnglish).toBeDisabled()
  await expect(missingEnglish).toHaveAttribute('title', '无该语言记录，请先手动新增')
})

test('archive search, language selection and paging are served by the wide endpoint', async ({ page, request }) => {
  const project = await createProject(request, '服务端翻页')
  const csv = [
    'ID,CN,EN',
    ...Array.from({ length: 205 }, (_, index) => {
      const value = String(index).padStart(3, '0')
      return `A-${value},分页源文 ${value},Target ${value}`
    }),
  ].join('\n')
  const artifact = await request.post(`${baseURL}/api/projects/${project.id}/files?kind=language_table`, {
    multipart: { file: { name: 'pagination.csv', mimeType: 'text/csv', buffer: Buffer.from(csv) } },
  }).then((response) => response.json())
  const imported = await request.post(`${baseURL}/api/projects/${project.id}/translations/import`, {
    data: { artifact_id: artifact.id },
  })
  expect(imported.ok()).toBeTruthy()
  const korean = await request.post(`${baseURL}/api/projects/${project.id}/translations`, {
    data: { entry_key: 'KR-204', source: '分页源文 204', target: '페이지 204', language: 'ko' },
  })
  expect(korean.ok()).toBeTruthy()

  const wideQueries: URLSearchParams[] = []
  page.on('request', (outgoing) => {
    const url = new URL(outgoing.url())
    if (url.pathname === `/api/projects/${project.id}/translations/wide`) wideQueries.push(url.searchParams)
  })

  await openProject(page, project.name)
  await page.getByRole('button', { name: '译文归档', exact: true }).click()
  await expect(page.locator('.translation-wide-table tbody tr')).toHaveCount(100)
  expect(wideQueries.at(-1)?.get('page')).toBe('1')
  expect(wideQueries.at(-1)?.get('page_size')).toBe('100')
  expect(wideQueries.at(-1)?.get('languages')).toBe('en')

  await page.getByTestId('archive-page-next').click()
  await expect(page.locator('.translation-wide-table')).toContainText('Target 100')
  await expect.poll(() => wideQueries.at(-1)?.get('page')).toBe('2')

  await page.getByTestId('archive-search').fill('페이지 204')
  await expect(page.locator('.translation-wide-table')).toContainText('Target 204')
  await expect.poll(() => wideQueries.at(-1)?.get('q')).toBe('페이지 204')
  expect(wideQueries.at(-1)?.get('page')).toBe('1')

  const row = page.locator('.translation-wide-table tbody tr').first()
  await row.getByRole('button', { name: '编辑', exact: true }).click()
  const patchRequest = page.waitForRequest((outgoing) => {
    const url = new URL(outgoing.url())
    return outgoing.method() === 'PATCH' && url.pathname === `/api/projects/${project.id}/translations/by-source-key`
  })
  await row.locator('input').nth(1).fill('分页源文 204 修改')
  await row.locator('input').nth(2).fill('Target 204 edited')
  const [saved] = await Promise.all([
    patchRequest,
    row.getByRole('button', { name: '保存', exact: true }).click(),
  ])
  const patchBody = saved.postDataJSON() as { expected_revision?: string; shared?: { source?: string }; targets?: Record<string, string> }
  expect(patchBody.expected_revision).toBeTruthy()
  expect(patchBody.shared?.source).toBe('分页源文 204 修改')
  expect(patchBody.targets).toEqual({ en: 'Target 204 edited' })
  await expect(page.locator('.translation-wide-table')).toContainText('Target 204 edited')
  await expect.poll(() => wideQueries.at(-1)?.get('page')).toBe('1')
  const editedReadback = await request.get(`${baseURL}/api/projects/${project.id}/translations/wide`, {
    params: { q: '分页源文 204 修改', languages: 'en,ko' },
  }).then((response) => response.json())
  expect(editedReadback.total_rows).toBe(1)
  expect(editedReadback.rows[0].translations.en.target).toBe('Target 204 edited')
  expect(editedReadback.rows[0].translations.ko.target).toBe('페이지 204')

  await page.getByTestId('archive-display-lang-ko').click()
  await expect(page.locator('.translation-wide-table')).toContainText('페이지 204')
  await expect.poll(() => wideQueries.at(-1)?.get('languages')).toBe('en,ko')
})
