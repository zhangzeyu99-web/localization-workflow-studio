import { expect, test } from '@playwright/test'

const baseURL = process.env.E2E_BASE_URL ?? `http://127.0.0.1:${process.env.LWS_E2E_FRONTEND_PORT ?? '15173'}`
const storageKey = 'lws.session-navigation'

const selectWizardStep = async (page: any, step: number) => {
  await page.getByTestId('step-menu-toggle').click()
  await page.getByTestId(`step-${step}`).click()
}

test('page refresh restores the validated project workflow location and refetches project data', async ({ page, request }) => {
  const projectName = `E2E Refresh Restore ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'refresh-restore', description: 'Refresh restore coverage.' },
  }).then((response) => response.json())

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.locator('.view-tabs').getByRole('button', { name: '校对', exact: true }).click()
  await page.locator('.sidebar').getByRole('button', { name: /新翻译任务/ }).click()
  await selectWizardStep(page, 4)
  await expect(page.getByTestId('step-menu-toggle')).toContainText('判定输入')

  const stored = await page.evaluate((key) => JSON.parse(localStorage.getItem(key) || '{}'), storageKey)
  expect(Object.keys(stored).sort()).toEqual(['projectId', 'step', 'tab', 'view'])
  expect(stored).toEqual({ projectId: project.id, view: 'wizard', tab: 'qa', step: 4 })

  const projectReload = page.waitForResponse((response) => (
    response.request().method() === 'GET'
    && response.url().endsWith(`/api/projects/${project.id}`)
  ))
  await page.reload()
  expect((await projectReload).ok()).toBeTruthy()

  await expect(page.getByRole('heading', { name: '新翻译任务', exact: true })).toBeVisible()
  await expect(page.getByTestId('step-menu-toggle')).toContainText('判定输入')
  await expect(page.locator('.project-item.active')).toContainText(projectName)
})

test('page refresh restores quick task and announcement views for the current project', async ({ page, request }) => {
  const projectName = `E2E View Restore ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'view-restore', description: 'Quick and announcement view restore coverage.' },
  }).then((response) => response.json())

  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()

  await page.getByTestId('quick-task-entry').click()
  await expect(page.locator('.quick-steps')).toBeVisible()
  await expect.poll(() => page.evaluate((key) => JSON.parse(localStorage.getItem(key) || '{}').view, storageKey)).toBe('quick')
  const quickReload = page.waitForResponse((response) => (
    response.request().method() === 'GET'
    && response.url().endsWith(`/api/projects/${project.id}`)
  ))
  await page.reload()
  expect((await quickReload).ok()).toBeTruthy()
  await expect(page.locator('.quick-steps')).toBeVisible()
  await expect(page.locator('.project-item.active')).toContainText(projectName)

  await page.getByRole('button', { name: projectName }).click()
  await expect(page.getByRole('heading', { name: projectName })).toBeVisible()
  await page.locator('main').getByRole('button', { name: '公告翻译', exact: true }).click()
  await expect(page.getByRole('heading', { name: '公告翻译', exact: true })).toBeVisible()
  await expect.poll(() => page.evaluate((key) => JSON.parse(localStorage.getItem(key) || '{}').view, storageKey)).toBe('announcement')
  const announcementReload = page.waitForResponse((response) => (
    response.request().method() === 'GET'
    && response.url().endsWith(`/api/projects/${project.id}`)
  ))
  await page.reload()
  expect((await announcementReload).ok()).toBeTruthy()
  await expect(page.getByRole('heading', { name: '公告翻译', exact: true })).toBeVisible()
  await expect(page.locator('.project-item.active')).toContainText(projectName)
})

test('navigation storage clamps the step, rejects unsupported enums, and ignores corrupt or deleted projects', async ({ page, request }) => {
  const projectName = `E2E Navigation Validation ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'refresh-validation', description: 'Navigation validation coverage.' },
  }).then((response) => response.json())

  await page.goto(baseURL)
  const parsed = await page.evaluate(async ({ key, projectId }) => {
    const { parseSessionNavigation } = await import('/src/sessionNavigation.ts')
    return {
      clamped: parseSessionNavigation(JSON.stringify({ projectId, view: 'wizard', tab: 'delivery', step: 99 })),
      invalidEnums: parseSessionNavigation(JSON.stringify({ projectId, view: 'unsupported', tab: 'internal', step: 4 })),
      corrupt: parseSessionNavigation('{not-json'),
      key,
    }
  }, { key: storageKey, projectId: project.id })
  expect(parsed.clamped).toEqual({ projectId: project.id, view: 'wizard', tab: 'delivery', step: 9 })
  expect(parsed.invalidEnums).toBeNull()
  expect(parsed.corrupt).toBeNull()

  await page.evaluate(({ key }) => localStorage.setItem(key, '{not-json'), { key: storageKey })
  await page.reload()
  await expect(page.locator('main')).toBeVisible()

  await page.evaluate(({ key }) => localStorage.setItem(key, JSON.stringify({
    projectId: 'project-that-no-longer-exists',
    view: 'wizard',
    tab: 'delivery',
    step: 9,
  })), { key: storageKey })
  await page.reload()
  await expect(page.getByRole('heading', { name: '新翻译任务', exact: true })).toHaveCount(0)
  await expect.poll(() => page.evaluate((key) => {
    const fallback = JSON.parse(localStorage.getItem(key) || '{}')
    return {
      hasValidProject: Boolean(fallback.projectId && fallback.projectId !== 'project-that-no-longer-exists'),
      view: fallback.view,
      tab: fallback.tab,
      step: fallback.step,
    }
  }, storageKey)).toEqual({ hasValidProject: true, view: 'overview', tab: 'meta', step: 1 })
})
