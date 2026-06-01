import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

const baseURL = process.env.E2E_BASE_URL ?? 'http://127.0.0.1:15173'
const sourceWorkbook = process.env.E2E_SOURCE_WORKBOOK ?? path.resolve('..', 'examples', 'synthetic-language.xlsx')
const fileName = (value: string) => path.basename(value.replace(/\\/g, '/'))
const inlineStatus = (page: any, text: string) => page.locator('.inline-status', { hasText: text })

test.use({ acceptDownloads: true })

test('user can complete the EN localization workflow from project tabs', async ({ page, request }) => {
  await request.patch(`${baseURL}/api/settings`, {
    data: {
      provider: 'mock',
      protocol: 'chat-completions',
      api_key: '',
      model: 'mock-localization',
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
  await expect(page.getByText('累计任务')).toBeVisible()
  await expect(page.getByText('CN 归档源文')).toBeVisible()
  await expect(page.getByRole('button', { name: projectName })).toBeVisible()

  await page.getByText('编辑项目元信息 / 重新生成输入').click()
  await page.getByLabel('题材/分类').fill('飞行射击')
  await page.getByLabel('来源标注、目标语言、风格要求、素材来源').fill('来源：synthetic-language.xlsx\n目标语言：英语 EN\n风格：UI 短句清晰，术语统一。')
  await page.getByRole('button', { name: '保存元信息' }).click()
  await expect(page.getByText('项目元信息已保存')).toBeVisible()

  await page.getByPlaceholder('补充本次分析需要的上下文；留空时使用项目描述。').fill('小小战机：飞行射击项目，资源、战机、任务、奖励术语需统一。')
  await page.getByRole('button', { name: '🔄 重新生成' }).click()
  await expect(page.getByText('项目提示词已生成')).toBeVisible({ timeout: 20000 })
  await expect(page.getByText('只返回 JSONL')).toBeVisible()

  await page.getByRole('button', { name: '📚 术语表' }).click()
  await page.getByPlaceholder('ID').fill('T-1')
  await page.getByPlaceholder('CN').fill('战机')
  await page.locator('input[name="target"]').fill('Warplane')
  await page.locator('input[name="target_alt"]').fill('Fighter')
  await page.getByPlaceholder('分类').fill('unit')
  await page.getByPlaceholder('备注').fill('E2E manual glossary assertion')
  await page.getByRole('button', { name: '+ 新增 EN' }).click()
  await expect(inlineStatus(page, '词条已新增')).toBeVisible()
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
  await page.locator('label.upload-box', { hasText: '上传待翻译 workbook' }).locator('input[type="file"]').setInputFiles(sourceWorkbook)
  await expect(page.locator('.selected-input span', { hasText: fileName(sourceWorkbook) })).toBeVisible({ timeout: 15000 })
  await expect(page.getByTestId('formal-translate')).toBeEnabled()
  await page.getByTestId('formal-translate').click()
  await expect(inlineStatus(page, 'EN 翻译和 QA 已通过，最终产物已归档。')).toBeVisible({ timeout: 120000 })
  await expect(page.getByText('最近翻译任务')).toBeVisible()
  await expect(page.getByText('passed').first()).toBeVisible()

  await page.getByRole('button', { name: '🔧 校对' }).click()
  await expect(page.locator('.detail', { hasText: 'QA final workbook' })).toBeVisible()
  await expect(page.locator('.detail', { hasText: '上一翻译结果' })).toBeVisible()

  await page.getByRole('button', { name: '📥 交付' }).click()
  await expect(page.locator('.card-title .left', { hasText: '最终交付' })).toBeVisible()
  await expect(page.locator('.delivery-head strong', { hasText: /T-[0-9a-f]{6}/ }).first()).toBeVisible({ timeout: 30000 })
  await expect(page.getByText('处理条数')).toBeVisible()
  await page.getByRole('button', { name: '生成/刷新最终交付文件' }).click()
  await expect(inlineStatus(page, '最终交付已生成：2 个文件')).toBeVisible({ timeout: 30000 })
  await expect(page.getByText(new RegExp(`${projectName}_EN_\\d{12}_T-[0-9a-f]{6}_final\\.xlsx`))).toBeVisible()
  await expect(page.getByText(new RegExp(`${projectName}_EN_\\d{12}_T-[0-9a-f]{6}_changes\\.xlsx`))).toBeVisible()
})

test('real project formal translation is blocked while provider is mock', async ({ page, request }) => {
  await request.patch(`${baseURL}/api/settings`, {
    data: { provider: 'mock', protocol: 'chat-completions', api_key: '', model: 'mock-localization', batch_size: 24 },
  })
  const projectName = `小小战机 UI 阻断 ${Date.now()}`
  await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: '飞行射击', description: '真实项目不能用 mock 交付。' },
  })

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.getByRole('button', { name: '⚡ 翻译' }).click()
  await page.locator('label.upload-box', { hasText: '上传待翻译 workbook' }).locator('input[type="file"]').setInputFiles(sourceWorkbook)
  await expect(page.locator('.selected-input span', { hasText: fileName(sourceWorkbook) })).toBeVisible({ timeout: 15000 })
  await expect(page.getByTestId('formal-translate')).toBeDisabled()
  await expect(page.getByText('真实项目禁止用 mock 假装完成')).toBeVisible()
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
  await page.locator('label.upload-box', { hasText: '上传术语表 xlsx/csv/json' }).locator('input[type="file"]').setInputFiles(termWorkbook)
  await expect(inlineStatus(page, `已上传：${fileName(termWorkbook)}`)).toBeVisible({ timeout: 15000 })
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
  await expect(page.locator('.stat-grid')).toContainText('CN 术语概念')
  await expect(page.locator('.stat-grid')).toContainText('EN 1 / KR 1 / JP 1')

  await page.locator('.view-tabs .view-tab').nth(1).click()
  await expect(page.locator('.glossary-wide-table thead')).toContainText('EN')
  await expect(page.locator('.glossary-wide-table thead')).toContainText('EN2')
  await expect(page.locator('.glossary-wide-table thead')).toContainText('KR')
  await expect(page.locator('.glossary-wide-table thead')).toContainText('JP')
  await expect(page.locator('.glossary-wide-table thead')).not.toContainText('KR2')
  await expect(page.locator('.glossary-wide-table thead')).not.toContainText('JP2')
  const glossaryRow = page.locator('.glossary-wide-table tbody tr', { hasText: '战机' }).first()
  await expect(glossaryRow).toContainText('Warplane')
  await expect(glossaryRow).toContainText('Fighter')
  await expect(glossaryRow).toContainText('전투기')
  await expect(glossaryRow).toContainText('戦闘機')

  await page.locator('.view-tabs .view-tab').nth(4).click()
  const archiveRow = page.locator('.translation-wide-table tbody tr', { hasText: '领取奖励' }).first()
  await expect(page.locator('.translation-wide-table thead')).toContainText('EN')
  await expect(page.locator('.translation-wide-table thead')).toContainText('KR')
  await expect(page.locator('.translation-wide-table thead')).not.toContainText('JP')
  await expect(archiveRow).toContainText('Claim rewards')
  await expect(archiveRow).toContainText('보상 수령')
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
  await page.locator('label.upload-box', { hasText: '上传术语表 xlsx/csv/json' }).locator('input[type="file"]').setInputFiles(termWorkbook)
  await expect(inlineStatus(page, `已上传：${fileName(termWorkbook)}`)).toBeVisible({ timeout: 15000 })
  await page.getByRole('button', { name: '自动导入多语言术语' }).click()
  await expect(inlineStatus(page, /术语表已导入：5 条/)).toBeVisible({ timeout: 20000 })

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
  await page.locator('.check-row', { hasText: 'announcement_notice.txt' }).locator('input').check()
  await page.getByRole('button', { name: '\u521b\u5efa\u516c\u544a\u4efb\u52a1' }).click()
  await expect(page.locator('.panel-title', { hasText: '\u7ea6\u675f\u6765\u6e90' })).toBeVisible({ timeout: 20000 })
  await expect(page.locator('.announcement-subflow-strip')).toHaveCount(0)
  await page.locator('label.upload-box', { hasText: /XLSX/ }).locator('input[type="file"]').setInputFiles(languageTable)
  await expect(page.locator('.inline-status')).toContainText(fileName(languageTable), { timeout: 15000 })
  await expect(page.locator('.check-row', { hasText: fileName(languageTable) }).locator('input')).toBeChecked()
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
    if (label.includes('\u82f1\u8bed EN')) {
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
  await expect(page.locator('.inline-status')).toContainText(fileName(supplementResponse), { timeout: 15000 })
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
  await page.getByRole('button', { name: '\u751f\u6210\u7ffb\u8bd1\u51c6\u5907\u5305' }).click()
  await expect(page.locator('.panel-title', { hasText: 'AI \u7ffb\u8bd1 / \u5bfc\u5165' })).toBeVisible({ timeout: 30000 })
  await expect(page.locator('.panel-desc', { hasText: '\u4e0d\u4f1a\u4f7f\u7528\u8c37\u6b4c\u673a\u7ffb' })).toBeVisible()
  const processArtifacts = page.locator('.announcement-artifacts details.asset-list')
  await processArtifacts.locator('summary', { hasText: '\u8fc7\u7a0b\u4ea7\u7269 / \u5ba1\u8ba1\u4ea7\u7269' }).click()
  await expect(processArtifacts.getByRole('link', { name: /\u516c\u544a workpack \(EN\)/ })).toBeVisible()
  await expect(processArtifacts.getByRole('link', { name: /\u516c\u544a\u7ffb\u8bd1\u4e2d\u8f6c\u8868/ })).toBeVisible()

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

  await page.locator('label.upload-box', { hasText: '\u4e0a\u4f20 ai_response_<lang>.jsonl' }).locator('input[type="file"]').setInputFiles(responseFile)
  await expect(page.locator('.inline-status')).toContainText(fileName(responseFile), { timeout: 15000 })
  await page.getByRole('button', { name: '\u5bfc\u5165 AI response' }).click()
  await expect(page.locator('.panel-title', { hasText: '\u6821\u5bf9\u56de\u586b' })).toBeVisible({ timeout: 20000 })
  await page.getByRole('button', { name: 'QA \u5e76\u56de\u586b\u540c\u683c\u5f0f\u6587\u4ef6' }).click()
  await expect(page.locator('.panel-title', { hasText: '\u4ea4\u4ed8' })).toBeVisible({ timeout: 30000 })
  await expect(page.getByRole('link', { name: /\u516c\u544a\u6210\u54c1 \(EN\)/ })).toBeVisible()
  await page.getByRole('button', { name: '\u751f\u6210\u4ea4\u4ed8\u603b\u5305' }).click()
  await expect(page.getByRole('link', { name: /\u516c\u544a\u4ea4\u4ed8\u603b\u5305/ })).toBeVisible({ timeout: 30000 })
  await expect(page.locator('.announcement-subflow-card', { hasText: '\u82f1\u8bed EN' })).toContainText('delivered')
  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await expect(page.locator('.announcement-project-panel .mini-lang')).toHaveCount(0)
  await expect(page.locator('.announcement-project-panel')).not.toContainText('terms_ready')
  await page.locator('.announcement-task-row', { hasText: 'announcement_notice.txt' }).getByRole('button', { name: '\u7ee7\u7eed' }).click()

  const stepTitles = ['\u516c\u544a\u8d44\u6599', '\u7ea6\u675f\u6765\u6e90', '\u76ee\u6807\u8bed\u8a00', '\u672f\u8bed\u63d0\u53d6', '\u8bd1\u6587\u53cd\u67e5', '\u7ffb\u8bd1\u51c6\u5907', 'AI \u7ffb\u8bd1 / \u5bfc\u5165', '\u6821\u5bf9\u56de\u586b', '\u4ea4\u4ed8']
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
  await page.locator('label.upload-box', { hasText: '上传新的译文 workbook' }).locator('input[type="file"]').setInputFiles(translatedWorkbook)
  await expect(inlineStatus(page, '已有译文已登记')).toBeVisible({ timeout: 15000 })
  await page.getByTestId('run-qa').click()
  await expect(inlineStatus(page, '已有译文 QA 通过')).toBeVisible({ timeout: 60000 })
  await expect(page.getByText('最近校对任务')).toBeVisible()
  await expect(page.locator('.tag-done', { hasText: 'passed' }).first()).toBeVisible()
  await page.getByRole('button', { name: '📥 交付' }).click()
  await expect(page.locator('.delivery-head strong', { hasText: /QA-[0-9a-f]{6}/ }).first()).toBeVisible({ timeout: 30000 })
  await page.getByRole('button', { name: '生成/刷新最终交付文件' }).click()
  await expect(inlineStatus(page, '最终交付已生成：2 个文件')).toBeVisible({ timeout: 30000 })
  await expect(page.getByText(new RegExp(`${projectName}_EN_\\d{12}_QA-[0-9a-f]{6}_final\\.xlsx`))).toBeVisible()

  await page.getByRole('button', { name: '🗄️ 译文归档' }).click()
  await expect(page.getByText('项目译文归档')).toBeVisible()
  await expect(page.locator('.translation-archive-table')).toContainText('Claim rewards')
})
