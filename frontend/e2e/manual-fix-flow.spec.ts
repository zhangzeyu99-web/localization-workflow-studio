import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

const baseURL = process.env.E2E_BASE_URL ?? `http://127.0.0.1:${process.env.LWS_E2E_FRONTEND_PORT ?? '15173'}`
const inlineStatus = (page: any, text: string) => page.locator('.inline-status', { hasText: text })

test('user can repair failed QA rows and rerun QA from the web UI', async ({ page, request }) => {
  const badWorkbook = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'lws-failed-qa-')), 'bad-translated.xlsx')
  execFileSync(process.env.LWS_E2E_PYTHON || 'python', ['-c', `
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
  await expect(page.getByTestId('delivery-problem-warning')).toContainText('任务已结束；保留历史下载，不从交付页恢复执行。')
  await expect(page.getByTestId('delivery-problem-warning')).toContainText('请到“校对”页选择成品，启动新的 QA 后修复；已交付记录保持不变。')
  const deliveries = await request.get(`${baseURL}/api/projects/${project.id}/deliverables`).then((response) => response.json())
  const delivery = deliveries.deliverables.find((item: { files: { qa_summary?: { path?: string } } }) => Boolean(item.files.qa_summary?.path))
  expect(delivery).toBeTruthy()
  const summaryPath = path.resolve(delivery!.files.qa_summary!.path!)
  expect(summaryPath.startsWith(path.resolve(process.env.LWS_E2E_DATA_ROOT || os.tmpdir()) + path.sep)).toBe(true)
  fs.rmSync(summaryPath)
  const incomplete = await request.get(`${baseURL}/api/projects/${project.id}/delivery-history`).then((response) => response.json())
  expect(incomplete.current_tasks[0].current_version_id).toBeNull()
  expect(incomplete.versions[0]).toMatchObject({ available: false, is_current: false })
  expect(incomplete.versions[0].files.find((file: any) => file.kind === 'qa_summary')).toMatchObject({ available: false, download_url: '' })
  await page.reload()
  await page.getByRole('button', { name: projectName }).click()
  await page.getByRole('button', { name: '交付', exact: true }).click()
  await expect(page.getByTestId('delivery-missing-qa-summary')).toContainText('当前交付不完整')
  await expect(page.getByTestId('delivery-missing-qa-summary')).toContainText('缺少 QA 摘要')
  await expect(page.getByTestId('delivery-missing-qa-summary')).toContainText('补齐问题清单后再下载')
  await expect(page.getByTestId('delivery-current').getByRole('link')).toHaveCount(0)
  await expect(page.locator('.delivery-card .warn-line')).toHaveCount(0)
  const originalViewport = page.viewportSize()
  const output = path.resolve('..', 'output', 'process-review-2026-09-20', 'bc-acceptance')
  fs.mkdirSync(output, { recursive: true })
  for (const width of [1280, 1024]) {
    await page.setViewportSize({ width, height: width === 1280 ? 900 : 768 })
    await page.getByTestId(`delivery-current-${delivery.run_id}`).scrollIntoViewIfNeeded()
    await expect(page.getByTestId('delivery-missing-qa-summary')).toBeInViewport()
    await expect(page.getByRole('button', { name: '重新生成并补齐摘要' })).toBeInViewport()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: path.join(output, `C-missing-summary-${width}.png`), fullPage: true })
  }
  if (originalViewport) await page.setViewportSize(originalViewport)
  await page.getByRole('button', { name: '重新生成并补齐摘要' }).click()
  await expect(page.getByRole('link', { name: /下载 QA 摘要/ })).toBeVisible({ timeout: 30000 })
  await expect(page.getByTestId('delivery-missing-qa-summary')).toHaveCount(0)
  const repairedHistory = await request.get(`${baseURL}/api/projects/${project.id}/delivery-history`).then((response) => response.json())
  expect(repairedHistory.versions.find((version: any) => version.version_id === incomplete.versions[0].version_id)).toMatchObject({ available: false, is_current: false })
  await page.locator('.view-tab', { hasText: '译文归档' }).click()
  await expect(page.getByTestId('archive-source-delivered_with_issues').first()).toContainText('待复核', { timeout: 30000 })
  await page.locator('.view-tab', { hasText: '校对' }).click()
  const deliveredRun = await request.get(`${baseURL}/api/runs/${delivery.run_id}`).then((response) => response.json())
  expect(deliveredRun.metadata.translation_task_state).toBe('delivered')
  const oldOutput = deliveredRun.artifacts.find((artifact: any) => artifact.kind === 'qa_final_workbook')
  expect(oldOutput).toBeTruthy()
  const inputs = page.locator('details.qa-input-details')
  if (await inputs.getAttribute('open') === null) await inputs.locator('summary').click()
  await page.getByLabel('选择译文').selectOption(oldOutput.id)
  const newQaCreated = page.waitForResponse((response) => response.request().method() === 'POST'
    && new URL(response.url()).pathname === '/api/runs' && response.request().postDataJSON().kind === 'qa')
  await page.getByTestId('run-qa').click()
  const newQaResponse = await newQaCreated
  expect(newQaResponse.ok()).toBeTruthy()
  const newQaRequest = newQaResponse.request().postDataJSON()
  expect(newQaRequest).toMatchObject({ input_artifact_id: oldOutput.id, source_run_id: null })
  expect(newQaRequest.translation_task_id).toMatch(/^translation-task-/)
  expect(newQaRequest.translation_task_id).not.toBe(deliveredRun.metadata.translation_task_id)
  const newQaRun = await newQaResponse.json()
  await expect.poll(async () => (await request.get(`${baseURL}/api/runs/${newQaRun.id}`).then((response) => response.json())).status).toBe('failed')
  await expect(page.getByTestId('failed-row-editor')).toBeVisible()
  await page.getByTestId('failed-row-editor').locator('summary').click()
  await expect(page.getByText('Forbidden Brand Reward').first()).toBeVisible()
  await page.getByTestId('manual-fix-input-2').fill('Reward')
  await page.getByTestId('manual-fix-rerun').click()
  await expect(page.locator('.qa-outcome-panel.ready')).toContainText('QA 已通过', { timeout: 60000 })
  await expect(page.getByTestId('failed-row-editor')).toBeHidden()
  await page.locator('.view-tab', { hasText: '译文归档' }).click()
  await expect(page.getByTestId('archive-source-qa_passed').first()).toContainText('QA 已通过', { timeout: 30000 })
  const unchangedDeliveredRun = await request.get(`${baseURL}/api/runs/${delivery.run_id}`).then((response) => response.json())
  expect(unchangedDeliveredRun.metadata.translation_task_state).toBe('delivered')
  expect(unchangedDeliveredRun.status).toBe('failed')
})
