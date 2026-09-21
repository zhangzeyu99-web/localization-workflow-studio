import { expect, test } from '@playwright/test'
import path from 'node:path'

test('archive commit keeps the queue status truthful and rejects a stale cancel action', async ({ page }) => {
  let committed = false
  let cancelRequests = 0
  await page.route('**/api/projects', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/system/job-queues', (route) => route.fulfill({ json: { lanes: [{
    lane: 'language_table', label: '语言表', queued: [], running: {
      job_id: 'run:archive-finalizing', job_kind: 'translation', lane: 'language_table',
      project_id: 'archive-project', project_name: '归档状态验收', target_id: 'archive-finalizing',
      translation_task_id: 'translation-archive-finalizing', operator_name: '验收用户',
      status: 'running', started_at: new Date().toISOString(),
      archive_committed: committed, can_cancel: !committed,
    },
  }] } }))
  await page.route('**/api/system/job-queues/run%3Aarchive-finalizing/cancel', (route) => {
    cancelRequests += 1
    committed = true
    return route.fulfill({ status: 409, json: { detail: {
      code: 'archive_already_committed', message: '译文归档已提交，任务正在完成或已完成，不能再取消；已归档结果会保留。',
      job_id: 'run:archive-finalizing', run_id: 'archive-finalizing', batch_id: 'archive-batch',
    } } })
  })
  await page.goto('/')
  await page.getByTestId('active-jobs-badge').click()
  const cancel = page.getByTestId('queue-cancel-run:archive-finalizing')
  await expect(cancel).toBeEnabled()
  await cancel.click()
  await page.getByTestId('confirm-modal-confirm').click()
  await expect.poll(() => cancelRequests).toBe(1)
  await expect(page.getByRole('status').filter({ hasText: '译文归档已提交，任务正在完成或已完成，不能再取消' }).first()).toBeVisible()
  await expect(page.getByTestId('queue-job-run:archive-finalizing')).toContainText('归档已提交，正在完成')
  await expect(cancel).toBeDisabled()
  await expect(cancel).toHaveText('已提交')
  for (const width of [1280, 1024]) {
    await page.setViewportSize({ width, height: 900 })
    await expect(page.getByTestId('active-jobs-panel')).toBeVisible()
    const overflow = await page.getByTestId('active-jobs-panel').evaluate((element) => element.scrollWidth > element.clientWidth)
    expect(overflow).toBe(false)
    await page.screenshot({ path: path.resolve(`../output/process-review-2026-09-20/priority-fixes/P06-queue-${width}.png`) })
  }
})
