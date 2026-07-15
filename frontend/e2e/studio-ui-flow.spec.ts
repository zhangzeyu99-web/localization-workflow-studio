import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

const baseURL = process.env.E2E_BASE_URL ?? `http://127.0.0.1:${process.env.LWS_E2E_FRONTEND_PORT ?? '15173'}`
const sourceWorkbook = process.env.E2E_SOURCE_WORKBOOK ?? path.resolve('..', 'examples', 'synthetic-language.xlsx')
const fileName = (value: string) => path.basename(value.replace(/\\/g, '/'))
const fileStem = (value: string) => fileName(value).replace(/\.[^.]+$/, '')
const inlineStatus = (page: any, text: string) => page.locator('.inline-status', { hasText: text })
const selectWizardStep = async (page: any, step: number, scope?: string) => {
  const root = scope ? page.locator(scope) : page
  await root.getByTestId('step-menu-toggle').click()
  await root.getByTestId(`step-${step}`).click()
}

test.use({ acceptDownloads: true })

test('spreadsheet column errors are shown as actionable Chinese', async ({ page }) => {
  await page.goto(baseURL)
  const message = await page.evaluate(async () => {
    const { sanitizeUserFacingError } = await import('/src/apiClient.ts')
    return sanitizeUserFacingError('target column not found in sheet: fminth')
  })
  expect(message).toBe('所选工作表“fminth”中找不到目标译文列。请确认译文列存在，或返回“判定输入”重新选择语言表。')
})

test('glossary scan events do not expose backend diagnostics', async ({ page }) => {
  await page.goto(baseURL)
  const messages = await page.evaluate(async () => {
    const { humanBackendEvent } = await import('/src/appText.ts')
    return [
      humanBackendEvent('running local workflow step'),
      humanBackendEvent('INPUT=D:\\data\\source.xlsx\nDETAIL_OUTPUT=D:\\runs\\details.xlsx'),
      humanBackendEvent('Glossary backfill strategy: dedupe by normalized CN; stage only missing CN as review candidates.'),
      humanBackendEvent('Glossary backfill result: candidates=2, unique=2, inserted=2, updated=0, existing=0, duplicates=0, conflicts=0, empty=0.'),
      humanBackendEvent('AI glossary supplement added 21 candidates, skipped 9.')
    ]
  })
  expect(messages).toEqual([
    '正在执行本地流程。',
    '正在读取输入文件。',
    '正在整理术语候选。',
    '已整理 2 个术语候选，待确认 2 个。',
    'AI 已补充 21 个候选，跳过 9 个。'
  ])
})

test('quick task preflight events do not expose backend diagnostics', async ({ page }) => {
  await page.goto(baseURL)
  const message = await page.evaluate(async () => {
    const { humanBackendEvent } = await import('/src/appText.ts')
    return humanBackendEvent('quick TXT translation preflight: source_lines=3, batch_size=90, estimated_batches=1')
  })

  expect(message).toBe('正在检查快速任务输入。')
})

test('quick translation completion status stays scoped to the quick task', async ({ page }) => {
  await page.goto(baseURL)
  const message = await page.evaluate(async () => {
    const { projectTranslationPassedStatusText } = await import('/src/domain/projectActivity.ts')
    return projectTranslationPassedStatusText({
      kind: 'translation',
      language: 'en',
      status: 'passed',
      metadata: { task_origin: 'quick_task' },
    } as any, 'en')
  })

  expect(message).toBe('EN 快速翻译已完成并通过 QA，可下载结果。')
})

test('delivery issue label distinguishes available from already delivered', async ({ page }) => {
  await page.goto(baseURL)
  const labels = await page.evaluate(async () => {
    const { deliveryStatusLabel } = await import('/src/components/translationWizard/ProjectTabs.tsx')
    return [
      deliveryStatusLabel({ status: 'failed', delivered_with_issues: true } as any),
      deliveryStatusLabel({ status: 'delivered', delivered_with_issues: true } as any),
      deliveryStatusLabel({ status: 'delivered', task_code: 'ALL', skipped_languages: ['IT'] } as any),
    ]
  })

  expect(labels).toEqual(['带问题可交付', '带问题已交付', '部分交付'])
})

test('failed translation QA exposes the correct repair path for row and structural issues', async ({ page }) => {
  await page.goto(baseURL)
  const modes = await page.evaluate(async () => {
    const { qaRepairMode } = await import('/src/components/translationWizard/steps/StepQA.tsx')
    const failedTranslation = { kind: 'translation', status: 'failed' } as any
    return [
      qaRepairMode(failedTranslation, [{ sheet: 'Sheet1', row: 2, severity: 'hard' }] as any, true),
      qaRepairMode(failedTranslation, [{ sheet: '', row: 0, severity: 'hard' }] as any, true),
    ]
  })

  expect(modes).toEqual(['row_fix', 'rerun_translation'])
})

test('glossary candidate notes hide model metadata', async ({ page }) => {
  await page.goto(baseURL)
  const note = await page.evaluate(async () => {
    const { normalizeGlossaryNote } = await import('/src/domain/projectAssets.ts')
    return normalizeGlossaryNote('AI 漏词补充候选，需人工确认；置信度 high；特训玩法的具体类型，不与 existing_candidates 中“特训”重复。')
  })
  expect(note).toBe('特训玩法的具体类型，不与已有候选中的“特训”重复。')
})

test('glossary review stays visible after another run becomes latest', async ({ page }) => {
  await page.goto(baseURL)
  const state = await page.evaluate(async () => {
    const { glossaryReviewState } = await import('/src/components/translationWizard/steps/StepFreqV2.tsx')
    return glossaryReviewState(
      { id: 'translation-run', kind: 'translation', status: 'needs_input' } as any,
      [{ id: 'batch-1', status: 'pending', counts: { total: 1, pending: 1, accepted: 0, rejected: 0 } }] as any,
      [{ id: 'candidate-1', batch_id: 'batch-1', status: 'pending', target: 'Start Game' }] as any,
    )
  })

  expect(state.showCandidateReview).toBe(true)
  expect(state.blockAdvance).toBe(true)
})

test('active glossary extraction blocks advancing before candidates arrive', async ({ page }) => {
  await page.goto(baseURL)
  const state = await page.evaluate(async () => {
    const { glossaryReviewState } = await import('/src/components/translationWizard/steps/StepFreqV2.tsx')
    return glossaryReviewState(
      { id: 'glossary-run', kind: 'glossary', status: 'running' } as any,
      [],
      [],
    )
  })

  expect(state.extractionActive).toBe(true)
  expect(state.blockAdvance).toBe(true)
})

test('inline status does not repeat running prefixes', async ({ page }) => {
  await page.goto(baseURL)
  const messages = await page.evaluate(async () => {
    const { actionStatusText } = await import('/src/components/shared/WorkflowPrimitives.tsx')
    return [
      actionStatusText('后台任务处理中：正在执行本地流程。', true),
      actionStatusText('正在导入术语表...', true),
      actionStatusText('检测到已有完整译文。', false),
      actionStatusText('当前状态：已完成。', false)
    ]
  })
  expect(messages).toEqual([
    '后台任务处理中：正在执行本地流程。',
    '正在导入术语表...',
    '当前状态：检测到已有完整译文。',
    '当前状态：已完成。'
  ])
})

test('QA issue labels do not expose internal enum names', async ({ page }) => {
  await page.goto(baseURL)
  const labels = await page.evaluate(async () => {
    const { issueHumanMessage, issueTypeLabel } = await import('/src/components/translationWizard/QaIssuePanel.tsx')
    return [
      issueTypeLabel('quality_issue'),
      issueTypeLabel('person_name_term_mismatch'),
      issueHumanMessage({ check_type: 'quality_issue', message: 'Source meaning needs review.' } as any),
      issueHumanMessage({ check_type: 'person_name_term_mismatch', message: "Person name '埃蒙' must use glossary spelling 'Eamon'" } as any)
    ]
  })
  expect(labels).toEqual([
    '文本质量问题',
    '人名术语不一致',
    '模型发现译文含义或表达需要复核，请查看 QA 报告。',
    '人名「埃蒙」应使用术语表译法：Eamon。'
  ])
})

test('announcement artifact labels do not expose internal English names', async ({ page }) => {
  await page.goto(baseURL)
  const labels = await page.evaluate(async () => {
    const { artifactKindLabel } = await import('/src/domain/artifacts.ts')
    return [
      artifactKindLabel({ kind: 'announcement_workpack' } as any),
      artifactKindLabel({ kind: 'announcement_lookup_manifest' } as any),
      artifactKindLabel({ kind: 'announcement_lookup_prompt_context' } as any)
    ]
  })
  expect(labels).toEqual(['公告工作包', '公告清单', '公告提示词上下文'])
})

test('generated result filenames use a user-facing picker label', async ({ page }) => {
  await page.goto(baseURL)
  const label = await page.evaluate(async () => {
    const { artifactPickerLabel } = await import('/src/domain/artifacts.ts')
    return artifactPickerLabel({
      kind: 'qa_final_workbook',
      label: 'QA final workbook',
      path: 'result_en.xlsx',
      origin: 'generated',
      metadata: { language: 'en' },
      created_at: '2026-07-10T00:00:00Z'
    } as any)
  })
  expect(label).toBe('已译语言表｜EN｜翻译结果｜2026-07-10')
})

test('failed announcement tasks do not show stale child runs as translating', async ({ page }) => {
  await page.goto(baseURL)
  const label = await page.evaluate(async () => {
    const { announcementStatusLabel } = await import('/src/domain/announcementText.ts')
    return announcementStatusLabel('running', 'failed')
  })
  expect(label).toBe('需继续/修复')
})

test('runtime version badge shows bundle version without mismatch warning', async ({ page }) => {
  await page.goto(baseURL)
  const badge = page.locator('.runtime-version-badge')
  await expect(badge).toBeVisible()
  await expect(badge).toHaveText(/^v\d+\.\d+\.\d+$/)
  await expect(badge).not.toContainText('版本不一致')
})

test('project list refreshes after an external project is created', async ({ page, request }) => {
  const firstProjectName = `E2E List Base ${Date.now()}`
  await request.post(`${baseURL}/api/projects`, {
    data: { name: firstProjectName, type: 'list-refresh', description: 'Project list refresh base.' },
  })

  await page.goto(baseURL)
  await expect(page.getByRole('button', { name: firstProjectName })).toBeVisible({ timeout: 15000 })
  await page.getByRole('button', { name: firstProjectName }).click()
  await expect(page.getByRole('heading', { name: firstProjectName })).toBeVisible()

  const externalProjectName = `E2E List External ${Date.now()}`
  await request.post(`${baseURL}/api/projects`, {
    data: { name: externalProjectName, type: 'list-refresh', description: 'Created outside the loaded page.' },
  })

  await expect(page.getByRole('button', { name: externalProjectName })).toBeVisible({ timeout: 20000 })
  await expect(page.getByRole('heading', { name: firstProjectName })).toBeVisible()
})

test('project switches keep each workflow location and scope new translation after handling activity', async ({ page, request }) => {
  const firstName = `E2E Scope First ${Date.now()}`
  const secondName = `E2E Scope Second ${Date.now()}`
  const first = await request.post(`${baseURL}/api/projects`, {
    data: { name: firstName, type: 'scope', description: 'First project scope.' },
  }).then((response) => response.json())
  const second = await request.post(`${baseURL}/api/projects`, {
    data: { name: secondName, type: 'scope', description: 'Second project scope.' },
  }).then((response) => response.json())
  const uploadedArtifactIds = new Map<string, string>()
  for (const [projectId, name] of [[first.id, 'first-scope.xlsx'], [second.id, 'second-scope.xlsx']]) {
    const artifact = await request.post(`${baseURL}/api/projects/${projectId}/files?kind=language_table`, {
      multipart: {
        file: {
          name,
          mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
          buffer: fs.readFileSync(sourceWorkbook),
        },
      },
    }).then((response) => response.json())
    uploadedArtifactIds.set(projectId, artifact.id)
  }
  const failedWorkbookRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'lws-project-scope-'))
  const failedWorkbook = path.join(failedWorkbookRoot, 'first-failed-qa.xlsx')
  execFileSync('python', ['-c', `
from openpyxl import Workbook
import sys
wb = Workbook()
ws = wb.active
ws.title = "Language"
ws.append(["ID", "cn", "en"])
ws.append([1, "领取奖励", "Forbidden Brand Reward"])
wb.save(sys.argv[1])
wb.close()
`, failedWorkbook])
  await request.patch(`${baseURL}/api/projects/${first.id}/harness`, {
    data: { forbidden_translations: ['Forbidden Brand'] },
  })
  const failedArtifact = await request.post(`${baseURL}/api/projects/${first.id}/files?kind=final_workbook`, {
    multipart: {
      file: {
        name: fileName(failedWorkbook),
        mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        buffer: fs.readFileSync(failedWorkbook),
      },
    },
  }).then((response) => response.json())
  const failedRun = await request.post(`${baseURL}/api/runs`, {
    data: { project_id: first.id, kind: 'qa', language: 'en', input_artifact_id: failedArtifact.id },
  }).then((response) => response.json())
  const qaResponse = await request.post(`${baseURL}/api/runs/${failedRun.id}/qa`)
  expect(qaResponse.ok()).toBeTruthy()

  await page.goto(baseURL)
  await page.getByRole('button', { name: firstName }).click()
  await expect(page.locator('.project-activity-panel')).toBeVisible()
  await page.locator('.project-activity-panel').getByRole('button', { name: '去处理' }).click()
  await expect(page.locator('.view-tab.active')).toContainText('校对')

  await page.getByRole('button', { name: secondName }).click()
  await page.locator('.sidebar').getByRole('button', { name: /新翻译任务/ }).click()
  await selectWizardStep(page, 4)
  await expect(page.getByTestId('step-menu-toggle')).toContainText('判定输入')
  const sourceSelect = page.locator('.step-panel.active label.asset-select select')
  await expect(sourceSelect).toHaveValue('')
  await sourceSelect.selectOption(uploadedArtifactIds.get(second.id)!)
  await expect(sourceSelect).toHaveValue(uploadedArtifactIds.get(second.id)!)
  await expect(sourceSelect.locator('option:checked')).toContainText('second-scope')
  await expect(sourceSelect.locator('option:checked')).not.toContainText('first-scope')

  await page.getByRole('button', { name: firstName }).click()
  await expect(page.locator('.view-tab.active')).toContainText('校对')

  await page.getByRole('button', { name: secondName }).click()
  await expect(page.getByRole('heading', { name: '新翻译任务', exact: true })).toBeVisible()
  await expect(page.getByTestId('step-menu-toggle')).toContainText('判定输入')
  await expect(sourceSelect).toHaveValue(uploadedArtifactIds.get(second.id)!)
})

test('new translation task lets the user continue or discard an unfinished draft', async ({ page, request }) => {
  const projectName = `E2E Translation Draft Choice ${Date.now()}`
  await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'lifecycle', description: 'Draft choice regression.' },
  })

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.locator('main').getByRole('button', { name: '新翻译任务', exact: true }).click()
  await selectWizardStep(page, 4)
  await page.getByRole('button', { name: '项目概览', exact: true }).click()

  await page.locator('main').getByRole('button', { name: '新翻译任务', exact: true }).click()
  await expect(page.getByRole('alertdialog')).toContainText('已有未完成翻译任务')
  await expect(page.getByTestId('confirm-modal-cancel')).toHaveText('继续当前任务')
  await expect(page.getByTestId('confirm-modal-confirm')).toHaveText('放弃草稿并新建')
  await page.getByTestId('confirm-modal-cancel').click()
  await expect(page.getByTestId('step-menu-toggle')).toContainText('判定输入')

  await page.getByRole('button', { name: '项目概览', exact: true }).click()
  await page.locator('main').getByRole('button', { name: '新翻译任务', exact: true }).click()
  await page.getByTestId('confirm-modal-confirm').click()
  await expect(page.getByTestId('step-menu-toggle')).toContainText('项目资料')
  await expect(page.getByRole('heading', { name: '新翻译任务', exact: true })).toBeVisible()
})


test('new translation task redirects to the active multilingual task without creating another run', async ({ page, request }) => {
  const projectName = `E2E Running Translation Redirect ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'lifecycle', description: 'Running task redirect regression.' },
  }).then((response) => response.json())
  const source = await request.post(`${baseURL}/api/projects/${project.id}/files?kind=language_table`, {
    multipart: {
      file: {
        name: 'running-task-source.xlsx',
        mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        buffer: fs.readFileSync(sourceWorkbook),
      },
    },
  }).then((response) => response.json())
  for (const [kind, language] of [['translation', 'en'], ['qa', 'ko']]) {
    const created = await request.post(`${baseURL}/api/runs`, {
      data: {
        project_id: project.id,
        kind,
        language,
        input_artifact_id: source.id,
        task_origin: kind === 'qa' ? 'translation_continuation' : 'translation_run',
        translation_task_id: 'task-running-multilingual',
      },
    })
    expect(created.ok()).toBeTruthy()
  }

  const beforeRuns = await request.get(`${baseURL}/api/runs?project_id=${project.id}`).then((response) => response.json())
  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.locator('.sidebar').getByRole('button', { name: /新翻译任务/ }).click()

  await expect(page.getByTestId('step-menu-toggle')).toContainText('QA 校对')
  await expect(page.getByTestId('multilingual-workflow-board').locator('[data-testid^="multilingual-language-"]')).toHaveCount(2)
  await expect(page.locator('.status')).toContainText('已带你回到当前任务')
  const afterRuns = await request.get(`${baseURL}/api/runs?project_id=${project.id}`).then((response) => response.json())
  expect(afterRuns).toHaveLength(beforeRuns.length)
})

test('redirecting to an externally active task clears a stale upload busy lock', async ({ page, request }) => {
  const projectName = `E2E Active Task Busy Reset ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'lifecycle', description: 'Active task redirect busy reset regression.' },
  }).then((response) => response.json())
  const source = await request.post(`${baseURL}/api/projects/${project.id}/files?kind=language_table`, {
    multipart: {
      file: {
        name: 'external-active-task-source.xlsx',
        mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        buffer: fs.readFileSync(sourceWorkbook),
      },
    },
  }).then((response) => response.json())

  let uploadRequested = false
  let uploadCompleted = false
  let releaseUpload!: () => void
  const uploadGate = new Promise<void>((resolve) => { releaseUpload = resolve })
  await page.route(`**/api/projects/${project.id}/files?kind=language_table`, async (route) => {
    uploadRequested = true
    await uploadGate
    await route.continue()
    uploadCompleted = true
  })

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.locator('main').getByRole('button', { name: '新翻译任务', exact: true }).click()
  await selectWizardStep(page, 4)
  await page.locator('label.upload-box', { hasText: '上传语言表' }).locator('input[type="file"]').setInputFiles(sourceWorkbook)
  await expect.poll(() => uploadRequested).toBeTruthy()
  await expect(page.locator('.inline-status.running')).toBeVisible()

  const externalRun = await request.post(`${baseURL}/api/runs`, {
    data: {
      project_id: project.id,
      kind: 'translation',
      language: 'en',
      input_artifact_id: source.id,
      task_origin: 'translation_run',
      translation_task_id: 'task-external-active',
    },
  })
  expect(externalRun.ok()).toBeTruthy()

  try {
    await page.locator('.sidebar').getByRole('button', { name: /新翻译任务/ }).click()
    await expect(page.getByTestId('step-menu-toggle')).toContainText('AI 翻译')
    await expect(page.locator('.inline-status.running')).toHaveCount(0)
    await expect(page.getByRole('button', { name: '暂停', exact: true })).toBeEnabled()
  } finally {
    releaseUpload()
  }
  await expect.poll(() => uploadCompleted).toBeTruthy()
  await expect(page.locator('.inline-status.running')).toHaveCount(0)
})

test('stale source upload cannot overwrite a replacement translation task', async ({ page, request }) => {
  const projectName = `E2E Source Upload Stale Guard ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'lifecycle', description: 'Source upload task race regression.' },
  }).then((response) => response.json())

  let uploadRequested = false
  let uploadCompleted = false
  let releaseUpload!: () => void
  const uploadGate = new Promise<void>((resolve) => { releaseUpload = resolve })
  await page.route(`**/api/projects/${project.id}/files?kind=language_table`, async (route) => {
    uploadRequested = true
    await uploadGate
    await route.continue()
    uploadCompleted = true
  })
  let analysisRequested = false
  let analysisCompleted = false
  let releaseAnalysis!: () => void
  const analysisGate = new Promise<void>((resolve) => { releaseAnalysis = resolve })
  await page.route(`**/api/projects/${project.id}/analyze`, async (route) => {
    analysisRequested = true
    await analysisGate
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ project, analysis: { summary: { parsed: 0, total: 0 }, language_table_candidates: [] } }),
    })
    analysisCompleted = true
  })

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.locator('main').getByRole('button', { name: '新翻译任务', exact: true }).click()
  await selectWizardStep(page, 4)
  await page.locator('label.upload-box', { hasText: '上传语言表' }).locator('input[type="file"]').setInputFiles(sourceWorkbook)
  await expect.poll(() => uploadRequested).toBeTruthy()

  await page.locator('.sidebar').getByRole('button', { name: /新翻译任务/ }).click()
  await page.getByTestId('confirm-modal-confirm').click()
  await expect(page.getByTestId('step-menu-toggle')).toContainText('项目资料')
  await expect(page.locator('.status')).toContainText('新的翻译任务已就绪')

  await selectWizardStep(page, 2)
  await page.getByRole('button', { name: '开始分析', exact: true }).click()
  await expect.poll(() => analysisRequested).toBeTruthy()
  await expect(page.locator('.inline-status.running')).toBeVisible()

  try {
    releaseUpload()
    await expect.poll(() => uploadCompleted).toBeTruthy()
    await expect(page.locator('.inline-status.running')).toBeVisible()
    await expect(page.locator('.status')).toContainText('正在读取项目资料并调用 AI 分析')
  } finally {
    releaseAnalysis()
  }
  await expect.poll(() => analysisCompleted).toBeTruthy()
  await selectWizardStep(page, 4)
  await expect(page.locator('.step-panel.active label.asset-select select')).toHaveValue('')
})

test('stale translation upload cannot attach a QA artifact to a replacement translation task', async ({ page, request }) => {
  const projectName = `E2E Translation Upload Stale Guard ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'lifecycle', description: 'Translation upload task race regression.' },
  }).then((response) => response.json())
  const source = await request.post(`${baseURL}/api/projects/${project.id}/files?kind=language_table`, {
    multipart: {
      file: {
        name: 'translation-upload-stale-source.xlsx',
        mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        buffer: fs.readFileSync(sourceWorkbook),
      },
    },
  }).then((response) => response.json())

  let uploadRequested = false
  let uploadCompleted = false
  let releaseUpload!: () => void
  const uploadGate = new Promise<void>((resolve) => { releaseUpload = resolve })
  await page.route(`**/api/projects/${project.id}/files?kind=final_workbook`, async (route) => {
    uploadRequested = true
    await uploadGate
    await route.continue()
    uploadCompleted = true
  })

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.locator('main').getByRole('button', { name: '新翻译任务', exact: true }).click()
  await selectWizardStep(page, 4)
  await page.locator('.step-panel.active label.asset-select select').selectOption(source.id)
  await selectWizardStep(page, 8)
  await page.locator('label.upload-box', { hasText: '上传译文' }).locator('input[type="file"]').setInputFiles(sourceWorkbook)
  await expect.poll(() => uploadRequested).toBeTruthy()

  await page.locator('.sidebar').getByRole('button', { name: /新翻译任务/ }).click()
  await page.getByTestId('confirm-modal-confirm').click()
  await expect(page.getByTestId('step-menu-toggle')).toContainText('项目资料')
  await expect(page.locator('.status')).toContainText('新的翻译任务已就绪')

  releaseUpload()
  await expect.poll(() => uploadCompleted).toBeTruthy()
  await expect(page.locator('.status')).toContainText('新的翻译任务已就绪')
  await expect(page.locator('.inline-status.running')).toHaveCount(0)
  await page.getByRole('button', { name: '项目概览', exact: true }).click()
  await page.getByRole('button', { name: '校对', exact: true }).click()
  await expect(page.getByTestId('qa-outcome-panel').locator('.qa-current-grid')).toContainText('未选择')
  await expect(page.getByTestId('qa-outcome-panel').locator('.qa-current-grid')).not.toContainText(fileName(sourceWorkbook))
})

test('stale source inspection cannot overwrite a replacement translation task', async ({ page, request }) => {
  const projectName = `E2E Translation Stale Guard ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'lifecycle', description: 'Same-project task race regression.' },
  }).then((response) => response.json())
  const source = await request.post(`${baseURL}/api/projects/${project.id}/files?kind=language_table`, {
    multipart: {
      file: {
        name: 'stale-guard-source.xlsx',
        mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        buffer: fs.readFileSync(sourceWorkbook),
      },
    },
  }).then((response) => response.json())

  await page.route(`**/api/projects/${project.id}/artifacts/${source.id}/translation-readiness?**`, async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1200))
    await route.continue()
  })
  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.locator('main').getByRole('button', { name: '新翻译任务', exact: true }).click()
  await selectWizardStep(page, 4)
  await page.locator('.step-panel.active label.asset-select select').selectOption(source.id)
  await page.getByRole('button', { name: '项目概览', exact: true }).click()
  await page.locator('main').getByRole('button', { name: '新翻译任务', exact: true }).click()
  await page.getByTestId('confirm-modal-confirm').click()
  await page.waitForTimeout(1500)
  await expect(page.getByTestId('step-menu-toggle')).toContainText('项目资料')
  await selectWizardStep(page, 4)
  await expect(page.locator('.step-panel.active label.asset-select select')).toHaveValue('')
  await expect(page.locator('.translation-readiness-box')).toContainText('等待语言表')
})

test('stale legacy task response cannot overwrite a replacement translation task', async ({ page, request }) => {
  const projectName = `E2E Legacy Translation Stale Guard ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'lifecycle', description: 'Legacy task race regression.' },
  }).then((response) => response.json())
  const source = await request.post(`${baseURL}/api/projects/${project.id}/files?kind=language_table`, {
    multipart: {
      file: {
        name: 'legacy-stale-guard-source.xlsx',
        mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        buffer: fs.readFileSync(sourceWorkbook),
      },
    },
  }).then((response) => response.json())
  const legacyRun = await request.post(`${baseURL}/api/runs`, {
    data: {
      project_id: project.id,
      kind: 'translation',
      language: 'en',
      input_artifact_id: source.id,
      batch_size: 2,
      task_code: 'T',
    },
  }).then((response) => response.json())
  await request.post(`${baseURL}/api/runs/${legacyRun.id}/translate/cancel`)

  let targetsRequested = 0
  await page.route(`**/api/projects/${project.id}/artifacts/${source.id}/translation-targets`, async (route) => {
    targetsRequested += 1
    await new Promise((resolve) => setTimeout(resolve, 1200))
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        artifact_id: source.id,
        label: source.label,
        supported_file: true,
        source_detected: true,
        detected_languages: ['ko'],
        suggested_language: 'ko',
        reason: 'detected',
      }),
    })
  })

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.locator('main').getByRole('button', { name: '新翻译任务', exact: true }).click()
  await expect(page.getByRole('alertdialog')).toContainText('已有未完成翻译任务')
  await page.getByTestId('confirm-modal-cancel').click()
  await expect.poll(() => targetsRequested).toBeGreaterThan(0)

  await page.getByRole('button', { name: '项目概览', exact: true }).click()
  await page.locator('main').getByRole('button', { name: '新翻译任务', exact: true }).click()
  await expect(page.getByRole('alertdialog')).toContainText('已有未完成翻译任务')
  await page.getByTestId('confirm-modal-confirm').click()

  await page.waitForTimeout(1500)
  await expect(page.getByTestId('step-menu-toggle')).toContainText('项目资料')
  await expect(page.locator('.status')).toContainText('新的翻译任务已就绪')
})

test('stale project analysis cannot attach candidates to a replacement translation task', async ({ page, request }) => {
  const projectName = `E2E Analysis Stale Guard ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'lifecycle', description: 'Analysis task race regression.' },
  }).then((response) => response.json())
  const source = await request.post(`${baseURL}/api/projects/${project.id}/files?kind=language_table`, {
    multipart: {
      file: {
        name: 'analysis-stale-guard-source.xlsx',
        mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        buffer: fs.readFileSync(sourceWorkbook),
      },
    },
  }).then((response) => response.json())
  const projectSnapshot = await request.get(`${baseURL}/api/projects/${project.id}`).then((response) => response.json())

  let analysisRequested = 0
  await page.route(`**/api/projects/${project.id}/analyze`, async (route) => {
    analysisRequested += 1
    await new Promise((resolve) => setTimeout(resolve, 1200))
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        project: projectSnapshot,
        analysis: {
          summary: { parsed: 1, total: 1 },
          language_table_candidates: [{ artifact_id: source.id }],
        },
      }),
    })
  })

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.locator('main').getByRole('button', { name: '新翻译任务', exact: true }).click()
  await selectWizardStep(page, 2)
  await page.getByRole('button', { name: '开始分析', exact: true }).click()
  await expect.poll(() => analysisRequested).toBeGreaterThan(0)

  await page.locator('.sidebar').getByRole('button', { name: /新翻译任务/ }).click()
  await expect(page.getByRole('alertdialog')).toContainText('已有未完成翻译任务')
  await page.getByTestId('confirm-modal-confirm').click()

  await page.waitForTimeout(1500)
  await expect(page.getByTestId('step-menu-toggle')).toContainText('项目资料')
  await expect(page.getByRole('alertdialog')).toHaveCount(0)
  await expect(page.locator('.status')).toContainText('新的翻译任务已就绪')
})

test('stale glossary extraction cannot hydrate a replacement translation task', async ({ page, request }) => {
  const projectName = `E2E Glossary Stale Guard ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'lifecycle', description: 'Glossary task race regression.' },
  }).then((response) => response.json())
  const source = await request.post(`${baseURL}/api/projects/${project.id}/files?kind=language_table`, {
    multipart: {
      file: {
        name: 'glossary-stale-source.xlsx',
        mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        buffer: fs.readFileSync(sourceWorkbook),
      },
    },
  }).then((response) => response.json())

  let extractionResolved = false
  await page.route(`**/api/projects/${project.id}/artifacts/${source.id}/translation-readiness?**`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        artifact_id: source.id,
        label: source.label,
        target_language: 'en',
        source_rows: 2,
        translated_rows: 0,
        empty_target_rows: 2,
        cjk_target_rows: 0,
        needs_translation: true,
        ready_for_translation: true,
        ready_for_qa: false,
        reason: 'target_column_empty',
        batch_size: 90,
        estimated_batches: 1,
        input_mode: 'needs_translation',
        next_step: 5,
      }),
    })
  })
  await page.route(`**/api/projects/${project.id}/glossary/extract`, async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1200))
    extractionResolved = true
    const now = new Date().toISOString()
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        run: { id: 'run-stale-glossary', project_id: project.id, kind: 'glossary', language: 'en', status: 'passed', created_at: now, updated_at: now, metadata: {} },
        artifacts: [{ id: 'artifact-stale-glossary', project_id: project.id, run_id: 'run-stale-glossary', kind: 'glossary_final', label: 'stale glossary', path: 'stale.xlsx', created_at: now }],
        glossary_backfill: { candidates: 1, unique_candidates: 1, pending_confirmation: 1 },
      }),
    })
  })
  await page.route(`**/api/projects/${project.id}/glossary/batches?**`, async (route) => {
    const batch = {
      id: 'batch-stale-glossary',
      project_id: project.id,
      label: 'stale batch',
      status: 'pending',
      language: 'en',
      source_artifact_id: source.id,
      counts: { pending: 1, accepted: 0, rejected: 0 },
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(extractionResolved ? {
        batches: [batch],
        active_batch: batch,
        candidates: [{
          id: 'candidate-stale-glossary', batch_id: batch.id, project_id: project.id,
          term_key: 'stale', source: '旧任务术语', target: 'Stale', target_alt: '', language: 'en',
          category: 'stale', note: 'must not hydrate replacement task', status: 'pending',
        }],
      } : { batches: [], active_batch: null, candidates: [] }),
    })
  })

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.locator('main').getByRole('button', { name: '新翻译任务', exact: true }).click()
  await selectWizardStep(page, 4)
  await page.locator('.step-panel.active label.asset-select select').selectOption(source.id)
  await selectWizardStep(page, 5)
  await page.getByRole('button', { name: '扫描候选' }).click()
  await expect(inlineStatus(page, '正在从待翻译语言表扫描术语候选')).toBeVisible()
  await page.getByRole('button', { name: '项目概览', exact: true }).click()
  await page.locator('main').getByRole('button', { name: '新翻译任务', exact: true }).click()
  await page.getByTestId('confirm-modal-confirm').click()

  await page.waitForTimeout(1700)
  await expect(page.getByTestId('step-menu-toggle')).toContainText('项目资料')
  await expect(page.locator('.status')).toContainText('新的翻译任务已就绪')
  await selectWizardStep(page, 5)
  await expect(page.locator('.pending-term-table')).toHaveCount(0)
})


test('deleting the active project refreshes the list and lands on a surviving project', async ({ page, request }) => {
  const keepName = `E2E Delete Keep ${Date.now()}`
  const removeName = `E2E Delete Active ${Date.now()}`
  await request.post(`${baseURL}/api/projects`, {
    data: { name: keepName, type: 'delete-e2e', description: 'Survives the deletion.' },
  })
  await request.post(`${baseURL}/api/projects`, {
    data: { name: removeName, type: 'delete-e2e', description: 'Deleted while active.' },
  })

  await page.goto(baseURL)
  const removeButton = page.getByRole('button', { name: removeName })
  await expect(removeButton).toBeVisible({ timeout: 15000 })
  await removeButton.click()
  await expect(page.getByRole('heading', { name: removeName })).toBeVisible()

  // Long-press guard: hold pointer down on the project item; after 850ms the delete modal opens.
  await removeButton.hover()
  await page.mouse.down()
  await expect(page.getByRole('alertdialog')).toBeVisible({ timeout: 5000 })
  await page.mouse.up()

  await expect(page.getByRole('heading', { name: '删除项目' })).toBeVisible()
  await page.getByRole('button', { name: '确认删除' }).click()

  // The status toast is transient (background polling overwrites it), so assert durable outcomes.
  await expect(page.getByRole('alertdialog')).toHaveCount(0, { timeout: 15000 })
  await expect(page.getByRole('button', { name: removeName })).toHaveCount(0, { timeout: 15000 })
  await expect(page.getByRole('button', { name: keepName })).toBeVisible()
  await expect(page.getByRole('heading', { name: removeName })).toHaveCount(0)
  // App must land on another project view, not a dead/blank state.
  await expect(page.getByRole('heading', { name: keepName })).toBeVisible({ timeout: 15000 })
  await expect(page.locator('.stat-grid')).toContainText('语言包任务')
})

test('user can complete the EN localization workflow from project tabs', async ({ page, request }) => {
  await request.patch(`${baseURL}/api/settings`, {
    data: {
      provider: 'test-fake',
      protocol: 'chat-completions',
      api_key: '',
      model: 'test-fake-localization',
      batch_size: 24,
    },
  })

  const projectName = `E2E 小小战机 ${Date.now()}`

  await page.goto(baseURL)
  await expect(page.getByRole('heading', { name: '本地化工作台' })).toBeVisible()

  await page.locator('.new-project-btn').click()
  await expect(page.getByRole('heading', { name: '新建本地化项目' })).toBeVisible()
  await page.getByPlaceholder('例如：星际边境 / 机甲纪元').fill(projectName)
  await page.locator('.modal select').selectOption({ label: '科幻 SLG' })
  await page.getByPlaceholder('目标用户、题材、语气要求').fill('来源：E2E 合成语言表。目标语言：英语 EN。风格：短句准确。')
  await page.getByRole('button', { name: '创建' }).click()

  await expect(page.getByRole('heading', { name: projectName })).toBeVisible({ timeout: 15000 })
  await expect(page.locator('.stat-grid')).toContainText('语言包任务')
  await expect(page.locator('.stat-grid')).toContainText('公告任务')
  await expect(page.locator('.stat-grid')).toContainText('已归档文本')
  await expect(page.getByRole('button', { name: projectName })).toBeVisible()

  await page.locator('summary', { hasText: '资料与重新分析' }).click()
  const materialCard = page.locator('.material-card')
  await materialCard.getByLabel('题材/分类').fill('飞行射击')
  await materialCard.getByLabel('投进去的信息 / 本次分析补充').fill('来源：synthetic-language.xlsx\n目标语言：英语 EN\n风格：UI 短句清晰，术语统一。')
  await materialCard.getByRole('button', { name: '保存资料说明' }).click()
  await expect(page.getByText('项目元信息已保存')).toBeVisible()

  await materialCard.getByLabel('投进去的信息 / 本次分析补充').fill('小小战机：飞行射击项目，资源、战机、任务、奖励术语需统一。')
  await materialCard.getByRole('button', { name: '重新分析项目' }).click()
  await expect(page.getByText(/项目(提示词已生成|分析完成)/)).toBeVisible({ timeout: 20000 })
  const promptView = page.locator('.reference-card pre').first()
  await expect(promptView).toContainText('\u5fc5\u987b\u4fdd\u7559')
  await expect(promptView).not.toContainText('JSONL')
  await page.locator('.reference-card .card-actions button').nth(1).click()
  const manualPrompt = '\u4eba\u5de5\u4fee\u8ba2\u9879\u76ee\u63d0\u793a\u8bcd\uff1a\u4fdd\u6301 UI \u7b80\u6d01\uff0c\u672f\u8bed\u4e25\u683c\u6309\u9879\u76ee\u8868\u6267\u884c\u3002'
  await page.locator('textarea.prompt-editor').fill(manualPrompt)
  await page.locator('.reference-card .row-actions .btn-primary').click()
  await expect(page.locator('textarea.prompt-editor')).toHaveCount(0)
  const promptProjects = await request.get(`${baseURL}/api/projects`).then((response) => response.json())
  const promptSavedProject = promptProjects.find((item: { name: string }) => item.name === projectName)
  expect(promptSavedProject.prompt_text).toBe(manualPrompt)
  expect(promptSavedProject.profile.prompts_by_language.en).toBe(manualPrompt)
  expect(promptSavedProject.profile.display_prompts_by_language.en).toBe(manualPrompt)

  await page.getByRole('button', { name: '术语表', exact: true }).click()
  await page.getByTestId('manual-glossary-tools').locator('summary').click()
  await page.locator('input[name="term_key"]').fill('T-1')
  await page.locator('input[name="source"]').fill('战机')
  await page.locator('input[name="target"]').fill('Warplane')
  await page.locator('input[name="category"]').fill('unit')
  await page.locator('input[name="note"]').fill('E2E manual glossary assertion')
  await page.getByRole('button', { name: '+ 新增 EN' }).click()
  await expect(inlineStatus(page, '词条已新增')).toBeVisible()
  await page.getByTestId('glossary-search').fill('战机')
  const glossaryRow = page.locator('.glossary-table tbody tr').first()
  await expect(glossaryRow.getByText('战机')).toBeVisible()
  await expect(glossaryRow.getByText('Warplane')).toBeVisible()
  await glossaryRow.getByRole('button', { name: '编辑' }).click()
  await glossaryRow.locator('input').nth(2).fill('Fighter Jet')
  await glossaryRow.getByRole('button', { name: '保存' }).click()
  await expect(inlineStatus(page, '词条已保存')).toBeVisible()
  await expect(glossaryRow.getByText('Fighter Jet')).toBeVisible()

  const projects = await request.get(`${baseURL}/api/projects`)
  const project = (await projects.json()).find((item: { name: string }) => item.name === projectName)
  expect(project).toBeTruthy()
  const exportedGlossary = await request.get(`${baseURL}/api/projects/${project.id}/glossary/export?format=json`)
  const exportedTerms = (await exportedGlossary.json()).terms
  expect(exportedTerms).toContainEqual(expect.objectContaining({ source: '战机', target: 'Fighter Jet', target_alt: '' }))
  expect(Object.keys(exportedTerms[0])).not.toContain('source_type')
  expect(Object.keys(exportedTerms[0])).not.toContain('confirmed')

  await page.getByRole('button', { name: '翻译', exact: true }).click()
  await page.locator('label.upload-box', { hasText: '上传待翻译表格' }).locator('input[type="file"]').setInputFiles(sourceWorkbook)
  await expect(page.locator('.selected-input span', { hasText: fileStem(sourceWorkbook) })).toBeVisible({ timeout: 15000 })
  await expect(page.getByTestId('formal-translate')).toBeEnabled()
  await page.getByTestId('formal-translate').click()
  await expect(inlineStatus(page, 'EN 翻译和 QA 已通过，最终产物已归档。')).toBeVisible({ timeout: 120000 })
  await expect(page.getByText('最近翻译任务')).toBeVisible()
  await expect(page.getByText('已通过').first()).toBeVisible()

  await page.getByRole('button', { name: '校对', exact: true }).click()
  await expect(page.locator('.qa-outcome-panel')).toContainText('QA 已通过')
  await expect(page.locator('.qa-outcome-panel')).toContainText('已译语言表（EN）')
  await expect(page.locator('.qa-outcome-panel')).not.toContainText('QA final workbook')
  await expect(page.locator('.qa-outcome-panel')).not.toContainText('result_en')
  await expect(page.locator('.qa-outcome-panel')).toContainText('上一翻译结果')

  await page.getByRole('button', { name: '交付', exact: true }).click()
  await expect(page.locator('.card-title .left', { hasText: '最终交付' })).toBeVisible()
  await expect(page.locator('.delivery-card').first()).toBeVisible({ timeout: 30000 })
  await expect(page.getByText('任务进度', { exact: true })).toBeVisible()
  await expect(page.getByText('交付结果', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '生成交付文件' }).click()
  await expect(inlineStatus(page, '最终交付已生成：2 个文件')).toBeVisible({ timeout: 30000 })
  await expect(page.getByRole('link', { name: '下载最终译文' })).toBeVisible()
  await expect(page.getByRole('link', { name: '下载修改记录' })).toBeVisible()
  await page.locator('main').getByRole('button', { name: '新翻译任务', exact: true }).click()
  await expect(page.getByTestId('step-menu-toggle')).toContainText('项目资料')
  await expect(page.locator('.workflow-file-link')).toHaveCount(0)
})

test('real project formal translation is blocked without configured API credential', async ({ page, request }) => {
  await request.patch(`${baseURL}/api/settings`, {
    data: { provider: 'openai', protocol: 'responses', api_key: '', model: 'gpt-5.5', batch_size: 24 },
  })
  const projectName = `小小战机 UI 阻断 ${Date.now()}`
  await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'QA', description: '真实项目缺少 API 密钥时必须阻断正式翻译。' },
  })

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.getByRole('button', { name: '翻译', exact: true }).click()
  await page.locator('label.upload-box', { hasText: '上传待翻译表格' }).locator('input[type="file"]').setInputFiles(sourceWorkbook)
  await expect(page.locator('.selected-input span', { hasText: fileStem(sourceWorkbook) })).toBeVisible({ timeout: 15000 })
  await expect(page.getByTestId('formal-translate')).toBeDisabled()
  await expect(page.locator('.warn-line', { hasText: 'API' })).toBeVisible()
  await expect(page.locator('.warn-line', { hasText: '设置' })).toBeVisible()
})

test('announcement AI translation shows API reminder when provider is not configured', async ({ page, request }) => {
  await request.patch(`${baseURL}/api/settings`, {
    data: { provider: 'openai', protocol: 'responses', api_key: '', model: 'gpt-5.5', batch_size: 24 },
  })
  const projectName = `E2E Announcement API Reminder ${Date.now()}`
  const createResponse = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: '公告', description: '公告翻译缺少 API 密钥时需要给人话提醒。' },
  })
  const project = await createResponse.json()
  await request.post(`${baseURL}/api/projects/${project.id}/files?kind=asset`, {
    multipart: {
      file: {
        name: 'api_reminder_notice.txt',
        mimeType: 'text/plain',
        buffer: Buffer.from('本次更新新增活动和奖励。', 'utf-8'),
      },
    },
  })

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.getByRole('button', { name: /公告翻译/ }).click()
  await page.locator('.check-row', { hasText: 'api_reminder_notice.txt' }).locator('input').check()
  await page.getByRole('button', { name: '创建公告任务' }).click()
  await expect(page.locator('.panel-title', { hasText: '约束来源' })).toBeVisible({ timeout: 20000 })
  await selectWizardStep(page, 7, '.announcement-wizard')
  await expect(page.locator('.panel-title', { hasText: 'AI 翻译' })).toBeVisible()
  await expect(page.locator('.warn-line', { hasText: '需要先配置 API' })).toBeVisible()
  await expect(page.locator('.warn-line', { hasText: '设置' })).toBeVisible()
  await expect(page.getByRole('button', { name: /^AI\s?\u7ffb\u8bd1$/ })).toBeDisabled()
})

test('translation workflow keeps preparation steps available and gates processing steps', async ({ page, request }) => {
  const projectName = `E2E Compact Workflow ${Date.now()}`
  await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'workflow-ui', description: 'Compact workflow navigation smoke.' },
  })

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.getByRole('button', { name: '新翻译任务', exact: true }).click()

  const stepMenu = page.getByTestId('step-menu-toggle')
  await expect(stepMenu).toContainText(/步骤 1\/9\s*·\s*项目资料/)
  await expect(page.locator('.workflow-substeps')).toBeHidden()
  await expect(page.locator('.panel-title')).toContainText('项目资料')
  await expect(page.locator('.panel-desc')).toHaveText('补充本次翻译依据。')

  const expectedSteps = [
    ['项目资料', '补充本次翻译依据。'],
    ['AI 分析', '确认项目信息与分析结果。'],
    ['术语表', '导入已确认术语，可跳过。'],
    ['判定输入', '上传语言表，系统自动分流。'],
    ['术语候选', '扫描并确认术语候选。'],
    ['目标语言', '选择本次翻译语言。'],
    ['AI 翻译', '确认输入并开始翻译。'],
    ['QA 校对', '检查译文并处理问题。'],
    ['交付', '生成并下载交付文件。'],
  ]
  for (let index = 1; index <= 6; index += 1) {
    await page.getByTestId('step-menu-toggle').click()
    await expect(page.getByTestId(`step-${index}`)).toBeVisible()
    await page.getByTestId(`step-${index}`).click()
    await expect(page.locator('.workflow-substeps')).toBeHidden()
    await expect(page.locator('.panel-title, .workflow-step-head h3').first()).toContainText(expectedSteps[index - 1][0])
    await expect(page.locator('.panel-desc, .workflow-step-head p').first()).toHaveText(expectedSteps[index - 1][1])
    if (index === 2) {
      await expect(page.locator('.analysis-summary')).toBeVisible()
      await expect(page.locator('.analysis-details')).not.toHaveAttribute('open', '')
      await expect(page.locator('.analysis-details .status-grid')).toBeHidden()
    }
  }

  await page.getByTestId('step-menu-toggle').click()
  for (const index of [7, 8, 9]) {
    await expect(page.getByTestId(`step-${index}`)).toBeVisible()
    await expect(page.getByTestId(`step-${index}`)).toBeDisabled()
  }

  await expect(page.getByText('完整语言表不要放这里')).toHaveCount(0)
})

test('new translation task exposes the full supported language set', async ({ page, request }) => {
  const projectName = `E2E Full Languages ${Date.now()}`
  const fixtureDir = fs.mkdtempSync(path.join(os.tmpdir(), 'lws-full-languages-'))
  const sourceWorkbookWithVietnamese = path.join(fixtureDir, 'full-languages-source.xlsx')
  execFileSync('python', ['-c', `
from openpyxl import Workbook
import sys
wb = Workbook()
ws = wb.active
ws.title = "Language"
ws.append(["ID", "CN", "EN", "VI"])
ws.append([1, "\\u9886\\u53d6\\u5956\\u52b1", "", ""])
wb.save(sys.argv[1])
wb.close()
`, sourceWorkbookWithVietnamese])
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'language-ui', description: 'Full language selector smoke.' },
  }).then((response) => response.json())
  const source = await request.post(`${baseURL}/api/projects/${project.id}/files?kind=language_table`, {
    multipart: {
      file: {
        name: fileName(sourceWorkbookWithVietnamese),
        mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        buffer: fs.readFileSync(sourceWorkbookWithVietnamese),
      },
    },
  }).then((response) => response.json())
  await request.patch(`${baseURL}/api/settings`, {
    data: {
      provider: 'test-fake',
      protocol: 'chat-completions',
      api_key: '',
      model: 'test-fake-localization',
      batch_size: 24,
    },
  })

  const expectedManualLanguages = ['en', 'ko', 'ja', 'vn']
  let queuePayload: Record<string, unknown> | null = null
  await page.route(`**/api/projects/${project.id}/multilingual/translate/start`, async (route) => {
    queuePayload = route.request().postDataJSON()
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        project_id: project.id,
        input_artifact_id: source.id,
        overall_status: 'pending',
        active_job_id: null,
        languages: expectedManualLanguages.map((language) => ({ language, visible_language: language === 'vn' ? 'VN' : language.toUpperCase(), run_id: null, translation_run_id: null, qa_run_id: null, status: 'pending', step: 'pending', can_continue: false, error: '', progress: {}, quality_summary: {}, large_text: {} })),
        created_run_ids: [],
        queue_started: true,
      }),
    })
  })

  const languageRefresh = page.waitForResponse((response) => response.url().endsWith('/api/languages') && response.ok())
  const settingsRefresh = page.waitForResponse((response) => response.url().endsWith('/api/settings') && response.ok())
  await page.goto(baseURL)
  await Promise.all([languageRefresh, settingsRefresh])
  const normalizedVietnameseCodes = await page.evaluate(async () => {
    const { normalizeLanguageCode } = await import('/src/languages.ts')
    return {
      vn: normalizeLanguageCode('vn'),
      vi: normalizeLanguageCode('vi'),
      vie: normalizeLanguageCode('vie'),
    }
  })
  expect(normalizedVietnameseCodes).toEqual({ vn: 'vn', vi: 'vn', vie: 'vn' })
  await page.getByRole('button', { name: projectName }).click()
  await page.getByRole('button', { name: '新翻译任务', exact: true }).click()
  await selectWizardStep(page, 4)
  const targetsResponse = page.waitForResponse((response) => response.url().includes(`/artifacts/${source.id}/translation-targets`) && response.ok())
  const readinessResponse = page.waitForResponse((response) => response.url().includes(`/artifacts/${source.id}/translation-readiness`) && response.ok())
  await page.locator('.step-panel.active label.asset-select select').selectOption(source.id)
  await Promise.all([targetsResponse, readinessResponse])
  await selectWizardStep(page, 6)

  for (const label of [
    'EN 英语',
    'KR 韩语',
    'JP 日语',
    'FR 法语',
    'DE 德语',
    'RU 俄语',
    'IT 意大利语',
    'ES 西班牙语',
    'PT 葡萄牙语',
    'TR 土耳其语',
    'ID 印尼语',
    'TH 泰语',
    'VN 越南语',
  ]) {
    await expect(page.getByRole('button', { name: label })).toBeVisible()
  }
  await expect(page.getByRole('button', { name: 'AR 阿拉伯语' })).toHaveCount(0)
  await expect(page.getByText('其他语言未开放')).toHaveCount(0)
  const enButton = page.getByRole('button', { name: /EN 英语/ })
  const krButton = page.getByRole('button', { name: /KR 韩语/ })
  const jpButton = page.getByRole('button', { name: /JP 日语/ })
  const vnButton = page.getByRole('button', { name: /VN 越南语/ })
  await expect(vnButton).toHaveClass(/selected/)
  await krButton.click()
  await jpButton.click()
  await vnButton.click()
  await expect(vnButton).not.toHaveClass(/selected/)
  const vnReadiness = page.waitForResponse((response) => response.url().includes(`/artifacts/${source.id}/translation-readiness`) && response.url().includes('language=vn') && response.ok())
  await vnButton.click()
  await vnReadiness
  await expect(enButton).toHaveClass(/selected/)
  await expect(krButton).toHaveClass(/selected/)
  await expect(jpButton).toHaveClass(/selected/)
  await expect(vnButton).toHaveClass(/selected/)
  await expect(vnButton).toHaveClass(/current/)
  await selectWizardStep(page, 7)
  const startTranslation = page.getByTestId('multilingual-translate')
  await expect(startTranslation).toBeEnabled()
  await startTranslation.click()
  await expect.poll(() => queuePayload).not.toBeNull()
  expect(queuePayload).toMatchObject({ input_artifact_id: source.id, languages: expectedManualLanguages })
  const submittedLanguages = (queuePayload as { languages: string[] }).languages
  expect(submittedLanguages).toContain('vn')
  expect(submittedLanguages).not.toContain('vi')
  expect(submittedLanguages).not.toContain('vie')
})

test('EN glossary candidate review exposes one translation column', async ({ page, request }) => {
  const projectName = `E2E Single EN Candidate ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'glossary', description: 'Single EN candidate column regression.' },
  }).then((response) => response.json())
  const source = await request.post(`${baseURL}/api/projects/${project.id}/files?kind=language_table`, {
    multipart: {
      file: {
        name: fileName(sourceWorkbook),
        mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        buffer: fs.readFileSync(sourceWorkbook),
      },
    },
  }).then((response) => response.json())
  const batch = {
    id: 'batch-single-en',
    project_id: project.id,
    label: 'Single EN candidates',
    status: 'pending',
    language: 'en',
    source_artifact_id: source.id,
    counts: { pending: 1, accepted: 0, rejected: 0 },
  }
  await page.route(`**/api/projects/${project.id}/glossary/batches?**`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        batches: [batch],
        active_batch: batch,
        candidates: [{
          id: 'candidate-single-en',
          batch_id: batch.id,
          project_id: project.id,
          term_key: 'term-1',
          source: '战机',
          target: 'Warplane',
          target_alt: 'Fighter',
          language: 'en',
          category: 'unit',
          note: 'legacy alternate must stay hidden',
          status: 'pending',
        }],
      }),
    })
  })

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.locator('main').getByRole('button', { name: '新翻译任务', exact: true }).click()
  await selectWizardStep(page, 4)
  await page.locator('.step-panel.active label.asset-select select').selectOption(source.id)
  await selectWizardStep(page, 5)

  const table = page.locator('.pending-term-table')
  await expect(table).toBeVisible()
  await expect(table.locator('thead')).not.toContainText('EN2')
  await expect(table.locator('thead th')).toHaveCount(7)
  const row = table.locator('tbody tr').first()
  await expect(row.locator('td')).toHaveCount(7)
  await row.getByRole('button', { name: '编辑' }).click()
  await expect(row.locator('input')).toHaveCount(5)
})

test('language table headers auto-select targets and start one multilingual queue', async ({ page, request }) => {
  await request.patch(`${baseURL}/api/settings`, {
    data: {
      provider: 'test-fake',
      protocol: 'chat-completions',
      api_key: '',
      model: 'test-fake-localization',
      batch_size: 24,
    },
  })
  const projectName = `E2E Header Languages ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'QA', description: 'Header language auto-selection.' },
  }).then((response) => response.json())
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'lws-header-languages-'))
  const workbook = path.join(root, 'header-languages.xlsx')
  execFileSync('python', ['-c', `
from openpyxl import Workbook
import sys
wb = Workbook()
ws = wb.active
ws.title = "Sheet1"
ws.append(["ID", "CN", "EN", "IDN", "DE", "FR", "ES", "PT", "RU", "IT", "TR", "TH", "VI"])
ws.append([1, "领取奖励", "", "", "", "", "", "", "", "", "", "", ""])
wb.save(sys.argv[1])
wb.close()
`, workbook])
  const artifact = await request.post(`${baseURL}/api/projects/${project.id}/files?kind=language_table`, {
    multipart: {
      file: {
        name: fileName(workbook),
        mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        buffer: fs.readFileSync(workbook),
      },
    },
  }).then((response) => response.json())

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.locator('.sidebar').getByRole('button', { name: /新翻译任务/ }).click()
  await selectWizardStep(page, 4)
  await page.locator('.step-panel.active label.asset-select select').selectOption(artifact.id)
  await selectWizardStep(page, 6)
  await expect(page.locator('.step-panel.active .lang-chip.selected')).toHaveCount(11)

  const expectedLanguages = ['en', 'fr', 'de', 'ru', 'it', 'es', 'pt', 'tr', 'idn', 'th', 'vn']
  let queuePayload: Record<string, unknown> | null = null
  await page.route(`**/api/projects/${project.id}/multilingual/translate/start`, async (route) => {
    queuePayload = route.request().postDataJSON()
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        project_id: project.id,
        input_artifact_id: artifact.id,
        overall_status: 'pending',
        active_job_id: null,
        languages: expectedLanguages.map((language) => ({ language, visible_language: language.toUpperCase(), run_id: null, translation_run_id: null, qa_run_id: null, status: 'pending', step: 'pending', can_continue: false, error: '', progress: {}, quality_summary: {}, large_text: {} })),
        created_run_ids: [],
        queue_started: true,
      }),
    })
  })
  await selectWizardStep(page, 7)
  await page.getByTestId('multilingual-translate').click()

  expect(queuePayload).toMatchObject({ input_artifact_id: artifact.id, languages: expectedLanguages })
})


test('multilingual workflow separates structural reruns from deliverable QA issues', async ({ page }) => {
  await page.goto(baseURL)
  const result = await page.evaluate(async () => {
    const { multilingualWorkflowItems, shouldAutoAdvanceTranslationRun } = await import('/src/domain/translationFlow.ts')
    const sourceId = 'art_source'
    const makeRun = (id: string, language: string, status: string, metadata: Record<string, unknown>) => ({
      id,
      project_id: 'proj_multi',
      kind: 'translation',
      language,
      status,
      created_at: `2026-07-13T00:00:0${id.length}+00:00`,
      updated_at: `2026-07-13T00:00:0${id.length}+00:00`,
      metadata: { input_artifact_id: sourceId, task_origin: 'translation_run', ...metadata },
    })
    const runs = [
      makeRun('run_en', 'en', 'passed', { quality_summary: { passed: true, hard_errors: 0 } }),
      makeRun('run_it', 'it', 'failed', { quality: { rows_scanned: 0, issue_counts: { workbook_scan_empty: 1 } }, quality_summary: { passed: false, hard_errors: 2 } }),
      makeRun('run_fr', 'fr', 'failed', { quality: { rows_scanned: 2, issue_counts: { placeholder_mismatch: 1 } }, quality_summary: { passed: false, hard_errors: 1 } }),
    ] as any[]
    const project = {
      id: 'proj_multi',
      runs,
      artifacts: runs.map((run) => ({ id: `art_${run.language}`, project_id: 'proj_multi', run_id: run.id, kind: 'qa_final_workbook', exists: true })),
    } as any
    return {
      states: multilingualWorkflowItems(project, ['en', 'it', 'fr'], sourceId).map((item: any) => [item.code, item.state, item.recovery]),
      singleAutoAdvance: shouldAutoAdvanceTranslationRun(runs[0]),
      multiAutoAdvance: shouldAutoAdvanceTranslationRun({ ...runs[0], metadata: { ...runs[0].metadata, multilingual_queue: true } }),
    }
  })

  expect(result.states).toEqual([
    ['en', 'ready', 'none'],
    ['it', 'blocked', 'translation'],
    ['fr', 'issues', 'none'],
  ])
  expect(result.singleAutoAdvance).toBe(true)
  expect(result.multiAutoAdvance).toBe(false)
})


test('formal workflow selectors isolate runs by translation task id', async ({ page }) => {
  await page.goto(baseURL)
  const result = await page.evaluate(async () => {
    const { matchesTranslationRun, findVisibleQualityRun } = await import('/src/domain/translationFlow.ts')
    const project = {
      id: 'project-1',
      runs: [
        {
          id: 'run-old', project_id: 'project-1', kind: 'translation', language: 'en', status: 'passed',
          created_at: '2026-07-14T01:00:00Z', updated_at: '2026-07-14T01:00:00Z',
          metadata: { input_artifact_id: 'source-1', task_origin: 'translation_run', translation_task_id: 'task-old' },
        },
        {
          id: 'run-new', project_id: 'project-1', kind: 'translation', language: 'en', status: 'queued',
          created_at: '2026-07-14T02:00:00Z', updated_at: '2026-07-14T02:00:00Z',
          metadata: { input_artifact_id: 'source-1', task_origin: 'translation_run', translation_task_id: 'task-new' },
        },
      ],
    } as any
    return {
      oldDoesNotMatchNew: matchesTranslationRun(project.runs[0], 'en', 'source-1', 'translation_run', 'task-new'),
      visibleNew: findVisibleQualityRun(project, 'en', 'source-1', 'task-new')?.id,
      missingTask: findVisibleQualityRun(project, 'en', 'source-1', 'task-missing')?.id || null,
    }
  })

  expect(result).toEqual({ oldDoesNotMatchNew: false, visibleNew: 'run-new', missingTask: null })
})


test('wizard delivery run stays inside the current translation task', async ({ page }) => {
  await page.goto(baseURL)
  const result = await page.evaluate(async () => {
    const { findWizardDeliveryRun } = await import('/src/components/translationWizard/steps/StepDone.tsx')
    const project = {
      id: 'project-1',
      runs: [{
        id: 'run-old', project_id: 'project-1', kind: 'translation', language: 'en', status: 'passed',
        created_at: '2026-07-14T01:00:00Z', updated_at: '2026-07-14T01:00:00Z',
        metadata: { input_artifact_id: 'source-1', translation_task_id: 'task-old' },
        artifacts: [{ id: 'artifact-old', project_id: 'project-1', run_id: 'run-old', kind: 'qa_final_workbook' }],
      }],
    } as any
    const scope = { inputArtifactId: 'source-1', language: 'en' }
    return {
      oldTask: findWizardDeliveryRun(project, project.runs[0], { ...scope, translationTaskId: 'task-old' })?.id || null,
      newTask: findWizardDeliveryRun(project, project.runs[0], { ...scope, translationTaskId: 'task-new' })?.id || null,
    }
  })

  expect(result).toEqual({ oldTask: 'run-old', newTask: null })
})


test('translation task lifecycle groups multilingual runs and ignores closed tasks', async ({ page }) => {
  await page.goto(baseURL)
  const result = await page.evaluate(async () => {
    const {
      findActiveFormalTask,
      findUnfinishedFormalTask,
      translationTaskResumeStep,
    } = await import('/src/domain/translationTaskLifecycle.ts')
    const run = (id: string, kind: string, language: string, status: string, taskId: string, state = '') => ({
      id,
      project_id: 'project-1',
      kind,
      language,
      status,
      created_at: `2026-07-14T0${id.length}:00:00Z`,
      updated_at: `2026-07-14T0${id.length}:00:00Z`,
      metadata: {
        input_artifact_id: 'source-1',
        parent_input_artifact_id: 'source-1',
        task_origin: 'translation_run',
        translation_task_id: taskId,
        translation_task_state: state,
      },
    })
    const activeProject = {
      id: 'project-1',
      runs: [
        run('run-ko-qa', 'qa', 'ko', 'running', 'task-running'),
        run('run-en', 'translation', 'en', 'passed', 'task-running'),
        run('run-delivered', 'translation', 'fr', 'failed', 'task-delivered', 'delivered'),
      ],
    } as any
    const active = findActiveFormalTask(activeProject)
    const unfinishedProject = {
      id: 'project-1',
      runs: [
        run('run-closed', 'translation', 'fr', 'failed', 'task-closed', 'abandoned'),
        run('run-unfinished', 'translation', 'en', 'passed', 'task-unfinished'),
        { ...run('run-legacy', 'translation', 'en', 'passed', ''), metadata: { input_artifact_id: 'source-1', task_origin: 'translation_run' } },
      ],
    } as any
    const unfinished = findUnfinishedFormalTask(unfinishedProject)
    return {
      activeId: active?.id || null,
      activeLanguages: active?.languages || [],
      activeStep: active ? translationTaskResumeStep(active) : 0,
      unfinishedId: unfinished?.id || null,
    }
  })

  expect(result).toEqual({
    activeId: 'task-running',
    activeLanguages: ['ko', 'en'],
    activeStep: 8,
    unfinishedId: 'task-unfinished',
  })
})


test('multilingual task stays in one flow through translation, QA overview, and merged delivery', async ({ page, request }) => {
  await request.patch(`${baseURL}/api/settings`, {
    data: {
      provider: 'test-fake',
      protocol: 'chat-completions',
      api_key: '',
      model: 'test-fake-localization',
      batch_size: 24,
    },
  })
  const projectName = `E2E Multilingual Closed Loop ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'QA', description: 'Multilingual closed-loop regression.' },
  }).then((response) => response.json())
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'lws-multilingual-loop-'))
  const workbook = path.join(root, 'multilingual-loop.xlsx')
  execFileSync('python', ['-c', `
from openpyxl import Workbook
import sys
wb = Workbook()
ws = wb.active
ws.title = "Sheet1"
ws.append(["ID", "CN", "EN", "FR", "IT"])
ws.append([1, "领取奖励", "", "", ""])
ws.append([2, "开始游戏", "", "", ""])
wb.save(sys.argv[1])
wb.close()
`, workbook])
  const sourceArtifact = await request.post(`${baseURL}/api/projects/${project.id}/files?kind=language_table`, {
    multipart: {
      file: {
        name: fileName(workbook),
        mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        buffer: fs.readFileSync(workbook),
      },
    },
  }).then((response) => response.json())

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.locator('.sidebar').getByRole('button', { name: /新翻译任务/ }).click()
  await selectWizardStep(page, 4)
  await page.locator('.step-panel.active label.asset-select select').selectOption(sourceArtifact.id)
  await selectWizardStep(page, 7)
  await expect(page.locator('[data-testid^="multilingual-language-"]')).toHaveCount(3)
  await page.getByTestId('multilingual-translate').click()

  await expect(page.locator('[data-testid^="multilingual-language-"][data-state="ready"]')).toHaveCount(3, { timeout: 120000 })
  await expect(page.getByRole('heading', { name: 'AI 翻译', exact: true })).toBeVisible()
  await page.locator('.translation-actions').getByRole('button', { name: '进入 QA', exact: true }).click()

  await expect(page.getByTestId('multilingual-qa-actions')).toContainText('当前可合并 3 种')
  await page.getByTestId('multilingual-go-delivery').click()
  await expect(page.getByTestId('multilingual-delivery-results').locator(':scope > div')).toHaveCount(3, { timeout: 30000 })
  await expect(page.locator('.workflow-file-link')).toHaveCount(2)
  await expect(page.getByTestId('wizard-generate-delivery')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '返回项目', exact: true })).toBeVisible()
  await expect(page.getByTestId('start-next-translation-task')).toHaveText(/开始下一翻译任务/)
  await page.getByRole('button', { name: '返回项目', exact: true }).click()
  await page.locator('main').getByRole('button', { name: '新翻译任务', exact: true }).click()
  await expect(page.getByTestId('step-menu-toggle')).toContainText('项目资料')
  await selectWizardStep(page, 4)
  await expect(page.locator('.step-panel.active label.asset-select select')).toHaveValue('')
})



test('delivery empty state routes to next actions', async ({ page, request }) => {
  const projectName = `E2E Empty Delivery ${Date.now()}`
  await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'delivery-empty', description: 'Delivery empty state smoke.' },
  })

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.locator('.view-tab').nth(5).click()
  await expect(page.getByTestId('delivery-empty')).toBeVisible()

  await page.getByTestId('delivery-empty-translate').click()
  await expect(page.locator('.view-tab').nth(2)).toHaveClass(/active/)
  await page.locator('.view-tab').nth(5).click()
  await page.getByTestId('delivery-empty-qa').click()
  await expect(page.locator('.view-tab').nth(3)).toHaveClass(/active/)
  await page.locator('.view-tab').nth(5).click()
  await page.getByTestId('delivery-empty-archive').click()
  await expect(page.locator('.view-tab').nth(4)).toHaveClass(/active/)
  await expect(page.getByTestId('archive-empty-state')).toBeVisible()
  await expect(page.getByTestId('manual-archive-tools')).toBeVisible()
})

test('wizard does not claim delivery generated before files are downloadable', async ({ page }) => {
  await page.goto(baseURL)
  const counts = await page.evaluate(async () => {
    const { wizardDeliveryFiles } = await import('/src/components/translationWizard/steps/StepDone.tsx')
    const run = {
      id: 'run_failed_qa',
      kind: 'qa',
      status: 'failed',
      artifacts: [{ id: 'art_final', kind: 'qa_final_workbook' }]
    } as any
    const project = { runs: [run], artifacts: [] } as any
    const placeholder = {
      run_id: run.id,
      files: {
        final: { kind: 'final', filename: 'final.xlsx', path: '', download_url: '' },
        qa_summary: { kind: 'qa_summary', filename: 'qa.xlsx', path: '', download_url: '' }
      }
    } as any
    const ready = {
      ...placeholder,
      files: { final: { kind: 'final', filename: 'final.xlsx', download_url: '/api/final.xlsx' } }
    } as any
    const merged = {
      run_id: 'art_merged',
      task_code: 'ALL',
      input_artifact_id: 'art_source',
      files: { final: { kind: 'merged_final', filename: 'all.xlsx', download_url: '/api/all.xlsx' } },
    } as any
    return [
      wizardDeliveryFiles(project, run, [placeholder]).length,
      wizardDeliveryFiles(project, run, [ready]).length,
      wizardDeliveryFiles(project, run, [merged], undefined, [], true, 'art_source').length,
    ]
  })
  expect(counts).toEqual([0, 1, 1])
})

test('new project modal shows API failure instead of silently staying stuck', async ({ page }) => {
  await page.route('**/api/projects', async (route) => {
    if (route.request().method() === 'POST') {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'backend unavailable' }),
      })
      return
    }
    await route.continue()
  })

  await page.goto(baseURL)
  await page.locator('.new-project-btn').click()
  await page.locator('input[name="name"]').fill(`E2E Create Fail ${Date.now()}`)
  await page.getByRole('button', { name: '创建' }).click()
  await expect(page.getByTestId('new-project-error')).toContainText('backend unavailable')
  await expect(page.getByRole('heading', { name: '新建本地化项目' })).toBeVisible()
})


test('interrupted translation run resumes instead of creating a new run', async ({ page, request }) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'lws-resume-'))
  const workbook = path.join(root, 'resume-language.xlsx')
  execFileSync('python', ['-c', `
from openpyxl import Workbook
wb = Workbook()
ws = wb.active
ws.title = "Language"
ws.append(["ID", "CN", "EN"])
ws.append(["btn.resume", "\\u7ee7\\u7eed\\u4efb\\u52a1", ""])
ws.append(["msg.resume", "\\u4ece\\u65ad\\u70b9\\u7ee7\\u7eed", ""])
wb.save(r"${workbook.replace(/\\/g, '\\\\')}")
wb.close()
`])
  await request.patch(`${baseURL}/api/settings`, {
    data: { provider: 'test-fake', protocol: 'chat-completions', api_key: '', model: 'test-fake-localization', batch_size: 2 },
  })
  const projectName = `E2E Resume ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'resume', description: 'Resume regression.' },
  }).then((response) => response.json())
  const upload = await request.post(`${baseURL}/api/projects/${project.id}/files?kind=language_table`, {
    multipart: {
      file: {
        name: 'resume-language.xlsx',
        mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        buffer: fs.readFileSync(workbook),
      },
    },
  }).then((response) => response.json())
  const run = await request.post(`${baseURL}/api/runs`, {
    data: { project_id: project.id, kind: 'translation', language: 'en', input_artifact_id: upload.id, batch_size: 2, task_code: 'T' },
  }).then((response) => response.json())
  await request.post(`${baseURL}/api/runs/${run.id}/translate/cancel`)

  let resumeCalled = 0
  let startCalled = 0
  await page.route(`**/api/runs/${run.id}/translate/resume`, async (route) => {
    resumeCalled += 1
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ...run, status: 'queued', metadata: { ...run.metadata, input_artifact_id: upload.id } }),
    })
  })
  await page.route(`**/api/runs/${run.id}/translate/start`, async (route) => {
    startCalled += 1
    await route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'start should not be called for resumable run' }) })
  })

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.locator('.quick-entry').first().click()
  await expect(page.getByRole('alertdialog')).toContainText('已有未完成翻译任务')
  await page.getByTestId('confirm-modal-cancel').click()
  await selectWizardStep(page, 7)
  await page.locator('details.translation-details > summary').click()
  await expect(page.getByTestId('large-text-panel')).toBeVisible()
  await expect(page.getByTestId('large-text-panel')).toContainText(/大文本处理/)
  await expect(page.getByTestId('line-proofread-toggle')).toBeVisible()
  await expect(page.getByTestId('line-proofread-toggle')).toContainText(/深度校对/)
  await expect(page.getByTestId('line-proofread-toggle').locator('input[type="checkbox"]')).not.toBeChecked()
  await expect(page.locator('.translation-actions .btn-primary')).toBeVisible({ timeout: 15000 })
  await page.locator('.translation-actions .btn-primary').click()
  await expect.poll(() => resumeCalled, { timeout: 10000 }).toBe(1)
  expect(startCalled).toBe(0)
})

test('quick task creates a project-scoped QA run without nine step workflow', async ({ page, request }) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'lws-quick-task-'))
  const workbook = path.join(root, 'quick-translated.xlsx')
  execFileSync('python', ['-c', `
from openpyxl import Workbook
wb = Workbook()
ws = wb.active
ws.title = "Language"
ws.append(["ID", "CN", "EN"])
ws.append(["btn.claim", "\\u9886\\u53d6\\u5956\\u52b1", "Claim Reward"])
ws.append(["msg.welcome", "\\u6b22\\u8fce\\u56de\\u6765 {playerName}", "Welcome back, {playerName}"])
wb.save(r"${workbook.replace(/\\/g, '\\\\')}")
wb.close()
`])
  const projectName = `E2E Quick Task ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'quick-task', description: 'Quick task smoke.' },
  }).then((response) => response.json())

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.getByTestId('quick-task-entry').click()
  await expect(page.locator('.quick-steps')).toBeVisible()
  await expect(page.locator('.steps-nav')).toHaveCount(0)
  await page.getByTestId('quick-mode-upload').click()
  await page.getByTestId('quick-input-upload').locator('input[type="file"]').setInputFiles(workbook)
  await expect(page.getByTestId('quick-reference-next')).toBeVisible({ timeout: 15000 })
  await page.getByTestId('quick-reference-next').click()
  await page.getByTestId('quick-objective-qa').click()
  await page.getByTestId('quick-task-start').click()

  await expect.poll(async () => {
    const detail = await request.get(`${baseURL}/api/projects/${project.id}`).then((response) => response.json())
    const run = (detail.runs || []).find((item: any) => item.metadata?.task_origin === 'quick_task')
    return run?.status || ''
  }, { timeout: 60000 }).toBe('passed')
})

test('quick task translates pasted text and shows copyable result in step three', async ({ page, request }) => {
  await request.patch(`${baseURL}/api/settings`, {
    data: { provider: 'test-fake', protocol: 'chat-completions', api_key: '', model: 'test-fake-localization', batch_size: 1 },
  })
  const projectName = `E2E Quick Paste ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'quick-task', description: 'Quick pasted text smoke.' },
  }).then((response) => response.json())
  await request.post(`${baseURL}/api/projects/${project.id}/glossary`, {
    data: { source: '开始游戏', target: 'Start Game', language: 'en', source_type: 'manual', confirmed: true },
  })

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.getByTestId('quick-task-entry').click()
  await expect(page.getByTestId('quick-text-input')).toBeVisible()
  await page.getByTestId('quick-text-input').fill('开始游戏\n保存 {0}\n')
  await page.getByTestId('quick-text-next').click()
  await expect(page.getByTestId('quick-reference-next')).toBeVisible({ timeout: 15000 })
  await page.getByTestId('quick-reference-next').click()
  await page.getByTestId('quick-objective-translate').click()
  await page.getByTestId('quick-task-start').click()

  await expect(page.getByTestId('quick-text-result')).toContainText('TestFake', { timeout: 60000 })
  await expect(page.getByTestId('quick-text-result')).toContainText('{0}')
  await expect(page.getByTestId('quick-result-copy')).toBeVisible()
  await expect(page.getByTestId('quick-result-download')).toBeVisible()
})

test('quick task does not expose an unrelated latest run as its result', async ({ page }) => {
  await page.goto(baseURL)
  const displayRun = await page.evaluate(async () => {
    const { quickTaskDisplayRun } = await import('/src/components/quickTask/QuickTaskWizard.tsx')
    return quickTaskDisplayRun(null, {
      id: 'formal-run',
      kind: 'translation',
      status: 'needs_input',
      metadata: { task_origin: 'formal_translation' },
    } as any)
  })

  expect(displayRun).toBeNull()
})

test('quick task does not expose a previous quick run as the current result', async ({ page }) => {
  await page.goto(baseURL)
  const displayRun = await page.evaluate(async () => {
    const { quickTaskDisplayRun } = await import('/src/components/quickTask/QuickTaskWizard.tsx')
    return quickTaskDisplayRun(null, {
      id: 'previous-quick-run',
      kind: 'translation',
      status: 'passed',
      metadata: { task_origin: 'quick_task' },
    } as any)
  })

  expect(displayRun).toBeNull()
})

test('quick task blocks later steps until input is accepted', async ({ page, request }) => {
  const projectName = `E2E Quick Guard ${Date.now()}`
  await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'quick-task', description: 'Quick step guard.' },
  })

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.getByTestId('quick-task-entry').click()

  await expect(page.getByTestId('quick-text-input')).toBeVisible()
  await expect(page.getByRole('button', { name: '2 投入参考', exact: true })).toBeDisabled()
  await expect(page.getByRole('button', { name: '3 目标并启动', exact: true })).toBeDisabled()
})

test('quick task paste field stays readable in the light workbench theme', async ({ page, request }) => {
  const projectName = `E2E Quick Contrast ${Date.now()}`
  await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'quick-task', description: 'Quick text contrast.' },
  })

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.getByTestId('quick-task-entry').click()
  const colors = await page.getByTestId('quick-text-input').evaluate((element) => {
    const style = getComputedStyle(element)
    return { background: style.backgroundColor, color: style.color }
  })

  expect(colors).toEqual({ background: 'rgb(255, 255, 255)', color: 'rgb(23, 32, 38)' })
})

test('switching from quick task to announcement clears the quick-task status', async ({ page, request }) => {
  const projectName = `E2E Flow Status ${Date.now()}`
  await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'QA', description: 'Workflow status scope.' },
  })

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.getByTestId('quick-task-entry').click()
  await page.getByRole('button', { name: '返回项目概览', exact: true }).click()
  await page.locator('main').getByRole('button', { name: '公告翻译', exact: true }).click()

  await expect(page.getByRole('heading', { name: '公告翻译', exact: true })).toBeVisible()
  await expect(page.getByText('快速任务已就绪。', { exact: true })).toHaveCount(0)
})

test('formal workflow blocks jumping from preparation straight to delivery', async ({ page, request }) => {
  const projectName = `E2E Workflow Guard ${Date.now()}`
  await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'QA', description: 'Formal step guard.' },
  })

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.locator('main').getByRole('button', { name: '新翻译任务', exact: true }).click()

  await expect(page.getByText('补充本次翻译依据。', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '4 交付', exact: true })).toBeDisabled()
})

test('delivery request failure is shown as an error instead of an empty project', async ({ page, request }) => {
  const projectName = `E2E Delivery Error ${Date.now()}`
  await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'QA', description: 'Delivery loading state.' },
  })
  await page.route('**/api/projects/*/deliverables', async (route) => {
    await route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'delivery unavailable' }) })
  })

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.getByRole('button', { name: '交付', exact: true }).click()

  await expect(page.getByTestId('delivery-load-error')).toContainText('交付列表加载失败')
  await expect(page.getByTestId('delivery-empty')).toHaveCount(0)
})

test('quick workflow can preview and import glossary terms', async ({ page, request }) => {
  const termWorkbook = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'lws-quick-glossary-')), 'terms.xlsx')
  execFileSync('python', ['-c', `
from openpyxl import Workbook
import sys
wb = Workbook()
ws = wb.active
ws.title = "Glossary"
ws.append(["ID", "CN", "EN", "EN2", "类型", "备注"])
ws.append(["Q-1", "战机", "Warplane", "Fighter", "unit", "quick import"])
ws.append(["Q-2", "钻石", "Diamonds", "Gems", "currency", "quick import"])
wb.save(sys.argv[1])
wb.close()
`, termWorkbook])

  const projectName = `E2E Quick Glossary ${Date.now()}`
  await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: '飞行射击', description: 'Quick workflow glossary import.' },
  })

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.getByRole('button', { name: '新翻译任务', exact: true }).click()
  await selectWizardStep(page, 3)
  await page.locator('label.upload-box', { hasText: '上传术语表' }).locator('input[type="file"]').setInputFiles(termWorkbook)
  await expect(inlineStatus(page, `已上传：上传术语表｜${fileStem(termWorkbook)}`)).toBeVisible({ timeout: 15000 })
  await page.getByRole('button', { name: '预览术语' }).click()
  await expect(inlineStatus(page, '术语表预览完成：2 条')).toBeVisible({ timeout: 20000 })
  await page.getByRole('button', { name: '导入术语' }).click()
  await expect(inlineStatus(page, '术语表已导入：2 条')).toBeVisible({ timeout: 20000 })

  const projects = await request.get(`${baseURL}/api/projects`)
  const project = (await projects.json()).find((item: { name: string }) => item.name === projectName)
  expect(project).toBeTruthy()
  const termsResponse = await request.get(`${baseURL}/api/projects/${project.id}/glossary`)
  const terms = await termsResponse.json()
  expect(terms).toEqual(expect.arrayContaining([
    expect.objectContaining({ source: '战机', target: 'Warplane', target_alt: 'Fighter' }),
    expect.objectContaining({ source: '钻石', target: 'Diamonds', target_alt: 'Gems' }),
  ]))
})

test('translation workflow blocks full language table in project material and accepts it in step 4', async ({ page, request }) => {
  const languageTable = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'lws-project-material-analysis-')), 'full-language-table.xlsx')
  execFileSync('python', ['-c', `
from openpyxl import Workbook
import sys
wb = Workbook()
ws = wb.active
ws.title = "Language"
ws.append(["ID", "CN", "KR"])
for i in range(1, 1003):
    ws.append([i, f"source {i}", ""])
wb.save(sys.argv[1])
wb.close()
`, languageTable])

  const projectName = `E2E Material Analysis ${Date.now()}`
  const createResponse = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'QA', description: 'Project material can include language tables.' },
  })
  const project = await createResponse.json()

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.locator('main').getByRole('button', { name: '\u65b0\u7ffb\u8bd1\u4efb\u52a1', exact: true }).click()

  await page.locator('label.upload-box', { hasText: '上传参考资料' }).locator('input[type="file"]').setInputFiles(languageTable)
  await expect(inlineStatus(page, /\u5b8c\u6574\u8bed\u8a00\u8868|STEP4/)).toBeVisible({ timeout: 20000 })
  await expect.poll(async () => {
    const assets = await request.get(`${baseURL}/api/projects/${project.id}/assets?role=project_material`).then((response) => response.json())
    return assets.length
  }, { timeout: 20000 }).toBe(0)

  await selectWizardStep(page, 4)
  await page.locator('label.upload-box', { hasText: '上传语言表' }).locator('input[type="file"]').setInputFiles(languageTable)
  await expect.poll(async () => {
    const assets = await request.get(`${baseURL}/api/projects/${project.id}/assets?role=language_source`).then((response) => response.json())
    return assets.some((artifact: { kind: string }) => artifact.kind === 'language_table')
  }, { timeout: 20000 }).toBeTruthy()

  const languageAssets = await request.get(`${baseURL}/api/projects/${project.id}/assets?role=language_source`).then((response) => response.json())
  const uploadedLanguageTable = languageAssets.find((artifact: { kind: string }) => artifact.kind === 'language_table')
  expect(uploadedLanguageTable?.id).toBeTruthy()
  let extractPayload: any = null
  await page.route(`**/api/projects/${project.id}/glossary/extract`, async (route) => {
    extractPayload = route.request().postDataJSON()
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        run: { id: 'run-e2e-glossary', project_id: project.id, kind: 'glossary', language: 'ko', status: 'passed', created_at: new Date().toISOString(), updated_at: new Date().toISOString(), metadata: {} },
        artifacts: [],
        glossary_backfill: { candidates: 1, unique_candidates: 1, skipped_existing: 0, pending_confirmation: 1, skipped_duplicate: 0 },
      }),
    })
  })
  await selectWizardStep(page, 5)
  await page.getByRole('button', { name: /扫描候选/ }).click()
  await expect.poll(() => extractPayload?.input_artifact_id || '', { timeout: 10000 }).toBe(uploadedLanguageTable.id)
  expect(extractPayload.language).toBe('ko')
})

test('project tabs show multilingual wide glossary and archive assets', async ({ page, request }) => {
  const projectName = `E2E Wide Assets ${Date.now()}`
  const createResponse = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'wide', description: 'Multilingual wide table smoke.' },
  })
  const project = await createResponse.json()
  await request.post(`${baseURL}/api/projects/${project.id}/files?kind=language_table`, {
    multipart: {
      file: {
        name: fileName(sourceWorkbook),
        mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        buffer: fs.readFileSync(sourceWorkbook),
      },
    },
  })
  await request.post(`${baseURL}/api/projects/${project.id}/glossary`, {
    data: { term_key: 'plane', source: '战机', target: 'Warplane', target_alt: 'Fighter', language: 'en', category: 'unit', note: 'wide' },
  })
  await request.post(`${baseURL}/api/projects/${project.id}/glossary`, {
    data: { term_key: 'plane', source: '战机', target: '전투기', language: 'ko', category: 'unit', note: 'wide' },
  })
  await request.post(`${baseURL}/api/projects/${project.id}/glossary`, {
    data: { term_key: 'plane', source: '战机', target: '戦闘機', language: 'ja', category: 'unit', note: 'wide' },
  })
  await request.post(`${baseURL}/api/projects/${project.id}/translations`, {
    data: { entry_key: 'claim', source: '领取奖励', target: 'Claim rewards', language: 'en', source_type: 'qa_passed' },
  })
  await request.post(`${baseURL}/api/projects/${project.id}/translations`, {
    data: { entry_key: 'claim', source: '领取奖励', target: '보상 수령', language: 'ko', source_type: 'qa_passed' },
  })

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await expect(page.locator('.proj-head')).not.toContainText('当前目标语言')
  await expect(page.locator('.proj-head .compact-lang-grid')).toHaveCount(0)
  await expect(page.locator('.stat-grid')).toContainText('已归档文本')

  await page.locator('.view-tabs .view-tab').nth(1).click()
  const manualGlossaryTools = page.getByTestId('manual-glossary-tools')
  await manualGlossaryTools.locator('summary').click()
  await manualGlossaryTools.getByRole('button', { name: 'KR 韩语' }).click()
  await page.waitForTimeout(750)
  await expect(page.locator('input[name="target"]')).toHaveAttribute('placeholder', 'KR')
  await expect(page.getByRole('button', { name: '+ 新增 KR' })).toBeVisible()
  await expect(page.locator('.glossary-wide-table thead')).toContainText('EN')
  await expect(page.locator('.glossary-wide-table thead')).not.toContainText('EN2')
  await expect(page.locator('.glossary-wide-table thead')).not.toContainText('KR')
  await expect(page.locator('.glossary-wide-table thead')).not.toContainText('JP')
  await expect(page.locator('.glossary-wide-table thead')).not.toContainText('KR2')
  await expect(page.locator('.glossary-wide-table thead')).not.toContainText('JP2')
  await expect(page.getByPlaceholder('EN2')).toHaveCount(0)
  await page.getByTestId('glossary-display-lang-ko').click()
  await page.getByTestId('glossary-display-lang-ja').click()
  await expect(page.locator('.glossary-wide-table thead')).toContainText('KR')
  await expect(page.locator('.glossary-wide-table thead')).toContainText('JP')
  const glossaryRow = page.locator('.glossary-wide-table tbody tr', { hasText: '战机' }).first()
  await expect(glossaryRow).toContainText('Warplane')
  await expect(glossaryRow).not.toContainText('Fighter')
  await expect(glossaryRow).toContainText('전투기')
  await expect(glossaryRow).toContainText('戦闘機')

  await page.locator('.view-tabs .view-tab').nth(4).click()
  const archiveRow = page.locator('.translation-wide-table tbody tr', { hasText: '领取奖励' }).first()
  await expect(page.locator('.translation-wide-table thead')).toContainText('EN')
  await expect(page.locator('.translation-wide-table thead')).not.toContainText('KR')
  await expect(page.locator('.translation-wide-table thead')).not.toContainText('JP')
  await page.getByTestId('archive-display-lang-ko').click()
  await expect(page.locator('.translation-wide-table thead')).toContainText('KR')
  await expect(archiveRow).toContainText('Claim rewards')
  await expect(archiveRow).toContainText('보상 수령')
})

test('wide glossary and archive support strong search, display languages, and 100 row paging', async ({ page, request }) => {
  const projectName = `E2E Search Paging ${Date.now()}`
  const createResponse = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'search-paging', description: 'Search and paging smoke.' },
  })
  const project = await createResponse.json()
  for (let index = 0; index < 101; index += 1) {
    const suffix = String(index).padStart(3, '0')
    await request.post(`${baseURL}/api/projects/${project.id}/glossary`, {
      data: { term_key: `G-${suffix}`, source: `术语${suffix}`, target: `English Term ${suffix}`, target_alt: `Alt ${suffix}`, language: 'en', category: 'cat', note: 'paging' },
    })
    await request.post(`${baseURL}/api/projects/${project.id}/translations`, {
      data: { entry_key: `A-${suffix}`, source: `归档${suffix}`, target: `Archive Text ${suffix}`, language: 'en', source_type: 'qa_passed', note: 'paging' },
    })
  }
  await request.post(`${baseURL}/api/projects/${project.id}/glossary`, {
    data: { term_key: 'G-042', source: '术语042', target: '한국어定位', language: 'ko', category: 'cat', note: 'paging' },
  })
  await request.post(`${baseURL}/api/projects/${project.id}/translations`, {
    data: { entry_key: 'A-042', source: '归档042', target: '보상定位', language: 'ko', source_type: 'qa_passed', note: 'paging' },
  })

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.locator('.view-tabs .view-tab').nth(1).click()
  await expect(page.locator('.glossary-wide-table tbody tr')).toHaveCount(100)
  await expect(page.locator('.glossary-wide-table thead')).not.toContainText('KR')
  await page.getByTestId('glossary-page-next').click()
  await expect(page.locator('.glossary-wide-table tbody tr')).toHaveCount(1)
  await page.getByTestId('glossary-search').fill('한국어定位')
  await expect(page.locator('.glossary-wide-table tbody tr')).toHaveCount(1)
  await expect(page.locator('.glossary-wide-table tbody tr').first()).toContainText('术语042')
  await page.getByTestId('glossary-display-lang-ko').click()
  await expect(page.locator('.glossary-wide-table thead')).toContainText('KR')
  await expect(page.locator('.glossary-wide-table tbody tr').first()).toContainText('한국어定位')
  await page.getByTestId('glossary-search').fill('G-100')
  await expect(page.locator('.glossary-wide-table tbody tr')).toHaveCount(1)
  await expect(page.locator('.glossary-wide-table tbody tr').first()).toContainText('术语100')
  await page.getByTestId('glossary-search').fill('no-hit')
  await expect(page.locator('.glossary-wide-table tbody')).toContainText('暂无匹配结果')

  await page.locator('.view-tabs .view-tab').nth(4).click()
  await expect(page.locator('.translation-wide-table tbody tr')).toHaveCount(100)
  await expect(page.locator('.translation-wide-table thead')).not.toContainText('KR')
  await page.getByTestId('archive-search').fill('보상定位')
  await expect(page.locator('.translation-wide-table tbody tr')).toHaveCount(1)
  await expect(page.locator('.translation-wide-table tbody tr').first()).toContainText('归档042')
  await page.getByTestId('archive-display-lang-ko').click()
  await expect(page.locator('.translation-wide-table thead')).toContainText('KR')
  await expect(page.locator('.translation-wide-table tbody tr').first()).toContainText('보상定位')
})

test('project glossary import auto-detects EN KR JP into one wide row', async ({ page, request }) => {
  const termWorkbook = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'lws-wide-glossary-')), 'terms-wide.xlsx')
  execFileSync('python', ['-c', `
from openpyxl import Workbook
import sys
wb = Workbook()
ws = wb.active
ws.title = "Glossary"
ws.append(["ID", "CN", "EN", "EN2", "KR", "JP", "分类", "备注"])
ws.append(["W-1", "战机", "Warplane", "Fighter", "전투기", "戦闘機", "unit", "wide import"])
ws.append(["W-2", "钻石", "Diamonds", "Gems", "다이아몬드", "", "currency", "wide import"])
wb.save(sys.argv[1])
wb.close()
`, termWorkbook])

  const projectName = `E2E Wide Import ${Date.now()}`
  await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'wide-import', description: 'Wide import smoke.' },
  })

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.locator('.view-tabs .view-tab').nth(1).click()
  await page.getByRole('button', { name: '导入 / 生成 / 导出' }).click()
  await page.locator('label.upload-box', { hasText: '上传已确认术语表模板 xlsx/csv/json' }).locator('input[type="file"]').setInputFiles(termWorkbook)
  await expect(inlineStatus(page, `已上传：上传术语表｜${fileStem(termWorkbook)}`)).toBeVisible({ timeout: 15000 })
  await page.getByRole('button', { name: '导入已确认术语' }).click()
  await expect(inlineStatus(page, /术语表已导入：5 条/)).toBeVisible({ timeout: 20000 })

  await page.getByTestId('glossary-display-lang-ko').click()
  await page.getByTestId('glossary-display-lang-ja').click()
  const wideRow = page.locator('.glossary-wide-table tbody tr', { hasText: '战机' }).first()
  await expect(wideRow).toContainText('Warplane')
  await expect(wideRow).not.toContainText('Fighter')
  await expect(wideRow).toContainText('전투기')
  await expect(wideRow).toContainText('戦闘機')
  await expect(page.locator('.glossary-wide-table thead')).not.toContainText('KR2')
  await expect(page.locator('.glossary-wide-table thead')).not.toContainText('JP2')
})

test('project announcement workflow extracts terms with AI supplement and prepares delivery', async ({ page, request }) => {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'lws-announcement-supplement-'))
  const languageTable = path.join(tempDir, 'announcement_language.xlsx')
  const supplementResponse = path.join(tempDir, 'ai_supplement_response.json')
  execFileSync('python', ['-c', `
from openpyxl import Workbook
import sys
wb = Workbook()
ws = wb.active
ws.title = "Language"
ws.append(["ID", "CN", "EN"])
ws.append(["T1", "\u79d8\u5883", "Trial Realm"])
ws.append(["S1", "\u5f00\u542f\u661f\u754c\u88c2\u9699\u6311\u6218", "Unlock Astral Rift Challenge"])
ws.append(["N1", "\u5b8c\u5168\u65e0\u5173\u7cfb\u7edf", "Unrelated System"])
wb.save(sys.argv[1])
wb.close()
`, languageTable])
  fs.writeFileSync(
    supplementResponse,
    JSON.stringify({
      supplement_terms: [
        {
          cn: '\u661f\u754c\u88c2\u9699',
          translations: { EN: 'Astral Rift' },
          source_ids: ['S1'],
          confidence: 'high',
          reason: 'split from language-table sentence',
          evidence_ids: ['S1'],
          action: 'add_to_main',
        },
      ],
    }),
    'utf-8',
  )

  const projectName = `E2E Announcement Lookup ${Date.now()}`
  const createResponse = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'RPG', description: 'Announcement lookup e2e.' },
  })
  const project = await createResponse.json()
  await request.post(`${baseURL}/api/projects/${project.id}/translations`, {
    data: { source: '\u79d8\u5883', target: 'Trial Realm', language: 'en', source_type: 'qa_passed' },
  })
  await request.post(`${baseURL}/api/projects/${project.id}/files?kind=asset`, {
    multipart: {
      file: {
        name: 'announcement_notice.txt',
        mimeType: 'text/plain',
        buffer: Buffer.from('\u672c\u6b21\u66f4\u65b0\u65b0\u589e\u79d8\u5883\u548c\u661f\u754c\u88c2\u9699\u73a9\u6cd5\uff0c\u5e76\u5f00\u653e\u7eb9\u7ae0\u7cfb\u7edf\u3002', 'utf-8'),
      },
    },
  })

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.getByRole('button', { name: /\u516c\u544a\u7ffb\u8bd1/ }).click()
  await expect(page.getByRole('heading', { name: /\u516c\u544a\u7ffb\u8bd1/ })).toBeVisible()
  await expect(page.locator('.panel-title', { hasText: '\u516c\u544a\u8d44\u6599' })).toBeVisible()
  await expect(page.locator('.announcement-side')).toHaveCount(0)
  await expect(page.locator('.announcement-subflow-strip')).toHaveCount(0)
  await selectWizardStep(page, 2, '.announcement-wizard')
  await expect(page.getByTestId('announcement-task-required')).toBeVisible()
  await page.getByRole('button', { name: '\u56de\u5230\u516c\u544a\u8d44\u6599' }).click()
  await page.locator('.check-row', { hasText: 'announcement_notice.txt' }).locator('input').check()
  await page.getByRole('button', { name: '\u521b\u5efa\u516c\u544a\u4efb\u52a1' }).click()
  await expect(page.locator('.panel-title', { hasText: '\u7ea6\u675f\u6765\u6e90' })).toBeVisible({ timeout: 20000 })
  await expect(page.locator('.announcement-subflow-strip')).toHaveCount(0)
  await page.locator('label.upload-box', { hasText: /XLSX/ }).locator('input[type="file"]').setInputFiles(languageTable)
  await expect(page.locator('.inline-status')).toContainText(fileStem(languageTable), { timeout: 15000 })
  await expect(page.locator('.check-row', { hasText: fileStem(languageTable) }).locator('input')).toBeChecked()
  await page.getByRole('button', { name: '\u8bc6\u522b\u8bed\u8a00\u4e0e\u7ea6\u675f' }).click()
  await expect(page.locator('.panel-title', { hasText: '\u76ee\u6807\u8bed\u8a00' })).toBeVisible({ timeout: 20000 })
  await expect(page.locator('.announcement-subflow-strip')).toHaveCount(0)
  await expect(page.locator('.announcement-panel .announcement-lang-card')).toHaveCount(0)
  await expect(page.locator('.announcement-panel .announcement-language-chip')).toHaveCount(13)
  await expect(page.locator('.announcement-panel')).not.toContainText('\u517c\u5bb9')
  await expect(page.locator('.announcement-panel')).not.toContainText('KO')
  await expect(page.locator('.announcement-panel')).not.toContainText('JA')
  const langChips = page.locator('.announcement-panel .announcement-language-chip')
  for (let index = 0; index < await langChips.count(); index += 1) {
    const chip = langChips.nth(index)
    const input = chip.locator('input[type="checkbox"]')
    const label = await chip.innerText()
    if (label.includes('EN')) {
      if (!await input.isChecked()) await input.check()
    } else if (await input.isChecked()) {
      await input.uncheck()
    }
  }
  await page.getByRole('button', { name: '\u786e\u8ba4\u76ee\u6807\u8bed\u8a00' }).click()
  await expect(page.locator('.panel-title', { hasText: '\u672f\u8bed\u63d0\u53d6' })).toBeVisible({ timeout: 20000 })
  await expect(page.locator('.announcement-subflow-strip')).toHaveCount(0)
  const aiSupplementToggle = page.locator('.check-row', { hasText: '\u9ed8\u8ba4\u542f\u7528 AI \u6f0f\u8bcd\u590d\u67e5' }).locator('input')
  if (!await aiSupplementToggle.isChecked()) await aiSupplementToggle.check()
  await page.locator('label.upload-box', { hasText: '\u4e0a\u4f20\u5916\u90e8 AI \u7ed3\u679c JSON' }).locator('input[type="file"]').setInputFiles(supplementResponse)
  await expect(page.locator('.inline-status')).toContainText(fileStem(supplementResponse), { timeout: 15000 })
  await page.getByRole('button', { name: '\u63d0\u53d6\u672f\u8bed\u5e76 AI \u590d\u67e5' }).click()
  await expect(page.locator('.panel-title', { hasText: '\u8bd1\u6587\u53cd\u67e5' })).toBeVisible({ timeout: 30000 })
  await selectWizardStep(page, 4, '.announcement-wizard')
  await expect(page.locator('.panel-title', { hasText: '\u672f\u8bed\u63d0\u53d6' })).toBeVisible()
  const termsTable = page.locator('.announcement-terms-table')
  await expect(termsTable.locator('tbody tr')).toHaveCount(2, { timeout: 30000 })
  await expect(termsTable.locator('tbody tr').nth(0).locator('input').nth(1)).toHaveValue('\u79d8\u5883')
  await expect(termsTable.locator('tbody tr').nth(1).locator('input').nth(1)).toHaveValue('\u661f\u754c\u88c2\u9699')
  await expect(termsTable.locator('tbody tr').nth(1).locator('input').nth(2)).toHaveValue('Astral Rift')
  await expect(page.getByRole('link', { name: '\u5bfc\u51fa XLSX' })).toBeVisible()
  await expect(page.getByRole('link', { name: '\u4e0b\u8f7d\u68c0\u67e5\u5305' })).toBeVisible()
  await expect(page.getByRole('link', { name: '\u4e0b\u8f7d AI \u62a5\u544a' })).toBeVisible()
  await selectWizardStep(page, 5, '.announcement-wizard')
  await expect(page.locator('.panel-title', { hasText: '\u8bd1\u6587\u53cd\u67e5' })).toBeVisible({ timeout: 20000 })
  await page.getByRole('button', { name: '\u53cd\u67e5\u672f\u8bed\u8bd1\u6587' }).click()
  await expect(page.locator('.panel-title', { hasText: '\u7ffb\u8bd1\u51c6\u5907' })).toBeVisible({ timeout: 20000 })
  await page.getByRole('button', { name: '\u751f\u6210\u7ffb\u8bd1\u51c6\u5907' }).click()
  await expect(page.locator('.panel-title', { hasText: 'AI \u7ffb\u8bd1' })).toBeVisible({ timeout: 30000 })
  await expect(page.locator('.panel-desc', { hasText: '\u4e0d\u4f1a\u4f7f\u7528\u8c37\u6b4c\u673a\u7ffb' })).toBeVisible()
  await expect(page.locator('.announcement-artifacts')).toHaveCount(0)
  await page.getByText('\u8fc7\u7a0b\u6587\u4ef6\u4e0e\u5ba1\u8ba1\uff08\u53ef\u9009\uff09').click()
  const processArtifacts = page.locator('.asset-list', { hasText: '\u51c6\u5907\u4ea7\u7269\u4e0b\u8f7d' })
  await expect(processArtifacts.getByText(/公告工作包.*EN/)).toBeVisible()
  await expect(processArtifacts.getByText(/\u516c\u544a\u7ffb\u8bd1\u4e2d\u8f6c\u8868/)).toBeVisible()

  const taskResponse = await request.get(`${baseURL}/api/projects/${project.id}/announcement-tasks`)
  const tasks = await taskResponse.json()
  const task = tasks.find((item: { title: string }) => item.title === 'announcement_notice.txt')
  expect(task).toBeTruthy()
  const segments = task.metadata.segments as { id: string }[]
  expect(segments.length).toBeGreaterThan(0)
  const responseFile = path.join(tempDir, 'ai_response_en.jsonl')
  fs.writeFileSync(
    responseFile,
    segments.map((segment) => JSON.stringify({
      para_id: segment.id,
      translation: 'Trial Realm and Astral Rift gameplay are now available, and the Emblem system is open.',
    })).join('\n') + '\n',
    'utf-8',
  )

  await page.locator('summary', { hasText: '\u5916\u90e8 AI \u7ed3\u679c\u5bfc\u5165' }).click()
  await page.locator('label.upload-box', { hasText: '上传外部 AI 结果 JSONL' }).locator('input[type="file"]').setInputFiles(responseFile)
  await expect(page.locator('.inline-status')).toContainText(fileStem(responseFile), { timeout: 15000 })
  await page.getByRole('button', { name: '\u5bfc\u5165\u5916\u90e8 AI \u7ed3\u679c' }).click()
  await expect(page.locator('.panel-title', { hasText: '\u6821\u5bf9\u56de\u586b' })).toBeVisible({ timeout: 20000 })
  await page.getByRole('button', { name: 'QA \u5e76\u56de\u586b\u540c\u683c\u5f0f\u6587\u4ef6' }).click()
  await expect(page.locator('.panel-title', { hasText: '\u4ea4\u4ed8' })).toBeVisible({ timeout: 30000 })
  await expect(page.getByRole('link', { name: '下载 EN 成品' })).toBeVisible()
  await page.getByRole('button', { name: '\u751f\u6210\u4ea4\u4ed8\u603b\u5305' }).click()
  await expect(page.getByRole('link', { name: '下载公告交付包' })).toBeVisible({ timeout: 30000 })
  await expect(page.locator('.announcement-subflow-strip')).toHaveCount(0)
  await expect(page.locator('.announcement-artifacts')).toContainText('\u53ef\u4ea4\u4ed8')
  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await expect(page.locator('.announcement-project-panel .mini-lang')).toHaveCount(0)
  await expect(page.locator('.announcement-project-panel')).not.toContainText('terms_ready')
  await page.getByRole('button', { name: '交付', exact: true }).click()
  await expect(page.getByRole('link', { name: '下载交付包' })).toBeVisible({ timeout: 30000 })
  await expect(page.getByRole('link', { name: '下载成品' })).toBeVisible()
  await expect(page.getByRole('link', { name: '下载 QA 摘要' })).toBeVisible()
  await page.getByRole('button', { name: '公告翻译', exact: true }).click()
  await expect(page.locator('.panel-title', { hasText: '\u516c\u544a\u8d44\u6599' })).toBeVisible()
  await expect(page.locator('.announcement-current-task')).toHaveCount(0)
  await page.getByRole('button', { name: '\u8fd4\u56de\u9879\u76ee\u6982\u89c8', exact: true }).click()
  const deliveredAnnouncementRow = page.locator('.announcement-task-row', { hasText: 'announcement_notice.txt' })
  await expect(deliveredAnnouncementRow.getByRole('button', { name: '\u7ee7\u7eed' })).toHaveCount(0)
  await deliveredAnnouncementRow.getByRole('button', { name: '\u67e5\u770b\u4ea4\u4ed8' }).click()

  const stepTitles = ['\u516c\u544a\u8d44\u6599', '\u7ea6\u675f\u6765\u6e90', '\u76ee\u6807\u8bed\u8a00', '\u672f\u8bed\u63d0\u53d6', '\u8bd1\u6587\u53cd\u67e5', '\u7ffb\u8bd1\u51c6\u5907', 'AI \u7ffb\u8bd1', '\u6821\u5bf9\u56de\u586b', '\u4ea4\u4ed8']
  for (const [index, title] of stepTitles.entries()) {
    await selectWizardStep(page, index + 1, '.announcement-wizard')
    await expect(page.locator('.panel-title', { hasText: title })).toBeVisible()
  }
})

test('user can upload an existing translated workbook and run QA directly', async ({ page, request }) => {
  const translatedWorkbook = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'lws-direct-qa-')), 'translated.xlsx')
  execFileSync('python', ['-c', `
from openpyxl import Workbook
import sys
wb = Workbook()
ws = wb.active
ws.title = "Language"
ws.append(["ID", "cn", "en"])
ws.append([1, "领取奖励", "Claim rewards"])
ws.append([2, "开始游戏", "Start game"])
ws.append([3, "系统错误", "System error"])
ws.append([4, "主线任务", "Main quest"])
ws.append([5, "欢迎回来，{playerName}", "Welcome back, {playerName}"])
wb.save(sys.argv[1])
wb.close()
`, translatedWorkbook])

  const projectName = `E2E Direct QA ${Date.now()}`
  await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'QA', description: 'Direct QA e2e' },
  })
  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.getByRole('button', { name: '校对', exact: true }).click()
  await page.locator('label.upload-box', { hasText: '上传译文' }).locator('input[type="file"]').setInputFiles(translatedWorkbook)
  await expect(inlineStatus(page, '已有译文已登记')).toBeVisible({ timeout: 15000 })
  await page.getByTestId('run-qa').click()
  await expect(page.locator('.qa-outcome-panel.ready')).toContainText('QA 已通过', { timeout: 60000 })
  await page.getByRole('button', { name: '交付', exact: true }).click()
  await expect(page.locator('.delivery-head span', { hasText: /QA-[0-9a-f]{6}/ }).first()).toBeVisible({ timeout: 30000 })
  await page.getByRole('button', { name: '\u751f\u6210\u4ea4\u4ed8\u6587\u4ef6' }).click()
  await expect(inlineStatus(page, '\u6700\u7ec8\u4ea4\u4ed8\u5df2\u751f\u6210\uff1a2 \u4e2a\u6587\u4ef6')).toBeVisible({ timeout: 30000 })
  await expect(page.getByRole('link', { name: '\u4e0b\u8f7d\u6700\u7ec8\u8bd1\u6587' })).toBeVisible()

  await page.getByRole('button', { name: '译文归档', exact: true }).click()
  await expect(page.getByText('项目译文归档')).toBeVisible()
  await expect(page.locator('.translation-archive-table')).toContainText('Claim rewards')
})


test('user can explicitly skip QA and archive an existing translated language table', async ({ page, request }) => {
  const translatedWorkbook = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'lws-skip-qa-')), 'translated-skip-qa.xlsx')
  execFileSync('python', ['-c', `
from openpyxl import Workbook
import sys
wb = Workbook()
ws = wb.active
ws.title = "Language"
ws.append(["ID", "cn", "en"])
ws.append([1, "\u9886\u53d6\u5956\u52b1", "Claim rewards"])
ws.append([2, "\u5f00\u59cb\u6e38\u620f", "Start game"])
wb.save(sys.argv[1])
wb.close()
`, translatedWorkbook])

  const projectName = `E2E Skip QA Archive ${Date.now()}`
  await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'QA', description: 'Skip QA archive e2e' },
  })

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.getByRole('button', { name: '\u65b0\u7ffb\u8bd1\u4efb\u52a1', exact: true }).click()
  await selectWizardStep(page, 4)
  await page.locator('label.upload-box', { hasText: '上传语言表' }).locator('input[type="file"]').setInputFiles(translatedWorkbook)
  await expect(page.locator('.ai-card', { hasText: fileName(translatedWorkbook) }).last()).toBeVisible({ timeout: 15000 })

  await selectWizardStep(page, 7)
  await expect(page.getByRole('button', { name: '进入 QA' })).toBeVisible({ timeout: 15000 })
  await expect(page.getByTestId('step-5')).toHaveClass(/skipped/)
  await expect(page.getByTestId('step-6')).toHaveClass(/skipped/)
  await expect(page.getByTestId('step-7')).not.toHaveClass(/skipped/)
  await page.getByRole('button', { name: '进入 QA' }).click()
  await expect(page.getByTestId('step-7')).toHaveClass(/skipped/)

  const skipPanel = page.locator('details.manual-maintenance', { hasText: '\u4e34\u65f6\u8df3\u8fc7 QA \u76f4\u63a5\u5f52\u6863' })
  await expect(skipPanel).toBeVisible()
  await skipPanel.locator('summary').click()
  await skipPanel.getByRole('button', { name: '\u786e\u8ba4\u8df3\u8fc7 QA \u5e76\u5f52\u6863' }).click()
  await page.getByTestId('confirm-modal-confirm').click()
  await expect(inlineStatus(page, '\u5df2\u8df3\u8fc7 QA \u5e76\u5bfc\u5165\u8bd1\u6587\u5f52\u6863').first()).toBeVisible({ timeout: 30000 })

  await page.getByRole('button', { name: '项目概览', exact: true }).click()
  await page.getByRole('button', { name: /\u8bd1\u6587\u5f52\u6863/ }).click()
  await expect(page.getByText('\u9879\u76ee\u8bd1\u6587\u5f52\u6863')).toBeVisible()
  await expect(page.locator('.translation-archive-table')).toContainText('Claim rewards')

  await page.locator('.view-tabs .view-tab', { hasText: '\u6821\u5bf9' }).click()
  await expect(page.locator('details', { hasText: '\u4e34\u65f6\u8df3\u8fc7 QA \u76f4\u63a5\u5f52\u6863' })).toHaveCount(0)
})


test('wizard QA refreshes readiness after manually selecting a translated language table', async ({ page, request }) => {
  const fixtureDir = fs.mkdtempSync(path.join(os.tmpdir(), 'lws-manual-readiness-'))
  const emptyWorkbook = path.join(fixtureDir, 'empty-language.xlsx')
  const translatedWorkbook = path.join(fixtureDir, 'manual-translated-language.xlsx')
  execFileSync('python', ['-c', `
from openpyxl import Workbook
import sys
empty_path, translated_path = sys.argv[1], sys.argv[2]
wb = Workbook()
ws = wb.active
ws.title = "Language"
ws.append(["ID", "cn", "en"])
ws.append([1, "\\u9886\\u53d6\\u5956\\u52b1", ""])
ws.append([2, "\\u5f00\\u59cb\\u6e38\\u620f", ""])
wb.save(empty_path)
wb.close()
wb = Workbook()
ws = wb.active
ws.title = "Language"
ws.append(["ID", "cn", "en"])
ws.append([1, "\\u9886\\u53d6\\u5956\\u52b1", "Claim rewards"])
ws.append([2, "\\u5f00\\u59cb\\u6e38\\u620f", "Start game"])
wb.save(translated_path)
wb.close()
`, emptyWorkbook, translatedWorkbook])

  const projectName = `E2E Manual Readiness ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'QA', description: 'Manual readiness refresh e2e' },
  }).then((response) => response.json())
  const translatedArtifact = await request.post(`${baseURL}/api/projects/${project.id}/files?kind=language_table`, {
    multipart: {
      file: {
        name: 'manual-translated-language.xlsx',
        mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        buffer: fs.readFileSync(translatedWorkbook),
      },
    },
  }).then((response) => response.json())
  await request.post(`${baseURL}/api/projects/${project.id}/files?kind=language_table`, {
    multipart: {
      file: {
        name: 'empty-language.xlsx',
        mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        buffer: fs.readFileSync(emptyWorkbook),
      },
    },
  })

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.getByRole('button', { name: '\u65b0\u7ffb\u8bd1\u4efb\u52a1', exact: true }).click()
  await selectWizardStep(page, 4)
  await page.locator('.step-panel.active label.asset-select select').selectOption(translatedArtifact.id)
  await page.getByRole('button', { name: '去校对' }).click()
  await page.locator('.step-panel.active label.asset-select select').selectOption(translatedArtifact.id)

  const skipPanel = page.locator('details.manual-maintenance', { hasText: '\u4e34\u65f6\u8df3\u8fc7 QA \u76f4\u63a5\u5f52\u6863' })
  await skipPanel.locator('summary').click()
  await expect(skipPanel.getByRole('button', { name: '\u786e\u8ba4\u8df3\u8fc7 QA \u5e76\u5f52\u6863' })).toBeEnabled({ timeout: 15000 })
})

// --- M4: active jobs panel + queue guidance --------------------------------
// GET /api/system/active-jobs reflects backend/app/jobs.py's per-project lease
// registry. The test-fake provider used elsewhere in this file completes a
// translation run (even a large one) in well under a second, so there is no
// real window in which a genuine background job stays "running" long enough
// for the frontend's ~9s poll to observe it. Following the same technique the
// "interrupted translation run resumes" test above uses (page.route to control
// backend responses deterministically), these tests intercept the active-jobs
// endpoint and/or the translate/start conflict response so they exercise the
// frontend's polling + rendering + inline-action logic without racing a job
// that would already be gone by the time the page checks.

test('active jobs badge stays hidden when no task is running', async ({ page }) => {
  await page.goto(baseURL)
  await expect(page.getByRole('heading', { name: '本地化工作台' })).toBeVisible()
  await expect(page.getByTestId('active-jobs-badge')).toHaveCount(0)
})

test('failed project task opens its processing tab instead of leaving the activity panel in place', async ({ page, request }) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'lws-failed-activity-'))
  const workbook = path.join(root, 'failed-activity.xlsx')
  execFileSync('python', ['-c', `
from openpyxl import Workbook
import sys
wb = Workbook()
ws = wb.active
ws.title = "Language"
ws.append(["ID", "cn", "en"])
ws.append([1, "领取奖励", "Forbidden Brand Reward"])
wb.save(sys.argv[1])
wb.close()
`, workbook])
  const projectName = `E2E Failed Activity ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'QA', description: 'Failed activity routing.' },
  }).then((response) => response.json())
  await request.patch(`${baseURL}/api/projects/${project.id}/harness`, {
    data: { forbidden_translations: ['Forbidden Brand'] },
  })
  const artifact = await request.post(`${baseURL}/api/projects/${project.id}/files?kind=final_workbook`, {
    multipart: {
      file: {
        name: fileName(workbook),
        mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        buffer: fs.readFileSync(workbook),
      },
    },
  }).then((response) => response.json())
  const run = await request.post(`${baseURL}/api/runs`, {
    data: { project_id: project.id, kind: 'qa', language: 'en', input_artifact_id: artifact.id },
  }).then((response) => response.json())
  const qa = await request.post(`${baseURL}/api/runs/${run.id}/qa`)
  expect(qa.ok()).toBeTruthy()

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await expect(page.locator('.project-activity-panel')).toBeVisible()
  await page.locator('.project-activity-panel').getByRole('button', { name: '去处理' }).click()

  await expect(page.locator('.project-activity-panel')).toHaveCount(0)
  await expect(page.locator('.view-tab.active')).toContainText('校对')
  await expect(page.getByTestId('qa-outcome-panel')).toContainText('QA 未通过')
  await expect(page.getByRole('button', { name: /修复并重跑/ })).toBeEnabled()
  await expect(page.getByRole('button', { name: '手动修复' })).toBeEnabled()

  const deliveryResponse = page.waitForResponse((response) => response.request().method() === 'POST' && response.url().includes(`/api/projects/${project.id}/delivery-package?run_id=`))
  await page.getByTestId('qa-go-delivery').click()
  expect((await deliveryResponse).ok()).toBeTruthy()
  await expect(page.locator('.delivery-card a')).toHaveCount(3)
})

test('cleared terminal tasks do not remain in the project activity list', async ({ page }) => {
  await page.goto(baseURL)
  const visibleRunIds = await page.evaluate(async () => {
    const { projectActivityRuns } = await import('/src/domain/projectActivity.ts')
    return projectActivityRuns({
      id: 'project-cleared',
      runs: [
        { id: 'failed-visible', kind: 'qa', status: 'failed', metadata: {} },
        { id: 'failed-cleared', kind: 'qa', status: 'failed', metadata: { activity_dismissed_at: '2026-07-13T00:00:00Z' } },
      ],
    } as any).map((run: any) => run.id)
  })

  expect(visibleRunIds).toEqual(['failed-visible'])
})

test('active jobs badge and panel show the running project name and task type', async ({ page, request }) => {
  const projectName = `E2E Active Jobs ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'active-jobs', description: 'Active jobs panel smoke.' },
  }).then((response) => response.json())

  await page.route('**/api/system/active-jobs', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          lease_name: `long_text:${project.id}`,
          job_id: 'run:run-e2e-active',
          job_kind: 'translation',
          project_id: project.id,
          project_name: projectName,
          started_at: new Date(Date.now() - 3 * 60 * 1000).toISOString(),
        },
      ]),
    })
  })

  await page.goto(baseURL)
  const badge = page.getByTestId('active-jobs-badge')
  await expect(badge).toBeVisible({ timeout: 15000 })
  await expect(badge).toContainText('1')
  await badge.click()
  const panel = page.getByTestId('active-jobs-panel')
  await expect(panel).toBeVisible()
  await expect(panel).toContainText(projectName)
  await expect(panel).toContainText('翻译')
  await expect(panel).toContainText('分钟前')
})

test('starting a second task on a busy project shows a queue hint that opens the active jobs panel', async ({ page, request }) => {
  await request.patch(`${baseURL}/api/settings`, {
    data: { provider: 'test-fake', protocol: 'chat-completions', api_key: '', model: 'test-fake-localization', batch_size: 24 },
  })
  const projectName = `E2E Queue Hint ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'queue-hint', description: 'Queue conflict inline action smoke.' },
  }).then((response) => response.json())

  // Exact text backend/app/routers/shared.py's _job_conflict_detail renders
  // for a project_busy rejection; apiClient.ts's sanitizeUserFacingError
  // passes it through unchanged (see the "该项目正在执行任务" branch).
  const conflictDetail = '该项目正在执行任务（翻译任务），请等它完成或先取消'
  await page.route('**/api/runs/*/translate/start', async (route) => {
    await route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: conflictDetail }) })
  })
  await page.route('**/api/system/active-jobs', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          lease_name: `long_text:${project.id}`,
          job_id: 'run:run-e2e-conflict',
          job_kind: 'translation',
          project_id: project.id,
          project_name: projectName,
          started_at: new Date(Date.now() - 60 * 1000).toISOString(),
        },
      ]),
    })
  })

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.getByRole('button', { name: '翻译', exact: true }).click()
  await page.locator('label.upload-box', { hasText: '上传待翻译表格' }).locator('input[type="file"]').setInputFiles(sourceWorkbook)
  await expect(page.locator('.selected-input span', { hasText: fileStem(sourceWorkbook) })).toBeVisible({ timeout: 15000 })
  await expect(page.getByTestId('formal-translate')).toBeEnabled()
  await page.getByTestId('formal-translate').click()
  await expect(inlineStatus(page, '该项目正在执行任务')).toBeVisible({ timeout: 15000 })

  const action = page.getByTestId('inline-status-view-active-jobs')
  await expect(action).toBeVisible()
  await action.click()
  const panel = page.getByTestId('active-jobs-panel')
  await expect(panel).toBeVisible()
  await expect(panel).toContainText(projectName)
  await expect(panel).toContainText('翻译')
})

test('translation evidence shows archive references and line proofreading stages', async ({ page, request }) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'lws-translation-evidence-'))
  const workbook = path.join(root, 'reference-source.xlsx')
  execFileSync('python', ['-c', `
from openpyxl import Workbook
import sys
wb = Workbook()
ws = wb.active
ws.title = "Language"
ws.append(["ID", "cn", "en"])
ws.append([1, "领取奖励", ""])
ws.append([2, "开始游戏", ""])
ws.append([3, "欢迎回来，{playerName}", ""])
wb.save(sys.argv[1])
wb.close()
`, workbook])

  const projectName = `E2E Translation Evidence ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'evidence', description: 'Reference and line proofread UI evidence.' },
  }).then((response) => response.json())
  await request.post(`${baseURL}/api/projects/${project.id}/translations`, {
    data: { entry_key: 'claim', source: '领取奖励', target: 'Claim Rewards', language: 'en', source_type: 'qa_passed' },
  })
  await request.post(`${baseURL}/api/projects/${project.id}/translations`, {
    data: { entry_key: 'welcome', source: '欢迎回来，{playerName}', target: 'Welcome back, {playerName}', language: 'en', source_type: 'imported' },
  })
  const upload = await request.post(`${baseURL}/api/projects/${project.id}/files?kind=language_table`, {
    multipart: {
      file: {
        name: 'reference-source.xlsx',
        mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        buffer: fs.readFileSync(workbook),
      },
    },
  }).then((response) => response.json())
  const run = await request.post(`${baseURL}/api/runs`, {
    data: { project_id: project.id, kind: 'translation', language: 'en', input_artifact_id: upload.id, translation_task_id: 'translation-evidence-task' },
  }).then((response) => response.json())
  const translated = await request.post(`${baseURL}/api/runs/${run.id}/translate`, {
    data: { provider: 'test-fake', enable_line_proofread: true },
  })
  expect(translated.ok()).toBeTruthy()

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.locator('main').getByRole('button', { name: '新翻译任务', exact: true }).click()
  await page.getByTestId('confirm-modal-cancel').click()
  await selectWizardStep(page, 7)
  const referenceAudit = page.getByTestId('translation-reference-audit')
  await expect(referenceAudit).toContainText('已检索 2 条项目译文', { timeout: 20000 })
  await expect(referenceAudit).toContainText('命中原文')
  await expect(page.getByTestId('line-proofread-process')).toContainText('逐句审校')
  await expect(page.getByTestId('line-proofread-summary')).toContainText('确定性审计')
})

test('workflow remains usable without page overflow at compact desktop and mobile widths', async ({ page, request }) => {
  const projectName = `E2E Responsive Workflow ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'responsive', description: 'Responsive workbench smoke.' },
  }).then((response) => response.json())
  const sourceArtifact = await request.post(`${baseURL}/api/projects/${project.id}/files?kind=language_table`, {
    multipart: {
      file: {
        name: fileName(sourceWorkbook),
        mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        buffer: fs.readFileSync(sourceWorkbook),
      },
    },
  }).then((response) => response.json())

  for (const viewport of [{ width: 1125, height: 903 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport)
    await page.goto(baseURL)
    await page.getByRole('button', { name: projectName }).click()
    await page.locator('main').getByRole('button', { name: '新翻译任务', exact: true }).click()
    await selectWizardStep(page, 4)
    await page.locator('.step-panel.active label.asset-select select').selectOption(sourceArtifact.id)
    await selectWizardStep(page, 7)
    await expect(page.locator('.phase-item.active')).toContainText('处理')
    await expect(page.locator('.actions .btn-primary')).toBeVisible()
    const dimensions = await page.evaluate(() => ({
      pageWidth: document.documentElement.scrollWidth,
      viewportWidth: document.documentElement.clientWidth,
      contentOverflow: document.querySelector('.main-content')!.scrollWidth - document.querySelector('.main-content')!.clientWidth,
    }))
    expect(dimensions.pageWidth).toBeLessThanOrEqual(dimensions.viewportWidth + 1)
    expect(dimensions.contentOverflow).toBeLessThanOrEqual(1)
  }
})

test('mobile project overview exposes all three workflow entries', async ({ page, request }) => {
  const projectName = `E2E Mobile Entries ${Date.now()}`
  await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'responsive', description: 'Mobile workflow entry coverage.' },
  })

  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()

  const main = page.locator('main')
  await expect(main.getByRole('button', { name: '新翻译任务', exact: true })).toBeVisible()
  await expect(main.getByRole('button', { name: '公告翻译', exact: true })).toBeVisible()
  await expect(main.getByTestId('overview-quick-task')).toBeVisible()
  await main.getByTestId('overview-quick-task').click()
  await expect(page.getByRole('heading', { name: '快速任务', exact: true })).toBeVisible()
})

test('compact desktop keeps sidebar entries and command labels intact', async ({ page, request }) => {
  const projectName = `E2E Compact Labels ${Date.now()}`
  await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'responsive', description: 'Compact label coverage.' },
  })

  await page.setViewportSize({ width: 1280, height: 720 })
  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()

  const entryMetrics = await page.locator('.quick-entry').evaluateAll((entries) => entries.map((entry) => ({
    clientHeight: entry.clientHeight,
    scrollHeight: entry.scrollHeight,
  })))
  expect(entryMetrics).toHaveLength(2)
  expect(entryMetrics.every((entry) => entry.clientHeight >= 56)).toBeTruthy()
  expect(entryMetrics.every((entry) => entry.scrollHeight <= entry.clientHeight + 1)).toBeTruthy()

  const secondaryColor = await page.locator('.quick-entry .pmeta').first().evaluate((element) => getComputedStyle(element).color)
  expect(secondaryColor).toBe('rgb(104, 116, 127)')

  await page.getByTestId('quick-task-entry').click()
  const back = page.getByRole('button', { name: '返回项目概览', exact: true })
  const backMetrics = await back.evaluate((element) => ({
    clientHeight: element.clientHeight,
    scrollHeight: element.scrollHeight,
    whiteSpace: getComputedStyle(element).whiteSpace,
  }))
  expect(backMetrics.scrollHeight).toBeLessThanOrEqual(backMetrics.clientHeight + 1)
  expect(backMetrics.whiteSpace).toBe('nowrap')
})

test('delivery cards reflow without horizontal overflow at 1024px', async ({ page, request }) => {
  const projectName = `E2E Delivery Reflow ${Date.now()}`
  await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'responsive', description: 'Delivery reflow coverage.' },
  })
  await page.route('**/api/projects/*/deliverables', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        deliverables: [{
          run_id: 'run-responsive-delivery',
          task_code: 'T',
          task_id: 'task-responsive-delivery',
          task_label: 'T-responsive',
          task_type: '翻译任务',
          language: 'EN',
          created_at: '2026-07-11T08:54:54Z',
          updated_at: '2026-07-11T08:54:54Z',
          status: 'passed',
          processed_rows: 5,
          source_rows: 5,
          input_label: '已译语言表｜EN｜responsive-delivery｜2026-07-11',
          qa_status: 'passed',
          qa_hard_errors: 0,
          qa_soft_warnings: 0,
          files: { outputs: [] },
        }],
      }),
    })
  })

  await page.setViewportSize({ width: 1024, height: 768 })
  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.getByRole('button', { name: '交付', exact: true }).click()
  await expect(page.locator('.delivery-line')).toBeVisible()

  const metrics = await page.evaluate(() => {
    const main = document.querySelector('.main')!
    const content = document.querySelector('.main-content')!
    const card = document.querySelector('.delivery-line')!
    const tag = document.querySelector('.delivery-line .tag')!
    return {
      mainOverflow: main.scrollWidth - main.clientWidth,
      contentOverflow: content.scrollWidth - content.clientWidth,
      cardColumns: getComputedStyle(card).gridTemplateColumns.split(' ').length,
      tagHeight: tag.getBoundingClientRect().height,
    }
  })
  expect(metrics.mainOverflow).toBeLessThanOrEqual(1)
  expect(metrics.contentOverflow).toBeLessThanOrEqual(1)
  expect(metrics.cardColumns).toBe(2)
  expect(metrics.tagHeight).toBeLessThanOrEqual(30)

  await page.setViewportSize({ width: 390, height: 844 })
  const mobileColumns = await page.locator('.delivery-line').evaluate((card) => getComputedStyle(card).gridTemplateColumns.split(' ').length)
  expect(mobileColumns).toBe(1)
})

test('mobile project tabs and history table stay readable', async ({ page, request }) => {
  const projectName = `E2E Mobile Tables ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'responsive', description: 'Mobile tab and table coverage.' },
  }).then((response) => response.json())
  await request.post(`${baseURL}/api/runs`, {
    data: { project_id: project.id, kind: 'translation', language: 'en' },
  })

  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.getByRole('button', { name: '翻译', exact: true }).click()
  await expect(page.locator('.history-table-scroll')).toBeVisible()

  const metrics = await page.evaluate(() => {
    const tabs = document.querySelector('.view-tabs')!
    const wrapper = document.querySelector('.history-table-scroll')!
    const table = document.querySelector('.history-table')!
    const tag = document.querySelector('.history-table .tag')!
    return {
      tabColumns: getComputedStyle(tabs).gridTemplateColumns.split(' ').length,
      tabOverflow: tabs.scrollWidth - tabs.clientWidth,
      wrapperOverflow: wrapper.scrollWidth - wrapper.clientWidth,
      tableWidth: table.getBoundingClientRect().width,
      tagHeight: tag.getBoundingClientRect().height,
    }
  })

  expect(metrics.tabColumns).toBe(3)
  expect(metrics.tabOverflow).toBeLessThanOrEqual(1)
  expect(metrics.wrapperOverflow).toBeGreaterThan(0)
  expect(metrics.tableWidth).toBeGreaterThanOrEqual(679)
  expect(metrics.tagHeight).toBeLessThanOrEqual(30)
})
