import { expect, test, type Page } from '@playwright/test'

const baseURL = process.env.E2E_BASE_URL ?? `http://127.0.0.1:${process.env.LWS_E2E_FRONTEND_PORT ?? '15173'}`

async function mountMultilingualQaAction(page: Page) {
  // Keep the hook's HTTP boundary isolated from all real project data.
  await page.route('**/api/**', (route) => route.fulfill({
    status: 503,
    json: { detail: 'Unexpected API request in isolated multilingual action test' },
  }))
  await page.goto(baseURL)
  await page.evaluate(async () => {
    const React = await import('/@id/react')
    const ReactDOMClient = await import('/@id/react-dom/client')
    const { useTranslationActions } = await import('/src/hooks/useTranslationActions.ts')
    const { captureTranslationActionScope } = await import('/src/domain/translationActionScope.ts')
    const createElement = React.createElement || React.default.createElement
    const useState = React.useState || React.default.useState
    const useRef = React.useRef || React.default.useRef
    const createRoot = ReactDOMClient.createRoot || ReactDOMClient.default.createRoot
    const host = document.createElement('div')
    document.body.replaceChildren(host)
    function QaActionHarness() {
      const [latestRun, setLatestRun] = useState<any>(null)
      const [busy, setBusy] = useState(false)
      const [status, setStatus] = useState('准备就绪')
      const current = { id: 'current-run-project', name: '多语言当前结果测试', artifacts: [], runs: [] }
      const currentIdRef = useRef(current.id)
      const translationTaskIdRef = useRef('current-run-task')
      const scopeRef = useRef({ projectId: current.id, taskId: translationTaskIdRef.current })
      const environmentRef = useRef({})
      const isCurrentTranslationTask = (projectId: string, taskId: string) => currentIdRef.current === projectId && translationTaskIdRef.current === taskId
      const actions = useTranslationActions({
        current,
        currentIdRef,
        translationTaskId: 'current-run-task',
        translationTaskIdRef,
        isWizard: true,
        captureTranslationAction: (projectId: string, taskId: string) => captureTranslationActionScope(
          scopeRef,
          environmentRef,
          () => isCurrentTranslationTask(projectId, taskId),
        ),
        sourceArtifact: { id: 'current-run-source' },
        qaArtifact: null,
        termArtifact: null,
        latestRun,
        tab: 'qa',
        selectedLanguage: 'en',
        selectedLanguages: ['en', 'ja'],
        isCurrentTranslationTask,
        setLatestRun,
        setBusyForProject: (_projectId: string, value: boolean) => setBusy(value),
        setStatusForProject: (_projectId: string, message: string) => setStatus(message),
        refreshCurrent: async () => current,
      } as any)
      return createElement('section', null,
        createElement('button', { disabled: busy, onClick: () => actions.startMultilingualQAQueue() }, '启动多语言 QA'),
        createElement('output', { 'data-testid': 'current-run-result' }, latestRun ? `${latestRun.id} · ${latestRun.kind} · ${latestRun.status}` : '尚无结果'),
        createElement('div', { role: 'status', 'data-testid': 'queue-action-status' }, status),
      )
    }
    createRoot(host).render(createElement(QaActionHarness))
  })
  await expect(page.getByRole('button', { name: '启动多语言 QA', exact: true })).toBeVisible()
}

for (const legacyResponse of [false, true]) {
  test(legacyResponse
    ? 'multilingual QA action falls back to a QA id only when current run ids are absent'
    : 'multilingual QA action shows the current passed translation instead of its older failed QA', async ({ page }) => {
    await mountMultilingualQaAction(page)
    const requestedRuns: string[] = []
    await page.route('**/current-run-project/multilingual/qa/start', (route) => route.fulfill({
      json: {
        project_id: 'current-run-project',
        input_artifact_id: 'current-run-source',
        created_run_ids: [],
        queue_started: false,
        languages: [
          {
            language: 'en',
            visible_language: 'EN',
            run_id: legacyResponse ? null : 'translation-current',
            translation_run_id: 'translation-current',
            qa_run_id: 'qa-history',
            status: legacyResponse ? 'failed' : 'passed',
          },
          { language: 'ja', visible_language: 'JP', run_id: null, qa_run_id: null, status: 'pending' },
        ],
      },
    }))
    await page.route('**/api/runs/*', async (route) => {
      const id = route.request().url().split('/').at(-1) || ''
      requestedRuns.push(id)
      await route.fulfill({ json: {
        id,
        project_id: 'current-run-project',
        kind: id === 'translation-current' ? 'translation' : 'qa',
        status: id === 'translation-current' ? 'passed' : 'failed',
        language: 'en',
        metadata: { translation_task_id: 'current-run-task' },
      } })
    })

    await page.getByRole('button', { name: '启动多语言 QA', exact: true }).click()
    await expect(page.getByTestId('queue-action-status')).toContainText('多语言 QA 队列已启动')
    await expect(page.getByTestId('current-run-result')).toHaveText(legacyResponse
      ? 'qa-history · qa · failed'
      : 'translation-current · translation · passed')
    expect(requestedRuns).toEqual([legacyResponse ? 'qa-history' : 'translation-current'])
  })
}
