import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

const baseURL = process.env.E2E_BASE_URL ?? `http://127.0.0.1:${process.env.LWS_E2E_FRONTEND_PORT ?? '15173'}`
const inlineStatus = (page: any, text: string) => page.locator('.inline-status', { hasText: text })

test('user can repair failed QA rows and rerun QA from the web UI', async ({ page, request }) => {
  const badWorkbook = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'lws-failed-qa-')), 'bad-translated.xlsx')
  execFileSync('python', ['-c', `
from openpyxl import Workbook
import sys
wb = Workbook()
ws = wb.active
ws.title = "Language"
ws.append(["ID", "cn", "en"])
ws.append([1, "Reward source", "Forbidden Brand Reward"])
ws.append([2, "Start source", "Start Game"])
wb.save(sys.argv[1])
wb.close()
`, badWorkbook])

  const projectName = `E2E Manual Fix ${Date.now()}`
  const createResponse = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'QA', description: 'Manual fix e2e' },
  })
  const project = await createResponse.json()
  await request.patch(`${baseURL}/api/projects/${project.id}/harness`, {
    data: { forbidden_translations: ['Forbidden Brand'] },
  })

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.getByRole('button', { name: '校对', exact: true }).click()
  await expect(page.locator('.workflow-step-head h3')).toHaveText('QA 校对')

  await page.locator('label.upload-box', { hasText: '上传译文' }).locator('input[type="file"]').setInputFiles(badWorkbook)
  await page.getByTestId('run-qa').click()
  await expect(page.getByTestId('failed-row-editor')).toBeVisible({ timeout: 60000 })
  await expect(page.getByTestId('qa-download-changes')).toBeVisible()
  await expect(page.getByTestId('qa-go-delivery')).toBeVisible()
  await page.getByTestId('qa-go-delivery').click()
  await expect(page.getByTestId('delivery-problem-warning')).toBeVisible({ timeout: 30000 })
  await expect(page.locator('.delivery-card .warn-line')).toHaveCount(0)
  await expect(page.getByRole('link', { name: /下载修改记录/ })).toBeVisible({ timeout: 30000 })
  await expect(page.getByRole('link', { name: /下载 QA 摘要/ })).toBeVisible()
  await expect(page.getByTestId('delivery-problem-warning')).toContainText('建议修复后再作为标准交付')
  const deliveries = await request.get(`${baseURL}/api/projects/${project.id}/deliverables`).then((response) => response.json())
  const delivery = deliveries.deliverables.find((item: { files: { qa_summary?: { path?: string } } }) => Boolean(item.files.qa_summary?.path))
  expect(delivery).toBeTruthy()
  fs.rmSync(delivery!.files.qa_summary!.path!)
  await page.reload()
  await page.getByRole('button', { name: projectName }).click()
  await page.getByRole('button', { name: '交付', exact: true }).click()
  await expect(page.getByTestId('delivery-missing-qa-summary')).toContainText('当前文件不完整')
  await expect(page.getByTestId('delivery-missing-qa-summary')).toContainText('交付不完整')
  await expect(page.getByTestId('delivery-missing-qa-summary')).toContainText('补齐问题清单后再下载')
  await expect(page.locator('.delivery-card .warn-line')).toHaveCount(0)
  await page.getByRole('button', { name: '重新生成并补齐摘要' }).click()
  await expect(page.getByRole('link', { name: /下载 QA 摘要/ })).toBeVisible({ timeout: 30000 })
  await page.locator('.view-tab', { hasText: '译文归档' }).click()
  await expect(page.getByTestId('archive-source-delivered_with_issues').first()).toContainText('待复核', { timeout: 30000 })
  await page.locator('.view-tab', { hasText: '校对' }).click()
  await page.getByTestId('failed-row-editor').locator('summary').click()
  await expect(page.getByText('Forbidden Brand Reward').first()).toBeVisible()
  await page.getByTestId('manual-fix-input-2').fill('Reward')
  await page.getByTestId('manual-fix-rerun').click()
  await expect(page.locator('.qa-outcome-panel.ready')).toContainText('QA 已通过', { timeout: 60000 })
  await expect(page.getByTestId('failed-row-editor')).toBeHidden()
  await page.locator('.view-tab', { hasText: '译文归档' }).click()
  await expect(page.getByTestId('archive-source-qa_passed').first()).toContainText('QA 已通过', { timeout: 30000 })
})
