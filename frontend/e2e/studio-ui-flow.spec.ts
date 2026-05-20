import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

const baseURL = process.env.E2E_BASE_URL ?? 'http://127.0.0.1:15173'
const sourceWorkbook = process.env.E2E_SOURCE_WORKBOOK ?? path.resolve('..', 'examples', 'synthetic-language.xlsx')
const fileName = (value: string) => path.basename(value.replace(/\\/g, '/'))

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
  await page.locator('select[name="type"]').selectOption({ label: '科幻 SLG' })
  await page.getByPlaceholder('🎮').fill('')
  await page.getByPlaceholder('目标用户、题材、语气要求').fill('来源：E2E 合成语言表。目标语言：英语 EN。风格：短句准确。')
  await page.getByRole('button', { name: '创建' }).click()

  await expect(page.getByRole('heading', { name: projectName })).toBeVisible({ timeout: 15000 })
  await expect(page.getByText('累计翻译任务')).toBeVisible()
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
  await page.getByRole('button', { name: '+ 新增' }).click()
  await expect(page.getByText('词条已新增')).toBeVisible()
  const glossaryRow = page.locator('.glossary-table tbody tr').first()
  await expect(glossaryRow.getByText('战机')).toBeVisible()
  await expect(glossaryRow.getByText('Warplane')).toBeVisible()
  await expect(glossaryRow.getByText('Fighter')).toBeVisible()
  await glossaryRow.getByRole('button', { name: '编辑' }).click()
  await glossaryRow.locator('input').nth(2).fill('Fighter Jet')
  await glossaryRow.getByRole('button', { name: '保存' }).click()
  await expect(page.getByText('词条已保存')).toBeVisible()
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
  await expect(page.getByText('EN 闭环通过，产物已归档')).toBeVisible({ timeout: 120000 })
  await expect(page.getByText('最近翻译任务')).toBeVisible()
  await expect(page.getByText('passed').first()).toBeVisible()

  await page.getByRole('button', { name: '🔧 校对' }).click()
  await expect(page.getByText('最近翻译任务')).toBeVisible()
  await expect(page.locator('.tag-done', { hasText: 'passed' }).first()).toBeVisible()

  await page.getByRole('button', { name: '📥 交付' }).click()
  await page.getByRole('button', { name: '生成任务交付' }).click()
  await expect(page.getByText('任务交付已生成：2 个文件')).toBeVisible({ timeout: 30000 })
  await expect(page.locator('strong', { hasText: `${projectName}_translated.xlsx` })).toBeVisible()
  await expect(page.locator('strong', { hasText: `${projectName}_qa_changes.xlsx` })).toBeVisible()
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
  await expect(page.getByText(`已上传：${fileName(termWorkbook)}`)).toBeVisible({ timeout: 15000 })
  await page.getByRole('button', { name: '预览术语' }).click()
  await expect(page.getByText('术语表预览完成：2 条')).toBeVisible({ timeout: 20000 })
  await page.getByRole('button', { name: '导入到项目术语' }).click()
  await expect(page.getByText('术语表已导入：2 条')).toBeVisible({ timeout: 20000 })

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
  await page.locator('label.upload-box', { hasText: '上传已有译文 workbook' }).locator('input[type="file"]').setInputFiles(translatedWorkbook)
  await expect(page.getByText('已有译文已登记')).toBeVisible({ timeout: 15000 })
  await page.getByTestId('run-qa').click()
  await expect(page.getByText('已有译文 QA 通过')).toBeVisible({ timeout: 60000 })
  await expect(page.getByText('最近校对任务')).toBeVisible()
  await expect(page.locator('.tag-done', { hasText: 'passed' }).first()).toBeVisible()
})
