import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

const baseURL = process.env.E2E_BASE_URL ?? `http://127.0.0.1:${process.env.LWS_E2E_FRONTEND_PORT ?? '15173'}`

async function createProject(request: APIRequestContext, suffix: string) {
  return request.post(`${baseURL}/api/projects`, {
    data: {
      name: `E2E 候选与删除 ${suffix} ${Date.now()}`,
      type: 'archive-maintenance',
      description: 'Task3B 项目页候选与删除语义回归。',
    },
  }).then((response) => response.json())
}

async function openProjectTab(page: Page, projectName: string, tab: '术语表' | '译文归档') {
  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.getByRole('button', { name: tab, exact: true }).click()
}

async function exposeArchiveRecordsDuringTask4Migration(page: Page, request: APIRequestContext, projectId: string) {
  await page.route(`**/api/projects/${projectId}?include_archives=false`, async (route) => {
    const project = await request.get(`${baseURL}/api/projects/${projectId}?include_archives=true`).then((response) => response.json())
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(project) })
  })
}

test('project glossary scans an independent language table and only accept writes a term', async ({ page, request }) => {
  const project = await createProject(request, '候选')
  await exposeArchiveRecordsDuringTask4Migration(page, request, project.id)
  const beforeProject = await request.get(`${baseURL}/api/projects/${project.id}`).then((response) => response.json())
  const candidates = [
    {
      id: 'candidate-accept', batch_id: 'batch-project-scan', project_id: project.id, action: 'new',
      term_key: 'T-1', source: '战力', target: 'Combat Power', language: 'en', category: 'system', note: '', status: 'pending',
    },
    {
      id: 'candidate-reject', batch_id: 'batch-project-scan', project_id: project.id, action: 'new',
      term_key: 'T-2', source: '临时候选', target: 'Temporary', language: 'en', category: 'other', note: '', status: 'pending',
    },
  ]
  let extractBody: Record<string, unknown> | null = null
  let activeCandidates = [...candidates]

  await page.route(`**/api/projects/${project.id}/glossary/extract`, async (route) => {
    extractBody = route.request().postDataJSON() as Record<string, unknown>
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        run: { id: 'run-project-scan', project_id: project.id, kind: 'glossary', status: 'passed', metadata: {} },
        artifacts: [],
        glossary_backfill: { batch_id: 'batch-project-scan', candidates: 2, pending_confirmation: 2 },
      }),
    })
  })
  await page.route(`**/api/projects/${project.id}/glossary/batches?**`, async (route) => {
    const pending = activeCandidates.filter((candidate) => candidate.status === 'pending').length
    const accepted = activeCandidates.filter((candidate) => candidate.status === 'accepted').length
    const rejected = activeCandidates.filter((candidate) => candidate.status === 'rejected').length
    const batch = {
      id: 'batch-project-scan', project_id: project.id, source_artifact_id: String(extractBody?.input_artifact_id || ''),
      label: 'Project scan', language: 'en', status: pending ? 'pending' : 'resolved', metadata: {},
      created_at: '2026-07-15T00:00:00Z', updated_at: '2026-07-15T00:00:00Z',
      counts: { total: 2, pending, accepted, rejected, pending_new: pending, pending_supplement: 0 },
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ batches: [batch], active_batch: batch, candidates: activeCandidates }),
    })
  })
  await page.route(`**/api/projects/${project.id}/glossary/batches/batch-project-scan/*`, async (route) => {
    const action = route.request().url().endsWith('/accept') ? 'accepted' : 'rejected'
    const ids = (route.request().postDataJSON() as { candidate_ids: string[] }).candidate_ids
    activeCandidates = activeCandidates.map((candidate) => ids.includes(candidate.id) ? { ...candidate, status: action } : candidate)
    if (action === 'accepted') {
      for (const candidate of activeCandidates.filter((item) => ids.includes(item.id))) {
        await request.post(`${baseURL}/api/projects/${project.id}/glossary`, {
          data: {
            term_key: candidate.term_key,
            source: candidate.source,
            target: candidate.target,
            language: candidate.language,
            category: candidate.category,
            note: candidate.note,
          },
        })
      }
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ resolved_count: ids.length, candidates: activeCandidates }) })
  })

  await openProjectTab(page, project.name, '术语表')
  await expect(page.locator('input[name="target_alt"]')).toHaveCount(0)
  await page.getByRole('button', { name: '导入 / 生成 / 导出', exact: true }).click()
  const upload = page.getByLabel('上传完整语言表')
  await expect(upload).toHaveAttribute('accept', '.xlsx')
  await upload.setInputFiles({
    name: 'project-candidate-source.xlsx',
    mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    buffer: Buffer.from('test workbook bytes'),
  })
  await expect(page.getByText('project-candidate-source.xlsx', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '扫描候选', exact: true }).click()

  await expect(page.getByRole('heading', { name: '确认候选' })).toBeVisible()
  expect(extractBody).toMatchObject({
    language: 'en',
    update_project_prompt: false,
  })
  expect(extractBody).toHaveProperty('input_artifact_id')
  const afterScanProject = await request.get(`${baseURL}/api/projects/${project.id}`).then((response) => response.json())
  expect(afterScanProject.glossary).toHaveLength(0)
  expect(afterScanProject.prompt_text).toBe(beforeProject.prompt_text)
  expect(afterScanProject.runs).toEqual(beforeProject.runs)

  await page.getByRole('button', { name: '跳过候选“临时候选”' }).click()
  await expect.poll(async () => (await request.get(`${baseURL}/api/projects/${project.id}/glossary`)).json()).toHaveLength(0)
  await page.getByRole('button', { name: '加入候选“战力”' }).click()
  await expect.poll(async () => (await request.get(`${baseURL}/api/projects/${project.id}/glossary`)).json()).toHaveLength(1)
  await expect(page.locator('table.glossary-wide-table')).toContainText('战力')
  await expect(page.getByRole('status', { name: '候选操作状态' })).toContainText('已加入')
})

test('candidate patch failure blocks save-and-accept', async ({ page, request }) => {
  const project = await createProject(request, '候选保存失败')
  const sourceArtifact = await request.post(`${baseURL}/api/projects/${project.id}/files?kind=language_table`, {
    multipart: {
      file: {
        name: 'candidate-patch-failure.xlsx',
        mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        buffer: Buffer.from('candidate patch failure workbook'),
      },
    },
  }).then((response) => response.json())
  const batch = {
    id: 'batch-patch-failure', project_id: project.id, source_artifact_id: sourceArtifact.id,
    label: 'Patch failure', language: 'en', status: 'pending',
    created_at: '2026-07-15T00:00:00Z', updated_at: '2026-07-15T00:00:00Z',
    counts: { total: 1, pending: 1, accepted: 0, rejected: 0, pending_new: 1, pending_supplement: 0 },
  }
  const candidate = {
    id: 'candidate-patch-failure', batch_id: batch.id, project_id: project.id, action: 'new',
    term_key: 'PATCH', source: '保存失败候选', target: 'Patch candidate', language: 'en',
    category: 'system', note: '', status: 'pending',
  }
  let acceptCalls = 0

  await page.route(`**/api/projects/${project.id}/glossary/extract`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ glossary_backfill: { batch_id: batch.id, candidates: 1, pending_confirmation: 1 } }),
    })
  })
  await page.route(`**/api/projects/${project.id}/glossary/batches?**`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ batches: [batch], active_batch: batch, candidates: [candidate] }),
    })
  })
  await page.route(`**/api/projects/${project.id}/glossary/candidates/${candidate.id}`, async (route) => {
    await route.fulfill({
      status: 500,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'forced candidate patch failure' }),
    })
  })
  await page.route(`**/api/projects/${project.id}/glossary/batches/${batch.id}/accept`, async (route) => {
    acceptCalls += 1
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ resolved_count: 1 }) })
  })

  await openProjectTab(page, project.name, '术语表')
  await page.getByRole('button', { name: '导入 / 生成 / 导出', exact: true }).click()
  await page.getByLabel('选择完整语言表').selectOption(sourceArtifact.id)
  await page.getByRole('button', { name: '扫描候选', exact: true }).click()
  const candidateRow = page.getByTestId(`glossary-candidate-${candidate.id}`)
  await candidateRow.getByRole('button', { name: '编辑', exact: true }).click()
  await candidateRow.getByRole('button', { name: '保存并加入', exact: true }).click()

  await expect(page.getByRole('status', { name: '候选操作状态' })).toContainText('候选保存失败')
  expect(acceptCalls).toBe(0)
  await expect(candidateRow.getByRole('button', { name: '取消', exact: true })).toBeVisible()
  await expect.poll(async () => (await request.get(`${baseURL}/api/projects/${project.id}/glossary`)).json()).toHaveLength(0)
})

test('project Vietnamese candidate scan omits an explicit VI target column', async ({ page, request }) => {
  const project = await createProject(request, '越南语候选列')
  const sourceArtifact = await request.post(`${baseURL}/api/projects/${project.id}/files?kind=language_table`, {
    multipart: {
      file: {
        name: 'candidate-vn.xlsx',
        mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        buffer: Buffer.from('route-intercepted workbook'),
      },
    },
  }).then((response) => response.json())
  let extractBody: Record<string, unknown> | null = null
  await page.route(`**/api/projects/${project.id}/glossary/extract`, async (route) => {
    extractBody = route.request().postDataJSON() as Record<string, unknown>
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ glossary_backfill: { candidates: 0, pending_confirmation: 0 } }),
    })
  })

  await openProjectTab(page, project.name, '术语表')
  await page.getByRole('button', { name: '导入 / 生成 / 导出', exact: true }).click()
  const candidatePanel = page.locator('.archive-tool-block', { hasText: '扫描术语候选' })
  await candidatePanel.getByLabel('选择完整语言表').selectOption(sourceArtifact.id)
  await candidatePanel.getByRole('button', { name: 'VN 越南语', exact: true }).click()
  await candidatePanel.getByRole('button', { name: '扫描候选', exact: true }).click()

  await expect.poll(() => extractBody).not.toBeNull()
  expect(extractBody).toMatchObject({ language: 'vn' })
  expect(extractBody).not.toHaveProperty('target_column')
})

test('wide glossary and archive delete only EN, cancel all, then confirm all with readback', async ({ page, request }) => {
  const project = await createProject(request, '删除')
  const deleteAllQueries: URLSearchParams[] = []
  page.on('request', (outgoing) => {
    const url = new URL(outgoing.url())
    if (outgoing.method() === 'DELETE' && url.pathname.endsWith('/by-source-key')) deleteAllQueries.push(url.searchParams)
  })
  await exposeArchiveRecordsDuringTask4Migration(page, request, project.id)
  for (const [language, glossaryTarget, archiveTarget] of [
    ['en', 'Combat Power', 'Claim rewards'],
    ['ko', '전투력', '보상 수령'],
    ['vn', 'Sức chiến đấu', 'Nhận thưởng'],
  ]) {
    const glossaryResponse = await request.post(`${baseURL}/api/projects/${project.id}/glossary`, {
      data: { term_key: 'POWER', source: '战力', target: glossaryTarget, language, category: 'system', note: 'delete semantics' },
    })
    expect(glossaryResponse.ok()).toBeTruthy()
    const archiveResponse = await request.post(`${baseURL}/api/projects/${project.id}/translations`, {
      data: { entry_key: 'CLAIM', source: '领取奖励', target: archiveTarget, language, source_type: 'qa_passed', note: 'delete semantics' },
    })
    expect(archiveResponse.ok()).toBeTruthy()
  }

  const glossaryLanguages = async () => {
    const records = await request.get(`${baseURL}/api/projects/${project.id}/glossary`).then((response) => response.json()) as Array<{ language: string }>
    return records.map((record) => record.language).sort()
  }
  const archiveLanguages = async () => {
    const records = await request.get(`${baseURL}/api/projects/${project.id}/translations`).then((response) => response.json()) as Array<{ language: string }>
    return records.map((record) => record.language).sort()
  }

  await openProjectTab(page, project.name, '术语表')
  await expect(page.getByTestId('glossary-display-lang-ko')).toHaveAttribute('aria-pressed', 'false')
  const glossaryRow = page.locator('.glossary-wide-table tbody tr', { hasText: '战力' }).first()
  await glossaryRow.getByRole('button', { name: '删除当前语言（EN）', exact: true }).click()
  await expect.poll(glossaryLanguages).toEqual(['ko', 'vn'])
  await expect(page.getByTestId('glossary-display-lang-ko')).toHaveAttribute('aria-pressed', 'false')

  await glossaryRow.getByRole('button', { name: '删除全部语言', exact: true }).click()
  let dialog = page.getByRole('alertdialog')
  await expect(dialog).toContainText(/KR.*VN.*2 条语言记录/)
  await dialog.getByRole('button', { name: '取消', exact: true }).click()
  await expect.poll(glossaryLanguages).toEqual(['ko', 'vn'])
  await glossaryRow.getByRole('button', { name: '删除全部语言', exact: true }).click()
  dialog = page.getByRole('alertdialog')
  await dialog.getByRole('button', { name: '删除全部', exact: true }).click()
  await expect.poll(glossaryLanguages).toEqual([])
  expect(deleteAllQueries.at(-1)?.get('expected_revision')).toBeTruthy()

  await page.getByRole('button', { name: '译文归档', exact: true }).click()
  await expect(page.locator('input[name="target_alt"]')).toHaveCount(0)
  await expect(page.getByTestId('archive-display-lang-ko')).toHaveAttribute('aria-pressed', 'false')
  const archiveRow = page.locator('.translation-wide-table tbody tr', { hasText: '领取奖励' }).first()
  await archiveRow.getByRole('button', { name: '删除当前语言（EN）', exact: true }).click()
  await expect.poll(archiveLanguages).toEqual(['ko', 'vn'])
  await expect(page.getByTestId('archive-display-lang-ko')).toHaveAttribute('aria-pressed', 'false')

  await archiveRow.getByRole('button', { name: '删除全部语言', exact: true }).click()
  dialog = page.getByRole('alertdialog')
  await expect(dialog).toContainText(/KR.*VN.*2 条语言记录/)
  await dialog.getByRole('button', { name: '取消', exact: true }).click()
  await expect.poll(archiveLanguages).toEqual(['ko', 'vn'])
  await archiveRow.getByRole('button', { name: '删除全部语言', exact: true }).click()
  dialog = page.getByRole('alertdialog')
  await dialog.getByRole('button', { name: '删除全部', exact: true }).click()
  await expect.poll(archiveLanguages).toEqual([])
  expect(deleteAllQueries.at(-1)?.get('expected_revision')).toBeTruthy()
})

test('selected VN can be deleted while its display column stays hidden', async ({ page, request }) => {
  const project = await createProject(request, '隐藏越南语删除')
  for (const [language, target] of [['en', 'Claim'], ['ko', '수령'], ['vn', 'Nhận']]) {
    const response = await request.post(`${baseURL}/api/projects/${project.id}/translations`, {
      data: { entry_key: 'CLAIM', source: '领取', target, language, note: 'hidden selected language' },
    })
    expect(response.ok()).toBeTruthy()
  }
  const wideQueries: URLSearchParams[] = []
  page.on('request', (outgoing) => {
    const url = new URL(outgoing.url())
    if (url.pathname === `/api/projects/${project.id}/translations/wide`) wideQueries.push(url.searchParams)
  })

  await openProjectTab(page, project.name, '译文归档')
  await page.getByTestId('manual-archive-tools').locator('summary').click()
  await page.getByTestId('manual-archive-tools').getByRole('button', { name: 'VN 越南语', exact: true }).click()
  await expect.poll(() => wideQueries.at(-1)?.get('languages')).toBe('en,vn')
  await expect(page.getByTestId('archive-display-lang-vn')).toHaveAttribute('aria-pressed', 'false')
  const row = page.locator('.translation-wide-table tbody tr', { hasText: '领取' }).first()
  const deleteButton = row.getByRole('button', { name: '删除当前语言（VN）', exact: true })
  await expect(deleteButton).toBeEnabled()
  await deleteButton.click()

  await expect.poll(async () => {
    const records = await request.get(`${baseURL}/api/projects/${project.id}/translations`).then((response) => response.json()) as Array<{ language: string }>
    return records.map((record) => record.language).sort()
  }).toEqual(['en', 'ko'])
})

test('project switch ignores a delayed glossary candidate response', async ({ page, request }) => {
  const projectA = await createProject(request, '慢项目 A')
  const projectB = await createProject(request, '目标项目 B')
  const uploadResponse = await request.post(`${baseURL}/api/projects/${projectA.id}/files?kind=language_table`, {
    multipart: {
      file: {
        name: 'slow-candidate-source.xlsx',
        mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        buffer: Buffer.from('slow workbook bytes'),
      },
    },
  })
  const sourceArtifact = await uploadResponse.json()
  let releaseExtract: (() => void) | null = null
  let extractStarted = false
  const extractGate = new Promise<void>((resolve) => { releaseExtract = resolve })

  await page.route(`**/api/projects/${projectA.id}/glossary/extract`, async (route) => {
    extractStarted = true
    await extractGate
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ glossary_backfill: { batch_id: 'stale-batch', candidates: 1, pending_confirmation: 1 } }),
    }).catch(() => undefined)
  })
  await page.route(`**/api/projects/${projectA.id}/glossary/batches?**`, async (route) => {
    const batch = {
      id: 'stale-batch', project_id: projectA.id, source_artifact_id: sourceArtifact.id,
      label: 'stale', language: 'en', status: 'pending', created_at: '2026-07-15T00:00:00Z', updated_at: '2026-07-15T00:00:00Z',
      counts: { total: 1, pending: 1, accepted: 0, rejected: 0, pending_new: 1, pending_supplement: 0 },
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        batches: [batch], active_batch: batch,
        candidates: [{
          id: 'stale-candidate', batch_id: batch.id, project_id: projectA.id, action: 'new',
          term_key: 'STALE', source: '过期候选', target: 'Stale candidate', language: 'en', category: '', note: '', status: 'pending',
        }],
      }),
    })
  })

  await openProjectTab(page, projectA.name, '术语表')
  await page.getByRole('button', { name: '导入 / 生成 / 导出', exact: true }).click()
  await page.getByLabel('选择完整语言表').selectOption(sourceArtifact.id)
  await page.getByRole('button', { name: '扫描候选', exact: true }).click()
  await expect.poll(() => extractStarted).toBe(true)
  await page.getByRole('button', { name: projectB.name }).click()
  await expect(page.getByRole('heading', { name: projectB.name, exact: true })).toBeVisible()
  releaseExtract?.()
  await page.waitForTimeout(500)
  await expect(page.getByText('过期候选', { exact: true })).toHaveCount(0)
  await expect(page.getByTestId('glossary-candidate-review')).toHaveCount(0)
})
