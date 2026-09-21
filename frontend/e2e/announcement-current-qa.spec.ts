import { expect, test, type Page } from '@playwright/test'

const baseURL = process.env.E2E_BASE_URL ?? `http://127.0.0.1:${process.env.LWS_E2E_FRONTEND_PORT ?? '15173'}`

async function mountAnnouncementDelivery(page: Page, scenario: string) {
  await page.route('**/api/**', (route) => route.fulfill({ status: 503, json: { detail: 'Isolated announcement current QA test' } }))
  await page.goto(baseURL)
  await page.evaluate(async (testCase) => {
    const React = await import('/@id/react')
    const ReactDOMClient = await import('/@id/react-dom/client')
    const { AnnouncementDeliveryStep } = await import('/src/components/announcement/AnnouncementWorkflow.tsx')
    const createElement = React.createElement || React.default.createElement
    const createRoot = ReactDOMClient.createRoot || ReactDOMClient.default.createRoot
    const current: any = {
      id: 'qa-current', project_id: 'qa-project', kind: 'announcement_qa_summary',
      label: 'Current QA', path: 'current.xlsx', size: 1, created_at: '2026-09-20T01:00:00Z',
      metadata: { task_id: 'qa-task', hard_blockers: 0 },
    }
    const old = {
      ...current, id: 'qa-old', label: 'Historical QA', path: 'old.xlsx',
      metadata: { task_id: 'qa-task', hard_blockers: 5, superseded: true },
    }
    const task: any = {
      id: 'qa-task', project_id: 'qa-project', title: 'Current QA evidence', source_format: 'txt',
      status: 'applied', current_step: 9, selected_languages: ['en'],
      metadata: { qa_summary_artifact_id: current.id, hard_blockers: 0, qa_issues: [] },
      languages: [], artifacts: [old, current],
    }
    if (testCase === 'current-blocker') current.metadata.hard_blockers = 2
    if (testCase === 'task-blocker') task.metadata.hard_blockers = 2
    if (testCase === 'current-issues') task.metadata.qa_issues = [{ severity: 'hard' }, {}]
    if (testCase === 'legacy-child') task.languages = [{ language: 'en', metadata: { hard_blockers: 2 } }]
    if (testCase === 'old-child') task.languages = [{ language: 'en', metadata: { qa_summary_artifact_id: old.id, hard_blockers: 5 } }]
    if (testCase === 'no-pointer') delete task.metadata.qa_summary_artifact_id
    if (testCase === 'missing-current-count') delete current.metadata.hard_blockers
    if (testCase === 'invalid-current-count') current.metadata.hard_blockers = 'unknown'
    const host = document.createElement('div')
    document.body.replaceChildren(host)
    createRoot(host).render(createElement(AnnouncementDeliveryStep, {
      activeTask: task, busy: false, onDeliver: () => {}, onBack: () => {}, onStartNext: () => {},
      confirm: async () => true,
    }))
  }, scenario)
}

for (const [scenario, expected] of [
  ['repaired', 0], ['old-child', 0], ['current-blocker', 2], ['task-blocker', 2],
  ['current-issues', 2], ['legacy-child', 2], ['no-pointer', 5],
  ['missing-current-count', 5], ['invalid-current-count', 5],
] as const) {
  test(`announcement current QA selects conservative current evidence: ${scenario}`, async ({ page }) => {
    await mountAnnouncementDelivery(page, scenario)
    const count = page.locator('.workflow-note-grid > div').filter({ has: page.getByText('严重问题', { exact: true }) }).locator('span')
    await expect(count).toHaveText(String(expected))
    if (expected === 0) {
      await expect(page.getByRole('button', { name: '生成交付总包', exact: true })).toBeVisible()
      await expect(page.getByRole('button', { name: '生成带 QA 摘要的交付包', exact: true })).toHaveCount(0)
    } else {
      await expect(page.getByRole('button', { name: '生成带 QA 摘要的交付包', exact: true })).toBeVisible()
      await expect(page.getByRole('button', { name: '生成交付总包', exact: true })).toHaveCount(0)
    }
  })
}
