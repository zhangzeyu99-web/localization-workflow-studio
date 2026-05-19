import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

const baseURL = process.env.E2E_BASE_URL ?? 'http://127.0.0.1:5173'
const sourceWorkbook = process.env.E2E_SOURCE_WORKBOOK ?? path.resolve('..', 'examples', 'synthetic-language.xlsx')
const termWorkbook = process.env.E2E_TERM_WORKBOOK || ''
const fileName = (value: string) => path.basename(value.replace(/\\/g, '/'))

test.use({ acceptDownloads: true })

test('user can complete the EN localization workflow from the web UI', async ({ page, request }) => {
  await request.patch(`${baseURL}/api/settings`, {
    data: {
      provider: 'mock',
      protocol: 'chat-completions',
      base_url: 'https://api.openai.com',
      api_key: '',
      model: 'mock-localization',
      batch_size: 24,
    },
  })

  const projectName = `E2E 明日2 回归 ${Date.now()}`

  await page.goto(baseURL)
  await expect(page.getByRole('heading', { name: '游戏翻译本地化 · 项目工作台' })).toBeVisible()

  await page.getByRole('button', { name: '+ 新建项目' }).click()
  await expect(page.getByRole('heading', { name: '🆕 新建本地化项目' })).toBeVisible()
  await page.getByPlaceholder('例如：星际边境 / 机甲纪元').fill(projectName)
  await page.locator('select[name="type"]').selectOption({ label: '科幻 SLG' })
  await page.getByPlaceholder('🎮').fill('🧪')
  await page.getByPlaceholder('目标用户、题材、语气要求').fill('近期明日2任务回归，验证网页到后端闭环。')
  await page.getByRole('button', { name: '创建' }).click()

  await expect(page.getByRole('heading', { name: `🧪 ${projectName}` })).toBeVisible({ timeout: 15000 })
  await expect(page.getByText('累计任务')).toBeVisible()

  await page.getByRole('button', { name: '🧭 Project Harness' }).click()
  await expect(page.getByText('整体 Harness（所有项目复用）')).toBeVisible()
  await expect(page.getByText('项目 Harness（仅当前项目）')).toBeVisible()
  await page.getByPlaceholder('只写当前项目特有要求，不写进整体 harness。').fill('本项目 UI 文案保持简洁，排行榜与联盟术语保持统一。')
  await page.getByRole('button', { name: '保存 Project Harness' }).click()
  await expect(page.getByText('Project Harness 已保存，仅对当前项目生效')).toBeVisible()

  await page.getByRole('button', { name: '📚 术语表' }).click()
  await expect(page.getByText('项目术语表')).toBeVisible()
  await page.getByPlaceholder('原文术语').fill('最强指挥官')
  await page.getByPlaceholder('译文 EN').fill('Strongest Commander')
  await page.getByPlaceholder('类型').fill('manual-regression')
  await page.getByPlaceholder('备注').fill('E2E manual glossary assertion')
  await page.getByRole('button', { name: '+ 新增' }).click()
  await expect(page.getByRole('cell', { name: '最强指挥官' })).toBeVisible()
  await expect(page.getByRole('cell', { name: 'Strongest Commander' })).toBeVisible()

  await page.getByRole('button', { name: '🚀 启动新翻译任务' }).click()
  await expect(page.getByText('STEP 1')).toBeVisible()
  await page.getByPlaceholder(/游戏名/).fill('游戏名：《明日2》\n类型：科幻 SLG\n目标用户：欧美移动端玩家\n玩法：联盟战争、排行榜、远征。')
  await expect(page.getByText('信息可用于生成 prompt')).toBeVisible()

  await page.getByRole('button', { name: '下一步 →' }).click()
  await expect(page.getByText('STEP 2')).toBeVisible()
  await page.getByRole('button', { name: '🤖 启动 AI 分析' }).click()
  await expect(page.getByText('项目提示词已生成')).toBeVisible({ timeout: 20000 })
  await expect(page.getByText('Return only id + translation JSONL')).toBeVisible()

  await page.getByRole('button', { name: '下一步 →' }).click()
  await expect(page.getByText('STEP 3')).toBeVisible()
  if (termWorkbook) {
    await page.locator('label.upload-box', { hasText: '上传 glossary.xlsx' }).locator('input[type="file"]').setInputFiles(termWorkbook)
    await expect(page.getByText(`已上传：${fileName(termWorkbook)}`)).toBeVisible({ timeout: 15000 })
  }

  await page.getByRole('button', { name: '下一步 →' }).click()
  await expect(page.getByText('STEP 4')).toBeVisible()
  await page.locator('label.upload-box', { hasText: '上传 language.xlsx' }).locator('input[type="file"]').setInputFiles(sourceWorkbook)
  await expect(page.getByText(`已上传：${fileName(sourceWorkbook)}`)).toBeVisible({ timeout: 15000 })

  await page.getByRole('button', { name: '下一步 →' }).click()
  await expect(page.getByText('STEP 5')).toBeVisible()
  await expect(page.getByRole('button', { name: '🔍 开始扫描' })).toBeEnabled()
  await page.getByRole('button', { name: '💡 查看补充策略' }).click()
  await expect(page.getByRole('heading', { name: '💡 高频词补充策略' })).toBeVisible()
  await page.getByRole('button', { name: '知道了' }).click()
  await expect(page.getByRole('heading', { name: '💡 高频词补充策略' })).toBeHidden()
  await page.getByRole('button', { name: '🔍 开始扫描' }).click()
  await expect(page.getByText('术语提取完成')).toBeVisible({ timeout: 60000 })

  await page.getByRole('button', { name: '下一步 →' }).click()
  await expect(page.getByText('STEP 6')).toBeVisible()
  await expect(page.getByRole('button', { name: '🇺🇸 英语 EN' })).toHaveClass(/selected/)

  await page.getByRole('button', { name: '下一步 →' }).click()
  await expect(page.getByText('STEP 7')).toBeVisible()
  await page.getByRole('button', { name: '⚡ 开始翻译' }).click()
  await expect(page.getByText('EN 闭环通过，产物已归档')).toBeVisible({ timeout: 120000 })
  await expect(page.getByText('status=passed')).toBeVisible()

  await page.getByRole('button', { name: '下一步 →' }).click()
  await expect(page.getByText('quality_harness 最终 gate')).toBeVisible()
  await expect(page.getByText('当前状态：passed')).toBeVisible()

  await page.getByRole('button', { name: '下一步 →' }).click()
  await expect(page.getByText('本次任务摘要')).toBeVisible()
  await expect(page.getByText('状态：passed')).toBeVisible()
  await expect(page.locator('a.artifact')).toHaveCount(7)

  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('link', { name: /Final workbook/ }).click()
  const download = await downloadPromise
  expect(download.suggestedFilename()).toMatch(/\.xlsx$/)
})

test('user can upload an existing translated workbook and run QA directly', async ({ page, request }) => {
  await request.patch(`${baseURL}/api/settings`, {
    data: {
      provider: 'mock',
      protocol: 'chat-completions',
      api_key: '',
      model: 'mock-localization',
      batch_size: 24,
    },
  })

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
  await page.goto(baseURL)
  await page.getByRole('button', { name: '+ 新建项目' }).click()
  await page.getByPlaceholder('例如：星际边境 / 机甲纪元').fill(projectName)
  await page.getByRole('button', { name: '创建' }).click()
  await expect(page.getByRole('heading', { name: `🎮 ${projectName}` })).toBeVisible({ timeout: 15000 })

  await page.getByRole('button', { name: '🚀 启动新翻译任务' }).click()
  await page.getByRole('button', { name: /自动校对/ }).click()
  await expect(page.getByText('STEP 8')).toBeVisible()
  await page.locator('label.upload-box', { hasText: '上传已有译文 workbook' }).locator('input[type="file"]').setInputFiles(translatedWorkbook)
  await expect(page.getByText('已有译文已登记')).toBeVisible({ timeout: 15000 })
  await page.getByRole('button', { name: '运行 QA' }).click()
  await expect(page.getByText('已有译文 QA 通过')).toBeVisible({ timeout: 60000 })
  await expect(page.getByText('当前状态：passed')).toBeVisible()
})
