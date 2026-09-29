import { expect, test, type Page } from '@playwright/test'
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
  const promptProject = await request.get(`${baseURL}/api/projects`)
    .then((response) => response.json())
    .then((items) => items.find((item: { name: string }) => item.name === projectName))
  expect(promptProject).toBeTruthy()
  const promptSave = page.waitForResponse((response) => (
    response.request().method() === 'PATCH'
    && new URL(response.url()).pathname === `/api/projects/${promptProject.id}`
    && response.request().postDataJSON().prompt_text === manualPrompt
  ))
  const [, promptSaveResponse] = await Promise.all([
    page.locator('.reference-card .row-actions .btn-primary').click(),
    promptSave,
  ])
  expect(promptSaveResponse.ok()).toBeTruthy()
  await expect(page.locator('textarea.prompt-editor')).toHaveCount(0)
  const promptSavedProject = await request.get(`${baseURL}/api/projects/${promptProject.id}`)
    .then((response) => response.json())
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
  const translationCreated = page.waitForResponse((response) => response.request().method() === 'POST'
    && new URL(response.url()).pathname === '/api/runs' && response.request().postDataJSON().kind === 'translation')
  await page.getByTestId('formal-translate').click()
  const translationResponse = await translationCreated
  expect(translationResponse.ok()).toBeTruthy()
  const translationRequest = translationResponse.request().postDataJSON()
  expect(translationRequest.translation_task_id).toMatch(/^translation-task-/)
  const translationRun = await translationResponse.json()
  expect(translationRun.metadata.translation_task_id).toBe(translationRequest.translation_task_id)
  await expect(inlineStatus(page, 'EN 翻译和 QA 已通过，最终产物已归档。')).toBeVisible({ timeout: 120000 })
  await expect(page.getByText('最近翻译任务')).toBeVisible()
  await expect(page.getByText('已通过').first()).toBeVisible()

  await page.getByRole('button', { name: '校对', exact: true }).click()
  await expect(page.locator('.qa-outcome-panel')).toContainText('QA 已通过')
  await expect(page.locator('.qa-outcome-panel')).toContainText('已译语言表（EN）')
  await expect(page.locator('.qa-outcome-panel')).not.toContainText('QA final workbook')
  await expect(page.locator('.qa-outcome-panel')).not.toContainText('result_en')
  await expect(page.locator('.qa-outcome-panel')).toContainText('上一翻译结果')
  await page.locator('details.qa-input-details > summary').click()
  const continuationCreated = page.waitForResponse((response) => response.request().method() === 'POST'
    && new URL(response.url()).pathname === '/api/runs' && response.request().postDataJSON().kind === 'qa')
  await page.getByTestId('run-qa').click()
  const continuationResponse = await continuationCreated
  expect(continuationResponse.ok()).toBeTruthy()
  expect(continuationResponse.request().postDataJSON()).toMatchObject({
    source_run_id: translationRun.id, translation_task_id: translationRequest.translation_task_id,
  })
  const continuationRun = await continuationResponse.json()
  await expect.poll(async () => (await request.get(`${baseURL}/api/runs/${continuationRun.id}`).then((response) => response.json())).status).toBe('passed')
  const completedContinuation = await request.get(`${baseURL}/api/runs/${continuationRun.id}`).then((response) => response.json())
  expect(completedContinuation.metadata.translation_task_id).toBe(translationRequest.translation_task_id)
  await expect(page.locator('.qa-outcome-panel.ready')).toContainText('QA 已通过')

  await page.getByRole('button', { name: '交付', exact: true }).click()
  await expect(page.locator('.card-title .left', { hasText: '最终交付' })).toBeVisible()
  await expect(page.locator('.delivery-card').first()).toBeVisible({ timeout: 30000 })
  await expect(page.getByText('本次 QA', { exact: true })).toBeVisible()
  await expect(page.getByText('当前交付', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '生成交付文件' }).click()
  await expect(inlineStatus(page, '最终交付已生成：2 个文件')).toBeVisible({ timeout: 30000 })
  await expect(page.getByRole('link', { name: '下载最终译文' })).toBeVisible()
  await expect(page.getByRole('link', { name: '下载修改记录' })).toBeVisible()
  const deliveredRun = await request.get(`${baseURL}/api/runs/${continuationRun.id}`).then((response) => response.json())
  expect(deliveredRun.metadata.translation_task_state).toBe('delivered')
  await page.getByRole('button', { name: '翻译', exact: true }).click()
  const nextTranslationCreated = page.waitForResponse((response) => response.request().method() === 'POST'
    && new URL(response.url()).pathname === '/api/runs' && response.request().postDataJSON().kind === 'translation')
  await page.getByTestId('formal-translate').click()
  const nextTranslationResponse = await nextTranslationCreated
  expect(nextTranslationResponse.ok()).toBeTruthy()
  const nextTranslationRequest = nextTranslationResponse.request().postDataJSON()
  expect(nextTranslationRequest.input_artifact_id).toBe(translationRequest.input_artifact_id)
  expect(nextTranslationRequest.translation_task_id).toMatch(/^translation-task-/)
  expect(nextTranslationRequest.translation_task_id).not.toBe(translationRequest.translation_task_id)
  const nextTranslationRun = await nextTranslationResponse.json()
  expect(nextTranslationRun.metadata.translation_task_id).toBe(nextTranslationRequest.translation_task_id)
  await expect.poll(async () => (await request.get(`${baseURL}/api/runs/${nextTranslationRun.id}`).then((response) => response.json())).status, { timeout: 120000 }).toBe('passed')
  await expect(page.getByTestId('formal-translate')).toBeEnabled()
  await page.getByRole('button', { name: '交付', exact: true }).click()
  await page.getByTestId(`delivery-generate-${nextTranslationRun.id}`).click()
  await expect(page.getByTestId(`delivery-current-${nextTranslationRun.id}`).getByRole('button', { name: '重新生成交付', exact: true })).toBeVisible()
  await page.locator('main').getByRole('button', { name: '新翻译任务', exact: true }).click()
  await expect(page.getByTestId('step-menu-toggle')).toContainText('项目资料')
  await expect(page.locator('.workflow-file-link')).toHaveCount(0)
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
  execFileSync(process.env.LWS_E2E_PYTHON || 'python', ['-X', 'utf8', '-c', `
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

test('user can upload an existing translated workbook and run QA directly', async ({ page, request }) => {
  const translatedWorkbook = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'lws-direct-qa-')), 'translated.xlsx')
  execFileSync(process.env.LWS_E2E_PYTHON || 'python', ['-X', 'utf8', '-c', `
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
  const directQaCreated = page.waitForResponse((response) => response.request().method() === 'POST'
    && new URL(response.url()).pathname === '/api/runs' && response.request().postDataJSON().kind === 'qa')
  await page.getByTestId('run-qa').click()
  const directQaResponse = await directQaCreated
  expect(directQaResponse.ok()).toBeTruthy()
  expect(directQaResponse.request().postDataJSON().translation_task_id).toMatch(/^translation-task-/)
  const directQaRun = await directQaResponse.json()
  expect(directQaRun.metadata.translation_task_id).toBe(directQaResponse.request().postDataJSON().translation_task_id)
  await expect(page.locator('.qa-outcome-panel.ready')).toContainText('QA 已通过', { timeout: 60000 })
  const completedDirectQa = await request.get(`${baseURL}/api/runs/${directQaRun.id}`).then((response) => response.json())
  expect(completedDirectQa.metadata.translation_task_id).toBe(directQaRun.metadata.translation_task_id)
  await page.getByRole('button', { name: '交付', exact: true }).click()
  await expect(page.locator('.delivery-head span', { hasText: /QA-[0-9a-f]{6}/ }).first()).toBeVisible({ timeout: 30000 })
  await page.getByRole('button', { name: '\u751f\u6210\u4ea4\u4ed8\u6587\u4ef6' }).click()
  await expect(inlineStatus(page, '\u6700\u7ec8\u4ea4\u4ed8\u5df2\u751f\u6210\uff1a2 \u4e2a\u6587\u4ef6')).toBeVisible({ timeout: 30000 })
  await expect(page.getByRole('link', { name: '\u4e0b\u8f7d\u6700\u7ec8\u8bd1\u6587' })).toBeVisible()

  await page.getByRole('button', { name: '译文归档', exact: true }).click()
  await expect(page.getByText('项目译文归档')).toBeVisible()
  await expect(page.locator('.translation-archive-table')).toContainText('Claim rewards')
})
