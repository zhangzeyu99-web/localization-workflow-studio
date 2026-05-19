import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

const baseURL = process.env.E2E_BASE_URL ?? 'http://127.0.0.1:15173'

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
  await page.getByRole('button', { name: '校对' }).click()
  await expect(page.getByText('自动校对与优化')).toBeVisible()

  await page.locator('label.upload-box', { hasText: '上传已有译文 workbook' }).locator('input[type="file"]').setInputFiles(badWorkbook)
  await page.getByTestId('run-qa').click()
  await expect(page.getByTestId('failed-row-editor')).toBeVisible({ timeout: 60000 })
  await expect(page.getByText('Forbidden Brand Reward').first()).toBeVisible()
  await page.getByTestId('manual-fix-input-2').fill('Reward')
  await page.getByTestId('manual-fix-rerun').click()
  await expect(page.getByText('手工修复已重新 QA：passed')).toBeVisible({ timeout: 60000 })
  await expect(page.getByTestId('failed-row-editor')).toBeHidden()
})
