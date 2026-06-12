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
  await expect(page.getByRole('heading', { name: '🎮 游戏翻译本地化 · 项目工作台' })).toBeVisible()

  await page.getByRole('button', { name: '+ 新建项目' }).click()
  await expect(page.getByRole('heading', { name: '🆕 新建本地化项目' })).toBeVisible()
  await page.getByPlaceholder('例如：星际边境 / 机甲纪元').fill(projectName)
  await page.locator('.modal select').selectOption({ label: '科幻 SLG' })
  await page.getByPlaceholder('🎮').fill('')
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
  const promptProjects = await request.get(`${baseURL}/api/projects`).then((response) => response.json())
  const promptSavedProject = promptProjects.find((item: { name: string }) => item.name === projectName)
  expect(promptSavedProject.prompt_text).toBe(manualPrompt)
  expect(promptSavedProject.profile.prompts_by_language.en).toBe(manualPrompt)
  expect(promptSavedProject.profile.display_prompts_by_language.en).toBe(manualPrompt)

  await page.getByRole('button', { name: '📚 术语表' }).click()
  await page.getByTestId('manual-glossary-tools').locator('summary').click()
  await page.locator('input[name="term_key"]').fill('T-1')
  await page.locator('input[name="source"]').fill('战机')
  await page.locator('input[name="target"]').fill('Warplane')
  await page.locator('input[name="target_alt"]').fill('Fighter')
  await page.locator('input[name="category"]').fill('unit')
  await page.locator('input[name="note"]').fill('E2E manual glossary assertion')
  await page.getByRole('button', { name: '+ 新增 EN' }).click()
  await expect(inlineStatus(page, '词条已新增')).toBeVisible()
  await page.getByTestId('glossary-search').fill('战机')
  const glossaryRow = page.locator('.glossary-table tbody tr').first()
  await expect(glossaryRow.getByText('战机')).toBeVisible()
  await expect(glossaryRow.getByText('Warplane')).toBeVisible()
  await expect(glossaryRow.getByText('Fighter')).toBeVisible()
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
  expect(exportedTerms).toContainEqual(expect.objectContaining({ source: '战机', target: 'Fighter Jet', target_alt: 'Fighter' }))
  expect(Object.keys(exportedTerms[0])).not.toContain('source_type')
  expect(Object.keys(exportedTerms[0])).not.toContain('confirmed')

  await page.getByRole('button', { name: '⚡ 翻译' }).click()
  await page.locator('label.upload-box', { hasText: '上传待翻译表格' }).locator('input[type="file"]').setInputFiles(sourceWorkbook)
  await expect(page.locator('.selected-input span', { hasText: fileStem(sourceWorkbook) })).toBeVisible({ timeout: 15000 })
  await expect(page.getByTestId('formal-translate')).toBeEnabled()
  await page.getByTestId('formal-translate').click()
  await expect(inlineStatus(page, 'EN 翻译和 QA 已通过，最终产物已归档。')).toBeVisible({ timeout: 120000 })
  await expect(page.getByText('最近翻译任务')).toBeVisible()
  await expect(page.getByText('passed').first()).toBeVisible()

  await page.getByRole('button', { name: '🔧 校对' }).click()
  await expect(page.locator('.qa-current-card')).toContainText('QA 已通过')
  await expect(page.locator('.qa-current-card')).toContainText('QA final workbook')
  await expect(page.locator('.qa-current-card')).toContainText('上一翻译结果')

  await page.getByRole('button', { name: '📥 交付' }).click()
  await expect(page.locator('.card-title .left', { hasText: '最终交付' })).toBeVisible()
  await expect(page.locator('.delivery-card').first()).toBeVisible({ timeout: 30000 })
  await expect(page.getByText('任务进度')).toBeVisible()
  await expect(page.getByText('交付结果')).toBeVisible()
  await page.getByRole('button', { name: '生成交付文件' }).click()
  await expect(inlineStatus(page, '最终交付已生成：2 个文件')).toBeVisible({ timeout: 30000 })
  await expect(page.getByRole('link', { name: '下载最终译文' })).toBeVisible()
  await expect(page.getByRole('link', { name: '下载修改记录' })).toBeVisible()
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
  await page.getByRole('button', { name: '⚡ 翻译' }).click()
  await page.locator('label.upload-box', { hasText: '上传待翻译表格' }).locator('input[type="file"]').setInputFiles(sourceWorkbook)
  await expect(page.locator('.selected-input span', { hasText: fileStem(sourceWorkbook) })).toBeVisible({ timeout: 15000 })
  await expect(page.getByTestId('formal-translate')).toBeDisabled()
  await expect(page.locator('.warn-line', { hasText: 'API' })).toBeVisible()
  await expect(page.locator('.warn-line', { hasText: '右上角“设置”填写 API 密钥' })).toBeVisible()
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
  await page.locator('.announcement-steps .step-item').nth(6).click()
  await expect(page.locator('.panel-title', { hasText: 'AI 翻译' })).toBeVisible()
  await expect(page.locator('.warn-line', { hasText: '需要先配置 API' })).toBeVisible()
  await expect(page.locator('.warn-line', { hasText: '右上角“设置”填写 API 密钥' })).toBeVisible()
  await expect(page.getByRole('button', { name: /^AI\s?\u7ffb\u8bd1$/ })).toBeDisabled()
})

test('new translation task exposes the full supported language set', async ({ page, request }) => {
  const projectName = `E2E Full Languages ${Date.now()}`
  await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'language-ui', description: 'Full language selector smoke.' },
  })

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.getByRole('button', { name: '🚀 启动新翻译任务' }).click()
  await page.getByRole('button', { name: '6 目标语言' }).click()

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
  ]) {
    await expect(page.getByRole('button', { name: label })).toBeVisible()
  }
  await expect(page.getByRole('button', { name: 'AR 阿拉伯语' })).toHaveCount(0)
  await expect(page.getByText('其他语言未开放')).toHaveCount(0)
  const enButton = page.getByRole('button', { name: /EN 英语/ })
  const krButton = page.getByRole('button', { name: /KR 韩语/ })
  const jpButton = page.getByRole('button', { name: /JP 日语/ })
  await krButton.click()
  await jpButton.click()
  await expect(enButton).toHaveClass(/selected/)
  await expect(krButton).toHaveClass(/selected/)
  await expect(jpButton).toHaveClass(/selected/)
  await expect(jpButton).toHaveClass(/current/)
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
  await page.getByRole('button', { name: '+ 新建项目' }).click()
  await page.locator('input[name="name"]').fill(`E2E Create Fail ${Date.now()}`)
  await page.getByRole('button', { name: '创建' }).click()
  await expect(page.getByTestId('new-project-error')).toContainText('backend unavailable')
  await expect(page.getByRole('heading', { name: '🆕 新建本地化项目' })).toBeVisible()
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
  await page.getByTestId('step-4').click()
  await page.locator('.asset-select select').selectOption(upload.id)
  await page.getByTestId('step-7').click()
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
  await page.getByRole('button', { name: '🚀 启动新翻译任务' }).click()
  await page.getByRole('button', { name: '3 术语表' }).click()
  await page.locator('label.upload-box', { hasText: '上传术语表模板 xlsx/csv/json' }).locator('input[type="file"]').setInputFiles(termWorkbook)
  await expect(inlineStatus(page, `已上传：上传术语表｜${fileStem(termWorkbook)}`)).toBeVisible({ timeout: 15000 })
  await page.getByRole('button', { name: '预览术语' }).click()
  await expect(inlineStatus(page, '术语表预览完成：2 条')).toBeVisible({ timeout: 20000 })
  await page.getByRole('button', { name: '导入到项目术语' }).click()
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
  await page.getByRole('button', { name: /\u542f\u52a8\u65b0\u7ffb\u8bd1\u4efb\u52a1/ }).click()

  await page.locator('label.upload-box', { hasText: /\u4e0a\u4f20 Markdown/ }).locator('input[type="file"]').setInputFiles(languageTable)
  await expect(inlineStatus(page, /\u5b8c\u6574\u8bed\u8a00\u8868|STEP4/)).toBeVisible({ timeout: 20000 })
  await expect.poll(async () => {
    const assets = await request.get(`${baseURL}/api/projects/${project.id}/assets?role=project_material`).then((response) => response.json())
    return assets.length
  }, { timeout: 20000 }).toBe(0)

  await page.getByRole('button', { name: /4\s+\u5224\u5b9a\u8f93\u5165/ }).click()
  await page.locator('label.upload-box', { hasText: /\u4e0a\u4f20 ID \/ CN/ }).locator('input[type="file"]').setInputFiles(languageTable)
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
  await page.getByTestId('step-5').click()
  await page.getByRole('button', { name: /扫描术语候选/ }).click()
  await expect.poll(() => extractPayload?.input_artifact_id || '', { timeout: 10000 }).toBe(uploadedLanguageTable.id)
  expect(extractPayload.language).toBe('ko')
})

test('project tabs show multilingual wide glossary and archive assets', async ({ page, request }) => {
  const projectName = `E2E Wide Assets ${Date.now()}`
  const createResponse = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'wide', description: 'Multilingual wide table smoke.' },
  })
  const project = await createResponse.json()
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
  await expect(page.locator('.glossary-wide-table thead')).toContainText('EN')
  await expect(page.locator('.glossary-wide-table thead')).toContainText('EN2')
  await expect(page.locator('.glossary-wide-table thead')).not.toContainText('KR')
  await expect(page.locator('.glossary-wide-table thead')).not.toContainText('JP')
  await expect(page.locator('.glossary-wide-table thead')).not.toContainText('KR2')
  await expect(page.locator('.glossary-wide-table thead')).not.toContainText('JP2')
  await page.getByTestId('glossary-display-lang-ko').click()
  await page.getByTestId('glossary-display-lang-ja').click()
  await expect(page.locator('.glossary-wide-table thead')).toContainText('KR')
  await expect(page.locator('.glossary-wide-table thead')).toContainText('JP')
  const glossaryRow = page.locator('.glossary-wide-table tbody tr', { hasText: '战机' }).first()
  await expect(glossaryRow).toContainText('Warplane')
  await expect(glossaryRow).toContainText('Fighter')
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
  await expect(wideRow).toContainText('Fighter')
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
  await page.locator('.announcement-steps .step-item').nth(1).click()
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
  await expect(page.locator('.announcement-panel .announcement-language-chip')).toHaveCount(12)
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
  await page.locator('.announcement-steps .step-item').nth(3).click()
  await expect(page.locator('.panel-title', { hasText: '\u672f\u8bed\u63d0\u53d6' })).toBeVisible()
  const termsTable = page.locator('.announcement-terms-table')
  await expect(termsTable.locator('tbody tr')).toHaveCount(2, { timeout: 30000 })
  await expect(termsTable.locator('tbody tr').nth(0).locator('input').nth(1)).toHaveValue('\u79d8\u5883')
  await expect(termsTable.locator('tbody tr').nth(1).locator('input').nth(1)).toHaveValue('\u661f\u754c\u88c2\u9699')
  await expect(termsTable.locator('tbody tr').nth(1).locator('input').nth(2)).toHaveValue('Astral Rift')
  await expect(page.getByRole('link', { name: '\u5bfc\u51fa XLSX' })).toBeVisible()
  await expect(page.getByRole('link', { name: '\u4e0b\u8f7d\u68c0\u67e5\u5305' })).toBeVisible()
  await expect(page.getByRole('link', { name: '\u4e0b\u8f7d AI \u62a5\u544a' })).toBeVisible()
  await page.locator('.announcement-steps .step-item').nth(4).click()
  await expect(page.locator('.panel-title', { hasText: '\u8bd1\u6587\u53cd\u67e5' })).toBeVisible({ timeout: 20000 })
  await page.getByRole('button', { name: '\u53cd\u67e5\u672f\u8bed\u8bd1\u6587' }).click()
  await expect(page.locator('.panel-title', { hasText: '\u7ffb\u8bd1\u51c6\u5907' })).toBeVisible({ timeout: 20000 })
  await page.getByRole('button', { name: '\u751f\u6210\u7ffb\u8bd1\u51c6\u5907' }).click()
  await expect(page.locator('.panel-title', { hasText: 'AI \u7ffb\u8bd1' })).toBeVisible({ timeout: 30000 })
  await expect(page.locator('.panel-desc', { hasText: '\u4e0d\u4f1a\u4f7f\u7528\u8c37\u6b4c\u673a\u7ffb' })).toBeVisible()
  await expect(page.locator('.announcement-artifacts')).toHaveCount(0)
  await page.getByText('\u8fc7\u7a0b\u6587\u4ef6\u4e0e\u5ba1\u8ba1\uff08\u53ef\u9009\uff09').click()
  const processArtifacts = page.locator('.asset-list', { hasText: '\u51c6\u5907\u4ea7\u7269\u4e0b\u8f7d' })
  await expect(processArtifacts.getByText(/\u516c\u544a Workpack.*EN/)).toBeVisible()
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
  await page.getByRole('button', { name: '📥 交付' }).click()
  await expect(page.getByRole('link', { name: '下载交付包' })).toBeVisible({ timeout: 30000 })
  await expect(page.getByRole('link', { name: '下载成品' })).toBeVisible()
  await expect(page.getByRole('link', { name: '下载 QA 摘要' })).toBeVisible()
  await page.getByRole('button', { name: '📣 公告翻译' }).click()
  await expect(page.locator('.panel-title', { hasText: '\u516c\u544a\u8d44\u6599' })).toBeVisible()
  await expect(page.locator('.announcement-current-task')).toHaveCount(0)
  await page.getByRole('button', { name: '\u2190 \u8fd4\u56de\u9879\u76ee\u6982\u89c8' }).click()
  const deliveredAnnouncementRow = page.locator('.announcement-task-row', { hasText: 'announcement_notice.txt' })
  await expect(deliveredAnnouncementRow.getByRole('button', { name: '\u7ee7\u7eed' })).toHaveCount(0)
  await deliveredAnnouncementRow.getByRole('button', { name: '\u67e5\u770b\u4ea4\u4ed8' }).click()

  const stepTitles = ['\u516c\u544a\u8d44\u6599', '\u7ea6\u675f\u6765\u6e90', '\u76ee\u6807\u8bed\u8a00', '\u672f\u8bed\u63d0\u53d6', '\u8bd1\u6587\u53cd\u67e5', '\u7ffb\u8bd1\u51c6\u5907', 'AI \u7ffb\u8bd1', '\u6821\u5bf9\u56de\u586b', '\u4ea4\u4ed8']
  for (const [index, title] of stepTitles.entries()) {
    await page.locator('.announcement-steps .step-item').nth(index).click()
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
  await page.getByRole('button', { name: '🔧 校对' }).click()
  await page.locator('label.upload-box', { hasText: '上传新的译文表格' }).locator('input[type="file"]').setInputFiles(translatedWorkbook)
  await expect(inlineStatus(page, '已有译文已登记')).toBeVisible({ timeout: 15000 })
  await page.getByTestId('run-qa').click()
  await expect(inlineStatus(page, '已有译文 QA 通过')).toBeVisible({ timeout: 60000 })
  await expect(page.locator('.qa-current-card')).toContainText('QA 已通过')
  await expect(page.locator('.tag-done', { hasText: '已通过' }).first()).toBeVisible()
  await page.getByRole('button', { name: '📥 交付' }).click()
  await expect(page.locator('.delivery-head span', { hasText: /QA-[0-9a-f]{6}/ }).first()).toBeVisible({ timeout: 30000 })
  await page.getByRole('button', { name: '\u751f\u6210\u4ea4\u4ed8\u6587\u4ef6' }).click()
  await expect(inlineStatus(page, '\u6700\u7ec8\u4ea4\u4ed8\u5df2\u751f\u6210\uff1a2 \u4e2a\u6587\u4ef6')).toBeVisible({ timeout: 30000 })
  await expect(page.getByRole('link', { name: '\u4e0b\u8f7d\u6700\u7ec8\u8bd1\u6587' })).toBeVisible()

  await page.getByRole('button', { name: '🗄️ 译文归档' }).click()
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
  await page.getByRole('button', { name: '\ud83d\ude80 \u542f\u52a8\u65b0\u7ffb\u8bd1\u4efb\u52a1' }).click()
  await page.getByRole('button', { name: '4 \u5224\u5b9a\u8f93\u5165' }).click()
  await page.locator('label.upload-box', { hasText: /\u4e0a\u4f20 ID \/ CN/ }).locator('input[type="file"]').setInputFiles(translatedWorkbook)
  await expect(page.locator('.ai-card', { hasText: fileName(translatedWorkbook) }).last()).toBeVisible({ timeout: 15000 })

  await page.getByRole('button', { name: '7 AI \u7ffb\u8bd1' }).click()
  await expect(page.getByRole('button', { name: '\u8df3\u5230\u6821\u5bf9' })).toBeVisible({ timeout: 15000 })
  await page.getByRole('button', { name: '\u8df3\u5230\u6821\u5bf9' }).click()

  const skipPanel = page.locator('details', { hasText: '\u4e34\u65f6\u8df3\u8fc7 QA \u76f4\u63a5\u5f52\u6863' })
  await expect(skipPanel).toBeVisible()
  await skipPanel.locator('summary').click()
  page.once('dialog', (dialog) => dialog.accept())
  await skipPanel.getByRole('button', { name: '\u786e\u8ba4\u8df3\u8fc7 QA \u5e76\u5f52\u6863' }).click()
  await expect(inlineStatus(page, '\u5df2\u8df3\u8fc7 QA \u5e76\u5bfc\u5165\u8bd1\u6587\u5f52\u6863').first()).toBeVisible({ timeout: 30000 })

  await page.getByRole('button', { name: /\u8fd4\u56de\u9879\u76ee\u6982\u89c8/ }).click()
  await page.getByRole('button', { name: /\u8bd1\u6587\u5f52\u6863/ }).click()
  await expect(page.getByText('\u9879\u76ee\u8bd1\u6587\u5f52\u6863')).toBeVisible()
  await expect(page.locator('.translation-archive-table')).toContainText('Claim rewards')

  await page.locator('.view-tabs .view-tab', { hasText: '\u6821\u5bf9' }).click()
  await expect(page.locator('details', { hasText: '\u4e34\u65f6\u8df3\u8fc7 QA \u76f4\u63a5\u5f52\u6863' })).toHaveCount(0)
})


test('wizard QA refreshes readiness after manually selecting another translated language table', async ({ page, request }) => {
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
  await page.getByRole('button', { name: '\ud83d\ude80 \u542f\u52a8\u65b0\u7ffb\u8bd1\u4efb\u52a1' }).click()
  await page.getByRole('button', { name: '8 QA \u6821\u5bf9' }).click()
  await page.locator('.step-panel.active label.asset-select select').selectOption(translatedArtifact.id)

  const skipPanel = page.locator('details', { hasText: '\u4e34\u65f6\u8df3\u8fc7 QA \u76f4\u63a5\u5f52\u6863' })
  await skipPanel.locator('summary').click()
  await expect(skipPanel.getByRole('button', { name: '\u786e\u8ba4\u8df3\u8fc7 QA \u5e76\u5f52\u6863' })).toBeEnabled({ timeout: 15000 })
})
