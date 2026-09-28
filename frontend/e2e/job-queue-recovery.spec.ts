import { expect, test, type Page } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import type { JobQueueEntry, JobQueues } from '../src/types'

const evidenceRoot = process.env.LWS_QUEUE_EVIDENCE_ROOT
const job = (id: string, status = 'running'): JobQueueEntry => ({
  job_id: id, project_id: `project-${id}`, project_name: id === 'a' ? '合成项目 · 语言表' : '合成项目 · 公告',
  lane: id === 'b' ? 'quick_announcement' : 'language_table', translation_task_id: `task-${id}`,
  target_id: `run-${id}`, job_kind: 'translation', status, operator_name: '流程验收',
  queued_at: '2026-09-28T00:00:00Z', started_at: '2026-09-28T00:00:00Z', can_cancel: true,
})
const queues = (cancelRequested = false): JobQueues => ({ lanes: [
  { lane: 'language_table', label: '正式语言表', running: { ...job('a'), cancel_requested: cancelRequested, can_cancel: !cancelRequested }, queued: [] },
  { lane: 'quick_announcement', label: '快速任务与公告', running: job('b'), queued: [] },
] })

async function openPanel(page: Page) {
  await page.goto('/')
  await expect(page.getByRole('button', { name: '设置', exact: true })).toBeVisible()
  await page.getByTestId('active-jobs-badge').click()
  await expect(page.getByTestId('active-jobs-panel')).toBeVisible()
}

test('evidence: a failed refresh must distinguish retained jobs from current state', async ({ page }) => {
  let failed = false
  let failedRequests = 0
  await page.route('**/api/system/job-queues', route => {
    if (failed) failedRequests += 1
    return route.fulfill(failed ? { status: 503, json: { detail: '隔离验收：暂时无法读取任务' } } : { json: queues() })
  })
  await page.clock.setSystemTime(new Date('2026-09-28T00:05:00Z'))
  await page.setViewportSize({ width: 1280, height: 800 })
  await openPanel(page)
  const liveColor = await page.getByTestId('queue-job-a').locator('.active-jobs-item-state').evaluate(node => getComputedStyle(node).color)
  failed = true
  await expect.poll(() => failedRequests).toBeGreaterThan(0)
  // Let the real component consume the returned error before either capture.
  await page.waitForTimeout(100)
  {
    if (evidenceRoot) fs.mkdirSync(evidenceRoot, { recursive: true })
    const observations = []
    for (const width of [1280, 390, 320]) {
      await page.setViewportSize({ width, height: width === 1280 ? 800 : 844 })
      await page.waitForTimeout(200)
      if (await page.getByTestId('queue-freshness').count()) await expect(page.getByTestId('queue-freshness').locator('p')).toBeVisible()
      if (evidenceRoot) {
        await page.screenshot({ path: path.join(evidenceRoot, `stale-${width}.png`), fullPage: true })
        await page.screenshot({ path: path.join(evidenceRoot, `stale-${width}-viewport.png`) })
      }
      const rect = await page.getByTestId('active-jobs-panel').boundingBox()
      expect(rect!.x).toBeGreaterThanOrEqual(0)
      expect(rect!.x + rect!.width).toBeLessThanOrEqual(width)
      const observation = await page.getByTestId('active-jobs-panel').evaluate(element => ({
        viewport: window.innerWidth,
        horizontalOverflow: element.scrollWidth > element.clientWidth,
        pageOverflow: document.documentElement.scrollWidth > window.innerWidth,
        badge: (() => {
          const badge = document.querySelector('[data-testid="active-jobs-badge"]')!
          return { text: badge.textContent, fontSize: getComputedStyle(badge).fontSize, clipped: badge.scrollWidth > badge.clientWidth }
        })(),
        texts: Array.from(element.querySelectorAll('.active-jobs-panel-head strong, .active-jobs-panel-head button, .queue-freshness strong, .queue-freshness p, .queue-freshness button, .job-queue-lane-head strong, .job-queue-lane-head span, .active-jobs-item-project, .active-jobs-item-kind, .active-jobs-item-time, .active-jobs-item-state, .active-jobs-cancel')).map(node => ({
          text: node.textContent, fontSize: getComputedStyle(node).fontSize,
          height: node.getBoundingClientRect().height,
        })),
      }))
      expect(observation.horizontalOverflow).toBe(false)
      expect(observation.pageOverflow).toBe(false)
      expect(observation.badge.clipped).toBe(false)
      expect(parseFloat(observation.badge.fontSize)).toBeGreaterThanOrEqual(16)
      expect(observation.texts.every(item => parseFloat(item.fontSize) >= 16)).toBe(true)
      observations.push(observation)
    }
    // A shorter viewport may need panel scrolling; the last operation must remain reachable.
    await page.setViewportSize({ width: 320, height: 568 })
    await page.getByTestId('active-jobs-panel').evaluate(node => { node.scrollTop = 0 })
    if (evidenceRoot) {
      await page.screenshot({ path: path.join(evidenceRoot, 'stale-320-short.png'), fullPage: true })
      await page.screenshot({ path: path.join(evidenceRoot, 'stale-320-short-viewport.png') })
    }
    await page.getByTestId('queue-cancel-b').scrollIntoViewIfNeeded()
    await expect(page.getByTestId('queue-cancel-b')).toBeInViewport({ ratio: 1 })
    if (evidenceRoot) await page.screenshot({ path: path.join(evidenceRoot, 'stale-320-short-last-action.png') })
    await page.getByTestId('queue-cancel-b').focus()
    await page.keyboard.press('Enter')
    await expect(page.getByRole('button', { name: '返回', exact: true })).toBeVisible()
    if (evidenceRoot) await page.screenshot({ path: path.join(evidenceRoot, 'stale-320-short-confirm.png') })
    await page.getByRole('button', { name: '返回', exact: true }).click()
    if (evidenceRoot) fs.writeFileSync(path.join(evidenceRoot, 'readability.json'), JSON.stringify(observations, null, 2))
  }
  await expect(page.getByTestId('queue-job-a').locator('.active-jobs-item-state')).toHaveText('上次读取：运行中')
  await expect(page.getByTestId('queue-job-b').locator('.active-jobs-item-state')).toHaveText('上次读取：运行中')
  const staleColor = await page.getByTestId('queue-job-a').locator('.active-jobs-item-state').evaluate(node => getComputedStyle(node).color)
  expect(staleColor).not.toBe(liveColor)
  const badgeFonts = await page.getByTestId('active-jobs-badge').evaluate(node => [node, ...node.querySelectorAll('span')].filter(item => item.textContent?.trim()).map(item => parseFloat(getComputedStyle(item).fontSize)))
  expect(badgeFonts.every(size => size >= 16)).toBe(true)
})

test('first load failure is unknown, not an empty queue; explicit retry recovers', async ({ page }) => {
  let failed = true
  await page.route('**/api/system/job-queues', route => route.fulfill(failed
    ? { status: 503, json: { detail: '隔离验收：暂时无法读取任务' } }
    : { json: { lanes: [] } }))
  await openPanel(page)
  await expect(page.getByTestId('queue-freshness')).toContainText('暂时无法读取任务')
  await expect(page.getByTestId('active-jobs-panel')).not.toContainText('当前通道没有任务')
  await page.getByTestId('active-jobs-badge').focus()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('button', { name: '关闭', exact: true })).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('button', { name: '重新连接', exact: true })).toBeFocused()
  failed = false
  await page.keyboard.press('Enter')
  await expect(page.getByTestId('queue-freshness')).toHaveCount(0)
  await expect(page.getByTestId('active-jobs-panel')).toContainText('当前通道没有任务')
})

test('stale snapshot stays visible with a warning and recovers without reloading the page', async ({ page }) => {
  let failed = false
  await page.route('**/api/system/job-queues', route => route.fulfill(failed
    ? { status: 503, json: { detail: '隔离验收：暂时无法读取任务' } }
    : { json: queues() }))
  await openPanel(page)
  failed = true
  await expect(page.getByTestId('queue-freshness')).toContainText('以下为上次结果')
  await expect(page.getByTestId('queue-job-a')).toBeVisible()
  await expect(page.getByTestId('active-jobs-badge')).toContainText('状态待更新')
  await expect(page.getByTestId('queue-job-a').locator('.active-jobs-item-state')).toHaveText('上次读取：运行中')
  failed = false
  await page.getByRole('button', { name: '重新连接', exact: true }).click()
  await expect(page.getByTestId('queue-freshness')).toHaveCount(0)
  await expect(page.getByTestId('active-jobs-badge')).not.toContainText('状态待更新')
  await expect(page.getByTestId('queue-job-a').locator('.active-jobs-item-state')).toHaveText('运行中')
})

test('accepted cancellation survives failed readback and reopening until terminal readback', async ({ page }) => {
  let failed = false
  let accepted = false
  let finished = false
  let writes = 0
  await page.route('**/api/system/job-queues', route => {
    const snapshot = queues(accepted)
    if (finished) snapshot.lanes[0].running = null
    return route.fulfill(failed ? { status: 503, json: { detail: '隔离验收：读取失败' } } : { json: snapshot })
  })
  await page.route('**/api/system/job-queues/a/cancel', route => {
    writes += 1
    accepted = true
    failed = true
    return route.fulfill({ json: { cancel_requested: true, status: 'running' } })
  })
  await page.clock.setSystemTime(new Date('2026-09-28T00:05:00Z'))
  await page.setViewportSize({ width: 390, height: 844 })
  await openPanel(page)
  await page.getByTestId('queue-cancel-a').click()
  await page.getByRole('button', { name: '确认取消', exact: true }).click()
  await expect(page.getByTestId('queue-freshness')).toBeVisible()
  await expect(page.getByTestId('queue-cancel-a')).toHaveText('等待停止')
  await page.getByRole('button', { name: '关闭', exact: true }).click()
  await page.getByTestId('active-jobs-badge').click()
  if (evidenceRoot) {
    fs.mkdirSync(evidenceRoot, { recursive: true })
    for (const width of [390, 320, 1280]) {
      await page.setViewportSize({ width, height: width === 1280 ? 800 : 844 })
      await page.screenshot({ path: path.join(evidenceRoot, `cancel-accepted-offline-${width}.png`), fullPage: true })
      await page.screenshot({ path: path.join(evidenceRoot, `cancel-accepted-offline-${width}-viewport.png`) })
    }
  }
  await expect(page.getByTestId('queue-job-a').locator('.active-jobs-item-state')).toHaveText('取消请求已接受；停止状态待确认')
  await expect(page.getByTestId('queue-cancel-a')).toBeDisabled()
  await expect(page.getByTestId('queue-job-b').locator('.active-jobs-item-state')).toHaveText('上次读取：运行中')
  expect(writes).toBe(1)
  failed = false
  await page.getByRole('button', { name: '重新连接', exact: true }).click()
  await expect(page.getByTestId('queue-freshness')).toHaveCount(0)
  await expect(page.getByTestId('queue-job-a')).toContainText('正在停止')
  if (evidenceRoot) await page.screenshot({ path: path.join(evidenceRoot, 'cancel-recovered-1280.png'), fullPage: true })
  finished = true
  await page.evaluate(() => window.dispatchEvent(new Event('focus')))
  await expect(page.getByTestId('queue-job-a')).toHaveCount(0)
  await expect(page.getByTestId('active-jobs-badge')).toContainText('1')
})

test('offline snapshots preserve queued position, accepted cancellation and committed archive facts', async ({ page }) => {
  let failed = false
  const snapshot = queues(true)
  Object.assign(snapshot.lanes[1].running, { archive_committed: true, can_cancel: false })
  snapshot.lanes[0].queued.push({ ...job('c', 'queued'), position: 2, ahead: 1 })
  await page.route('**/api/system/job-queues', route => route.fulfill(failed ? { status: 503, json: {} } : { json: snapshot }))
  await openPanel(page)
  failed = true
  await page.evaluate(() => window.dispatchEvent(new Event('focus')))
  await expect(page.getByTestId('queue-freshness')).toBeVisible()
  await expect(page.getByTestId('queue-job-a').locator('.active-jobs-item-state')).toHaveText('取消请求已接受；停止状态待确认')
  await expect(page.getByTestId('queue-job-b').locator('.active-jobs-item-state')).toHaveText('归档已提交；完成状态待确认')
  await expect(page.getByTestId('queue-job-c').locator('.active-jobs-item-state')).toHaveText('上次读取：排队第 2 位、前方 1 个')
  await expect(page.getByTestId('queue-cancel-a')).toBeDisabled()
  await expect(page.getByTestId('queue-cancel-b')).toBeDisabled()
  await expect(page.getByTestId('queue-cancel-c')).toBeEnabled()
})

test('in-flight cancellation survives closing and reopening without a duplicate write', async ({ page }) => {
  let writes = 0
  let failed = false
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  await page.route('**/api/system/job-queues', route => route.fulfill(failed ? { status: 503, json: {} } : { json: queues() }))
  await page.route('**/api/system/job-queues/a/cancel', async route => {
    writes += 1
    await gate
    failed = true
    await route.fulfill({ json: { cancel_requested: true } })
  })
  await page.setViewportSize({ width: 390, height: 844 })
  await openPanel(page)
  try {
    await page.getByTestId('queue-cancel-a').click()
    await page.getByRole('button', { name: '确认取消', exact: true }).click()
    await expect.poll(() => writes).toBe(1)
    await page.getByRole('button', { name: '关闭', exact: true }).click()
    await page.getByTestId('active-jobs-badge').click()
    if (evidenceRoot) {
      fs.mkdirSync(evidenceRoot, { recursive: true })
      await page.screenshot({ path: path.join(evidenceRoot, 'cancel-pending-reopened-390-viewport.png') })
    }
    if (await page.getByTestId('queue-cancel-a').isEnabled()) {
      await page.getByTestId('queue-cancel-a').click()
      await page.getByRole('button', { name: '确认取消', exact: true }).click()
      await expect.poll(() => writes).toBe(2)
    }
    expect(writes).toBe(1)
    await expect(page.getByTestId('queue-cancel-a')).toBeDisabled()
    await expect(page.getByTestId('queue-cancel-a')).toHaveText('取消中...')
    await expect(page.getByTestId('queue-cancel-b')).toBeEnabled()
    release()
    await expect(page.getByTestId('queue-job-a').locator('.active-jobs-item-state')).toHaveText('取消请求已接受；停止状态待确认')
    await expect(page.getByTestId('queue-cancel-a')).toHaveText('等待停止')
  } finally { release() }
})

test('cancellation errors stay with their job and simultaneous requests do not unlock one another', async ({ page }) => {
  await page.route('**/api/system/job-queues', route => route.fulfill({ json: queues() }))
  let releaseA!: () => void
  let releaseB!: () => void
  const gateA = new Promise<void>(resolve => { releaseA = resolve })
  const gateB = new Promise<void>(resolve => { releaseB = resolve })
  let countA = 0
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/api/system/job-queues/a/cancel', async route => {
    countA += 1
    if (countA === 1) await gateA
    await route.fulfill(countA === 1 ? { status: 503, json: { detail: '取消失败，请重试' } } : { json: { canceled: true } })
  })
  await page.route('**/api/system/job-queues/b/cancel', async route => {
    await gateB
    await route.fulfill({ status: 503, json: { detail: '权限不足' } })
  })
  await openPanel(page)
  try {
    await page.getByTestId('queue-cancel-a').click()
    await page.getByRole('button', { name: '确认取消', exact: true }).click()
    await page.getByTestId('queue-cancel-b').click()
    await page.getByRole('button', { name: '确认取消', exact: true }).click()
    await expect(page.getByTestId('queue-cancel-a')).toBeDisabled()
    await expect(page.getByTestId('queue-cancel-b')).toBeDisabled()
    releaseA()
    await expect(page.getByTestId('queue-job-a')).toContainText('取消失败，请重试')
    await expect(page.getByTestId('queue-cancel-a')).toBeEnabled()
    await expect(page.getByTestId('queue-cancel-b')).toBeDisabled()
    await page.getByTestId('queue-cancel-a').click()
    await page.getByRole('button', { name: '确认取消', exact: true }).click()
    await expect.poll(() => countA).toBe(2)
    await expect(page.getByTestId('queue-job-a')).not.toContainText('取消失败，请重试')
    releaseB()
    await expect(page.getByTestId('queue-job-b')).toContainText('当前账号权限不足')
    expect(errors).toEqual([])
  } finally {
    releaseA()
    releaseB()
  }
})

test('accepted cancellation remains waiting until the worker confirms its terminal state', async ({ page }) => {
  let cancelRequested = false
  await page.route('**/api/system/job-queues', route => route.fulfill({ json: queues(cancelRequested) }))
  await page.route('**/api/system/job-queues/a/cancel', route => {
    cancelRequested = true
    return route.fulfill({ json: { cancel_requested: true, status: 'running' } })
  })
  await openPanel(page)
  await page.getByTestId('queue-cancel-a').click()
  await page.getByRole('button', { name: '确认取消', exact: true }).click()
  await expect(page.getByTestId('queue-job-a')).toContainText('正在停止')
  await expect(page.getByTestId('queue-cancel-a')).toBeDisabled()
  await expect(page.getByTestId('queue-cancel-a')).toHaveText('等待停止')
  await expect(page.getByTestId('queue-cancel-b')).toBeEnabled()
  if (evidenceRoot) await page.getByTestId('active-jobs-panel').screenshot({ path: path.join(evidenceRoot, 'cancel-requested.png') })
})

test('a pre-cancellation GET cannot overwrite the forced post-cancellation readback', async ({ page }) => {
  let reads = 0
  let stopped = false
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  await page.route('**/api/system/job-queues', async route => {
    reads += 1
    const snapshot = queues(stopped)
    if (reads === 2) await gate
    await route.fulfill({ json: snapshot }).catch(() => undefined)
  })
  await page.route('**/api/system/job-queues/a/cancel', route => {
    stopped = true
    return route.fulfill({ json: { cancel_requested: true } })
  })
  await openPanel(page)
  await page.evaluate(() => window.dispatchEvent(new Event('focus')))
  await expect.poll(() => reads).toBe(2)
  try {
    await page.getByTestId('queue-cancel-a').click()
    await page.getByRole('button', { name: '确认取消', exact: true }).click()
    await expect.poll(() => reads).toBeGreaterThanOrEqual(3)
    await expect(page.getByTestId('queue-cancel-a')).toHaveText('等待停止')
    release()
    await page.getByRole('button', { name: '关闭', exact: true }).click()
    await page.getByTestId('active-jobs-badge').click()
    await expect(page.getByTestId('queue-cancel-a')).toHaveText('等待停止')
  } finally { release() }
})

test('declining cancellation keeps the task actionable without issuing a write', async ({ page }) => {
  let writes = 0
  await page.route('**/api/system/job-queues', route => route.fulfill({ json: queues() }))
  await page.route('**/api/system/job-queues/*/cancel', route => {
    writes += 1
    return route.fulfill({ json: {} })
  })
  await openPanel(page)
  await page.getByTestId('queue-cancel-a').click()
  const confirmation = page.getByRole('alertdialog', { name: '取消后台任务' })
  for (const viewport of [{ width: 1280, height: 800 }, { width: 390, height: 844 }, { width: 320, height: 568 }]) {
    await page.setViewportSize(viewport)
    await expect(confirmation).toBeInViewport({ ratio: 1 })
    await expect(page.getByTestId('confirm-modal-cancel')).toBeInViewport({ ratio: 1 })
    await expect(page.getByTestId('confirm-modal-confirm')).toBeInViewport({ ratio: 1 })
    const readability = await confirmation.evaluate(element => ({
      overflow: element.scrollWidth > element.clientWidth,
      texts: Array.from(element.querySelectorAll('h3, p, button')).map(node => ({
        text: node.textContent, fontSize: parseFloat(getComputedStyle(node).fontSize),
        height: node.getBoundingClientRect().height, button: node.tagName === 'BUTTON',
      })),
    }))
    expect(readability.overflow).toBe(false)
    expect(readability.texts.every(item => item.fontSize >= 16)).toBe(true)
    expect(readability.texts.filter(item => item.button).every(item => item.height >= 44)).toBe(true)
    if (evidenceRoot) {
      fs.mkdirSync(evidenceRoot, { recursive: true })
      await page.screenshot({ path: path.join(evidenceRoot, `cancel-confirmation-${viewport.width}-viewport.png`) })
      fs.writeFileSync(path.join(evidenceRoot, `cancel-confirmation-${viewport.width}-readability.json`), JSON.stringify(readability, null, 2))
    }
  }
  await page.getByRole('button', { name: '返回', exact: true }).click()
  await expect(page.getByTestId('queue-cancel-a')).toBeEnabled()
  await expect(page.getByTestId('queue-cancel-a')).toHaveText('取消')
  expect(writes).toBe(0)
})
