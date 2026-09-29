import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'

const baseURL = process.env.E2E_BASE_URL ?? `http://127.0.0.1:${process.env.LWS_E2E_FRONTEND_PORT ?? '15173'}`
test.use({ acceptDownloads: true })

async function createProject(request: APIRequestContext) {
  const response = await request.post(`${baseURL}/api/projects`, {
    data: { name: `E2E 交付版本 ${Date.now()}`, type: 'delivery-review', description: 'Synthetic delivery history acceptance.' },
  })
  expect(response.ok()).toBeTruthy()
  return response.json()
}

async function openDelivery(page: Page, projectName: string) {
  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.getByRole('button', { name: '交付', exact: true }).click()
}

async function jsonOk(response: Awaited<ReturnType<APIRequestContext['post']>>) {
  expect(response.ok(), await response.text()).toBeTruthy()
  return response.json()
}

async function prepareQa(request: APIRequestContext, projectId: string, taskId: string, target: string, quick = false, sourceRunId?: string) {
  await jsonOk(await request.patch(`${baseURL}/api/settings`, { data: { provider: 'test-fake', model: 'test-fake-localization', api_key: '', batch_size: 1 } }))
  const buffer = execFileSync(process.env.LWS_E2E_PYTHON || 'python', ['-X', 'utf8', '-c', `
import io, sys
from openpyxl import Workbook
book = Workbook()
sheet = book.active
sheet.title = 'Language'
sheet.append(['ID', 'CN', 'EN'])
sheet.append(['row-1', '开始游戏', sys.argv[1]])
output = io.BytesIO()
book.save(output)
book.close()
sys.stdout.buffer.write(output.getvalue())
`, target])
  const artifact = await jsonOk(await request.post(`${baseURL}/api/projects/${projectId}/files?kind=final_workbook`, { multipart: {
    file: { name: `delivery-${target.replace(/\W/g, '')}.xlsx`, mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer },
  } }))
  const run = await jsonOk(await request.post(`${baseURL}/api/runs`, { data: {
    project_id: projectId, kind: 'qa', language: 'en', input_artifact_id: artifact.id,
    translation_task_id: taskId || null, task_origin: quick ? 'quick_task' : 'translation_run', source_run_id: sourceRunId || null,
  } }))
  await jsonOk(await request.post(`${baseURL}/api/runs/${run.id}/qa`))
  return jsonOk(await request.get(`${baseURL}/api/runs/${run.id}`))
}

async function generate(request: APIRequestContext, projectId: string, runId: string) {
  return jsonOk(await request.post(`${baseURL}/api/projects/${projectId}/delivery-package?run_id=${encodeURIComponent(runId)}`))
}

test('real formal delivery regeneration preserves its old download and history cannot restore a task', async ({ page, request }) => {
  const project = await createProject(request)
  const run = await prepareQa(request, project.id, `translation-task-${project.id}`, 'Start Game')
  expect(run.status).toBe('passed')
  const first = await generate(request, project.id, run.id)
  const oldFile = first.files.find((file: any) => file.kind === 'final')
  const oldBytes = await (await request.get(`${baseURL}${oldFile.download_url}`)).body()
  await openDelivery(page, project.name)
  await expect(page.getByTestId('delivery-current')).toContainText('QA 已通过')
  await page.getByRole('button', { name: '重新生成交付', exact: true }).click()
  const history = page.getByTestId('delivery-history')
  await expect(history).toBeVisible()
  await expect(history).not.toHaveAttribute('open', '')
  const writes: string[] = []
  page.on('request', (request) => { if (['POST', 'PATCH', 'DELETE'].includes(request.method())) writes.push(request.url()) })
  await history.locator('summary').click()
  await expect(history.getByRole('link', { name: '下载最终译文' })).toHaveAttribute('href', oldFile.download_url)
  const downloadEvent = page.waitForEvent('download')
  await history.getByRole('link', { name: '下载最终译文' }).click()
  expect((await downloadEvent).suggestedFilename()).toBe(oldFile.filename)
  await expect(history).toBeVisible()
  await expect(history.getByRole('button')).toHaveCount(0)
  expect(await (await request.get(`${baseURL}${oldFile.download_url}`)).body()).toEqual(oldBytes)
  expect(writes).toEqual([])
  await page.locator('main').getByRole('button', { name: '新翻译任务', exact: true }).click()
  await expect(page.getByRole('heading', { name: '新翻译任务', exact: true })).toBeVisible()
  await expect(page.getByTestId('confirm-modal')).toHaveCount(0)
  await page.getByTestId('step-menu-toggle').click()
  await page.getByTestId('step-4').click()
  await expect(page.locator('.step-panel.active label.asset-select select')).toHaveValue('')
  await expect(page.locator('.workflow-file-link')).toHaveCount(0)
})
