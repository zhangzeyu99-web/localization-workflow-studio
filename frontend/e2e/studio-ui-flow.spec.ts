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
  await expect(page.getByRole('heading', { name: 'Localization Workflow Studio' })).toBeVisible()

  await page.getByRole('button', { name: '+ 新建项目' }).click()
  await expect(page.getByRole('heading', { name: '🆕 新建本地化项目' })).toBeVisible()
  await page.getByPlaceholder('例如：星际边境 / 机甲纪元').fill(projectName)
  await page.locator('select[name="type"]').selectOption({ label: '科幻 SLG' })
  await page.getByPlaceholder('🎮').fill('')
  await page.getByPlaceholder('目标用户、题材、语气要求').fill('来源：E2E 合成语言表。目标语言：英语 EN。风格：短句准确。')
  await page.getByRole('button', { name: '创建' }).click()

  await expect(page.getByRole('heading', { name: projectName })).toBeVisible({ timeout: 15000 })
  await expect(page.getByText('累计任务')).toBeVisible()
  await expect(page.getByRole('button', { name: projectName })).toBeVisible()

  await page.getByLabel('题材/分类').fill('飞行射击')
  await page.getByLabel('来源标注、目标语言、风格要求、素材来源').fill('来源：synthetic-language.xlsx\n目标语言：英语 EN\n风格：UI 短句清晰，术语统一。')
  await page.getByRole('button', { name: '保存元信息' }).click()
  await expect(page.getByText('项目元信息已保存')).toBeVisible()

  await page.getByPlaceholder('补充本次分析需要的上下文；留空时使用项目描述。').fill('小小战机：飞行射击项目，资源、战机、任务、奖励术语需统一。')
  await page.getByRole('button', { name: '生成/更新' }).click()
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
  await expect(page.locator('input[value="战机"]').first()).toBeVisible()
  await expect(page.locator('input[value="Warplane"]').first()).toBeVisible()
  await expect(page.locator('input[value="Fighter"]').first()).toBeVisible()

  await page.getByRole('button', { name: '翻译' }).click()
  await page.locator('label.upload-box', { hasText: '上传待翻译 workbook' }).locator('input[type="file"]').setInputFiles(sourceWorkbook)
  await expect(page.locator('.selected-input span', { hasText: fileName(sourceWorkbook) })).toBeVisible({ timeout: 15000 })
  await expect(page.getByTestId('formal-translate')).toBeEnabled()
  await page.getByTestId('formal-translate').click()
  await expect(page.getByText('EN 闭环通过，产物已归档')).toBeVisible({ timeout: 120000 })
  await expect(page.getByText('最近翻译任务')).toBeVisible()
  await expect(page.getByText('passed')).toBeVisible()

  await page.getByRole('button', { name: '校对' }).click()
  await expect(page.getByText('最近翻译任务')).toBeVisible()
  await expect(page.getByText('passed')).toBeVisible()

  await page.getByRole('button', { name: '交付' }).click()
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
  await page.getByRole('button', { name: '翻译' }).click()
  await page.locator('label.upload-box', { hasText: '上传待翻译 workbook' }).locator('input[type="file"]').setInputFiles(sourceWorkbook)
  await expect(page.locator('.selected-input span', { hasText: fileName(sourceWorkbook) })).toBeVisible({ timeout: 15000 })
  await expect(page.getByTestId('formal-translate')).toBeDisabled()
  await expect(page.getByText('真实项目禁止用 mock 假装完成')).toBeVisible()
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
  await page.getByRole('button', { name: '校对' }).click()
  await page.locator('label.upload-box', { hasText: '上传已有译文 workbook' }).locator('input[type="file"]').setInputFiles(translatedWorkbook)
  await expect(page.getByText('已有译文已登记')).toBeVisible({ timeout: 15000 })
  await page.getByTestId('run-qa').click()
  await expect(page.getByText('已有译文 QA 通过')).toBeVisible({ timeout: 60000 })
  await expect(page.getByText('最近校对任务')).toBeVisible()
  await expect(page.getByText('passed')).toBeVisible()
})
