import { expect, test, type Page } from '@playwright/test'

const baseURL = process.env.E2E_BASE_URL ?? `http://127.0.0.1:${process.env.LWS_E2E_FRONTEND_PORT ?? '15173'}`

async function holdListSnapshot(page: Page) {
  let release!: () => void
  let started!: () => void
  let served!: () => void
  let count = 0
  const gate = new Promise<void>((resolve) => { release = resolve })
  const snapshotReady = new Promise<void>((resolve) => { started = resolve })
  const snapshotServed = new Promise<void>((resolve) => { served = resolve })
  await page.route('**/api/projects', async (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    count += 1
    if (count !== 1) return route.continue()
    const snapshot = await route.fetch()
    started()
    await gate
    await route.fulfill({ response: snapshot }).catch(() => undefined)
    served()
  })
  await page.evaluate(() => window.dispatchEvent(new Event('focus')))
  await snapshotReady
  return { release, snapshotServed, count: () => count }
}

test('slow list refresh coalesces timer and focus requests without reverting project selection', async ({ page, request }) => {
  const names = [`P08 First ${Date.now()}`, `P08 Second ${Date.now()}`]
  for (const name of names) {
    expect((await request.post(`${baseURL}/api/projects`, { data: { name } })).ok()).toBeTruthy()
  }
  await page.clock.install()
  await page.goto(baseURL)
  await page.getByRole('button', { name: names[0] }).click()
  await expect(page.getByRole('heading', { name: names[0] })).toBeVisible()
  let listRequests = 0
  let release!: () => void
  const gate = new Promise<void>((resolve) => { release = resolve })
  await page.route('**/api/projects', async (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    listRequests += 1
    const snapshot = await route.fetch()
    await gate
    await route.fulfill({ response: snapshot })
  })
  try {
    await page.evaluate(() => window.dispatchEvent(new Event('focus')))
    await expect.poll(() => listRequests).toBe(1)
    await page.getByRole('button', { name: names[1] }).click()
    await expect(page.getByRole('heading', { name: names[1] })).toBeVisible()
    await page.evaluate(() => {
      window.dispatchEvent(new Event('focus'))
      document.dispatchEvent(new Event('visibilitychange'))
    })
    await page.clock.fastForward(10001)
    await page.clock.fastForward(10001)
    // Let intercepted network events settle after more than two poll periods.
    await page.waitForTimeout(100)
    expect(listRequests).toBe(1)
    const response = page.waitForResponse((item) => new URL(item.url()).pathname === '/api/projects')
    release()
    await response
    await expect(page.locator('.project-item.active')).toContainText(names[1])
    await expect(page.getByRole('heading', { name: names[1] })).toBeVisible()
  } finally {
    release()
  }
})

test('creating a project bypasses an older in-flight snapshot and cancels its writeback', async ({ page, request }) => {
  const before = `P08 Before Create ${Date.now()}`
  const after = `P08 After Create ${Date.now()}`
  expect((await request.post(`${baseURL}/api/projects`, { data: { name: before } })).ok()).toBeTruthy()
  await page.goto(baseURL)
  await page.getByRole('button', { name: before }).click()
  await expect(page.getByRole('heading', { name: before })).toBeVisible()
  const held = await holdListSnapshot(page)
  try {
    await page.locator('.new-project-btn').click()
    await page.locator('input[name="name"]').fill(after)
    await page.getByRole('button', { name: '创建', exact: true }).click()
    await expect(page.getByRole('heading', { name: after })).toBeVisible()
    expect(held.count()).toBe(2)
    held.release()
    await held.snapshotServed
    await expect(page.locator('.project-item.active')).toContainText(after)
    await expect(page.getByRole('heading', { name: after })).toBeVisible()
  } finally {
    held.release()
  }
})

test('deleting a project refetches after the write instead of reviving it from a held snapshot', async ({ page, request }) => {
  const name = `P08 Delete ${Date.now()}`
  expect((await request.post(`${baseURL}/api/projects`, { data: { name } })).ok()).toBeTruthy()
  await page.goto(baseURL)
  const item = page.getByRole('button', { name })
  await item.click()
  await expect(page.getByRole('heading', { name })).toBeVisible()
  const held = await holdListSnapshot(page)
  try {
    await item.dispatchEvent('pointerdown', { button: 0 })
    await expect(page.getByRole('heading', { name: '删除项目', exact: true })).toBeVisible()
    await item.dispatchEvent('pointerup', { button: 0 })
    await page.getByRole('button', { name: '确认删除', exact: true }).click()
    await expect(item).toHaveCount(0)
    expect(held.count()).toBe(2)
    held.release()
    await held.snapshotServed
    await expect(item).toHaveCount(0)
  } finally {
    held.release()
  }
})

test('a failed shared list refresh can be retried on focus', async ({ page, request }) => {
  const before = `P08 Retry Base ${Date.now()}`
  const added = `P08 Retry Added ${Date.now()}`
  await request.post(`${baseURL}/api/projects`, { data: { name: before } })
  await page.goto(baseURL)
  await page.getByRole('button', { name: before }).click()
  await expect(page.getByRole('heading', { name: before })).toBeVisible()
  await page.route('**/api/projects', (route) => route.abort('failed'), { times: 1 })
  const failed = page.waitForEvent('requestfailed', (item) => new URL(item.url()).pathname === '/api/projects')
  await page.evaluate(() => window.dispatchEvent(new Event('focus')))
  await failed
  await request.post(`${baseURL}/api/projects`, { data: { name: added } })
  await page.evaluate(() => window.dispatchEvent(new Event('focus')))
  await expect(page.getByRole('button', { name: added })).toBeVisible()
  await expect(page.locator('.project-item.active')).toContainText(before)
})

test('a delayed delete readback preserves navigation into another project quick task', async ({ page, request }) => {
  const removedName = `P08 Delayed Delete ${Date.now()}`
  const keptName = `P08 Keep Quick ${Date.now()}`
  await request.post(`${baseURL}/api/projects`, { data: { name: keptName } })
  const removed = await request.post(`${baseURL}/api/projects`, { data: { name: removedName } }).then((response) => response.json())
  await page.goto(baseURL)
  const item = page.getByRole('button', { name: removedName })
  await item.click()
  await expect(page.getByRole('heading', { name: removedName })).toBeVisible()
  let deleted = false
  let ready!: () => void
  let release!: () => void
  const readbackStarted = new Promise<void>((resolve) => { ready = resolve })
  const gate = new Promise<void>((resolve) => { release = resolve })
  await page.route(`**/api/projects/${removed.id}`, async (route) => {
    if (route.request().method() !== 'DELETE') return route.continue()
    const response = await route.fetch()
    expect(response.ok()).toBeTruthy()
    deleted = true
    await route.fulfill({ response })
  })
  await page.route('**/api/projects', async (route) => {
    if (route.request().method() !== 'GET' || !deleted) return route.continue()
    const response = await route.fetch()
    ready()
    await gate
    await route.fulfill({ response }).catch(() => undefined)
  })
  try {
    await item.dispatchEvent('pointerdown', { button: 0 })
    await expect(page.getByRole('heading', { name: '删除项目', exact: true })).toBeVisible()
    await item.dispatchEvent('pointerup', { button: 0 })
    await page.getByRole('button', { name: '确认删除', exact: true }).click()
    await readbackStarted
    // Exercise navigation handlers while delete readback is pending. The busy
    // dialog still overlays these controls, so dispatch their DOM click events.
    await page.getByRole('button', { name: keptName }).dispatchEvent('click')
    await expect(page.locator('.project-item.active')).toContainText(keptName)
    await expect(page.getByTestId('quick-task-entry')).toBeEnabled()
    await page.getByTestId('quick-task-entry').dispatchEvent('click')
    await expect(page.locator('.quick-steps')).toBeVisible()
    release()
    await expect(page.getByRole('heading', { name: '删除项目', exact: true })).toHaveCount(0)
    await expect(page.locator('.project-item.active')).toContainText(keptName)
    await expect(page.locator('.quick-steps')).toBeVisible()
  } finally {
    release()
  }
})

test('saving project metadata invalidates a list snapshot captured before the save', async ({ page, request }) => {
  test.setTimeout(45000)
  const oldName = `P08 Metadata Old ${Date.now()}`
  const newName = `P08 Metadata Saved ${Date.now()}`
  await request.post(`${baseURL}/api/projects`, { data: { name: oldName, type: 'old-type', description: 'old-description' } })
  await page.goto(baseURL)
  await page.getByRole('button', { name: oldName }).click()
  await expect(page.getByRole('heading', { name: oldName })).toBeVisible()
  const held = await holdListSnapshot(page)
  try {
    await page.getByText('资料与重新分析', { exact: true }).click()
    await page.getByLabel('项目名', { exact: true }).fill(newName)
    await page.getByLabel('题材/分类', { exact: true }).fill('saved-type')
    await page.locator('.material-input-grid textarea').fill('saved-description')
    await page.getByRole('button', { name: '保存资料说明', exact: true }).click()
    await expect(page.getByRole('heading', { name: newName })).toBeVisible()
    held.release()
    await held.snapshotServed
    await page.evaluate(() => new Promise<void>((resolve) => {
      requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
    }))
    expect(await page.locator('main .proj-head h2').textContent()).toBe(newName)
    await expect(page.getByLabel('题材/分类', { exact: true })).toHaveValue('saved-type')
    await expect(page.locator('.material-input-grid textarea')).toHaveValue('saved-description')
    expect(held.count()).toBe(2)
  } finally {
    held.release()
  }
})
