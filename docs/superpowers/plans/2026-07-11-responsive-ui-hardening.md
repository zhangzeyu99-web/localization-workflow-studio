# Responsive UI Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate responsive clipping, wrapping, hidden-entry, table-compression, and contrast defects without changing localization workflow behavior or the established workbench visual style.

**Architecture:** Keep responsive decisions in the existing CSS system and keep React changes limited to exposing the existing quick-task transition from `ProjectOverview`. Use container queries for delivery cards because their usable width depends on the persistent desktop sidebar, and use media queries for viewport-wide navigation/table behavior. Add Playwright integration assertions before each implementation slice so layout regressions fail deterministically.

**Tech Stack:** React 19, TypeScript 5.7, Vite 7, CSS media/container queries, Playwright 1.60.

## Global Constraints

- Preserve the current white, light-gray, and teal workbench theme.
- Do not change backend APIs, task state, delivery rules, or archive behavior.
- Keep desktop wide-screen density unchanged at `1920 x 1080`.
- Validate `1280 x 720`, `1024 x 768`, and `390 x 844`.
- Keep command buttons and status badges on one line.
- Keep all three workflow entries available on mobile: formal translation, announcement translation, and quick task.
- Use horizontal scrolling for wide operational tables instead of collapsing cell text vertically.
- Keep visible interaction targets at least 24px; primary controls remain at least 36px high.
- Do not add dependencies, routes, themes, animations, or decorative components.

---

### Task 1: Expose Quick Task From Project Overview

**Files:**
- Modify: `frontend/e2e/studio-ui-flow.spec.ts`
- Modify: `frontend/src/components/project/ProjectOverview.tsx`
- Modify: `frontend/src/main.tsx`

**Interfaces:**
- Consumes: existing `AppView = 'overview' | 'wizard' | 'announcement' | 'quick'` and `setView('quick')` behavior in `main.tsx`.
- Produces: `ProjectOverviewProps.onStartQuickTask: () => void` and a visible `data-testid="overview-quick-task"` button.

- [ ] **Step 1: Write the failing mobile-entry test**

Append this test near the existing responsive workflow test in `frontend/e2e/studio-ui-flow.spec.ts`:

```ts
test('mobile project overview exposes all three workflow entries', async ({ page, request }) => {
  const projectName = `E2E Mobile Entries ${Date.now()}`
  await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'responsive', description: 'Mobile workflow entry coverage.' },
  })

  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()

  const main = page.locator('main')
  await expect(main.getByRole('button', { name: '新翻译任务', exact: true })).toBeVisible()
  await expect(main.getByRole('button', { name: '公告翻译', exact: true })).toBeVisible()
  await expect(main.getByTestId('overview-quick-task')).toBeVisible()
  await main.getByTestId('overview-quick-task').click()
  await expect(page.getByRole('heading', { name: '快速任务', exact: true })).toBeVisible()
})
```

- [ ] **Step 2: Run the focused test and verify failure**

Run:

```powershell
npm run e2e -- --grep "mobile project overview exposes all three workflow entries" --workers=1
```

Expected: FAIL because `overview-quick-task` does not exist.

- [ ] **Step 3: Add the overview callback and button**

In `ProjectOverviewProps`, add:

```ts
onStartQuickTask: () => void
```

Destructure it in `ProjectOverviewImpl`, import `Zap` from `lucide-react`, and add it after the announcement button:

```tsx
<button
  className="btn btn-ghost"
  data-testid="overview-quick-task"
  onClick={onStartQuickTask}
>
  <Zap size={16} aria-hidden="true" />快速任务
</button>
```

Pass the existing transition from `main.tsx`:

```tsx
onStartQuickTask={() => {
  setStatusForProject(current.id, '快速任务已就绪。')
  setView('quick')
}}
```

- [ ] **Step 4: Run the focused test and production build**

Run:

```powershell
npm run e2e -- --grep "mobile project overview exposes all three workflow entries" --workers=1
npm run build
```

Expected: focused test PASS; TypeScript and Vite build exit 0.

- [ ] **Step 5: Commit the entry fix**

```powershell
git add frontend/e2e/studio-ui-flow.spec.ts frontend/src/components/project/ProjectOverview.tsx frontend/src/main.tsx
git commit -m "fix(frontend): expose quick task on mobile overview"
```

---

### Task 2: Stabilize Sidebar, Buttons, Badges, And Secondary Text

**Files:**
- Modify: `frontend/e2e/studio-ui-flow.spec.ts`
- Modify: `frontend/src/styles/workbench.css`

**Interfaces:**
- Consumes: existing `.quick-entry`, `.btn`, `.tag`, `.pmeta`, and workflow summary classes.
- Produces: non-shrinking sidebar actions, single-line command/status controls, and secondary text with at least 4.5:1 contrast on white.

- [ ] **Step 1: Write failing layout assertions**

Append:

```ts
test('compact desktop keeps sidebar entries and command labels intact', async ({ page, request }) => {
  const projectName = `E2E Compact Labels ${Date.now()}`
  await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'responsive', description: 'Compact label coverage.' },
  })

  await page.setViewportSize({ width: 1280, height: 720 })
  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()

  const entryMetrics = await page.locator('.quick-entry').evaluateAll((entries) => entries.map((entry) => ({
    clientHeight: entry.clientHeight,
    scrollHeight: entry.scrollHeight,
  })))
  expect(entryMetrics).toHaveLength(2)
  expect(entryMetrics.every((entry) => entry.scrollHeight <= entry.clientHeight + 1)).toBeTruthy()

  const secondaryColor = await page.locator('.quick-entry .pmeta').first().evaluate((element) => getComputedStyle(element).color)
  expect(secondaryColor).toBe('rgb(104, 116, 127)')

  await page.getByTestId('quick-task-entry').click()
  const back = page.getByRole('button', { name: '返回项目概览', exact: true })
  const backMetrics = await back.evaluate((element) => ({
    clientHeight: element.clientHeight,
    scrollHeight: element.scrollHeight,
    whiteSpace: getComputedStyle(element).whiteSpace,
  }))
  expect(backMetrics.scrollHeight).toBeLessThanOrEqual(backMetrics.clientHeight + 1)
  expect(backMetrics.whiteSpace).toBe('nowrap')
})
```

- [ ] **Step 2: Run the focused test and verify failure**

Run:

```powershell
npm run e2e -- --grep "compact desktop keeps sidebar entries and command labels intact" --workers=1
```

Expected: FAIL because quick entries are vertically clipped, secondary text is `rgb(123, 135, 145)`, and buttons use normal whitespace.

- [ ] **Step 3: Add the minimal CSS hardening**

Update `frontend/src/styles/workbench.css`:

```css
.quick-entry {
  flex: 0 0 auto;
  min-height: 56px;
  border: 1px solid transparent;
}

.btn,
.tag {
  white-space: nowrap;
}

.tag {
  flex: 0 0 auto;
  line-height: 1.3;
}

.pmeta,
.phase-item small,
.workflow-step-menu > summary span,
.substep-item.skipped:not(.active),
.analysis-summary span,
.translation-input-summary span,
.evidence-metrics dt,
.proofread-timeline li {
  color: #68747f;
}
```

Keep border-only uses of `#9da8b1` and scrollbar colors unchanged.

- [ ] **Step 4: Run the focused test and production build**

Run:

```powershell
npm run e2e -- --grep "compact desktop keeps sidebar entries and command labels intact" --workers=1
npm run build
```

Expected: focused test PASS; build exit 0.

- [ ] **Step 5: Commit the sizing and contrast fix**

```powershell
git add frontend/e2e/studio-ui-flow.spec.ts frontend/src/styles/workbench.css
git commit -m "fix(frontend): stabilize compact workbench controls"
```

---

### Task 3: Reflow Delivery Cards By Container Width

**Files:**
- Modify: `frontend/e2e/studio-ui-flow.spec.ts`
- Modify: `frontend/src/styles/workbench.css`

**Interfaces:**
- Consumes: existing `GET /api/projects/:id/deliverables` response and `.delivery-list > .delivery-line` structure.
- Produces: a three-column wide layout, two-column layout at delivery-container width `<= 820px`, and existing one-column mobile layout.

- [ ] **Step 1: Write the failing delivery overflow test**

Append:

```ts
test('delivery cards reflow without horizontal overflow at 1024px', async ({ page, request }) => {
  const projectName = `E2E Delivery Reflow ${Date.now()}`
  await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'responsive', description: 'Delivery reflow coverage.' },
  })
  await page.route('**/api/projects/*/deliverables', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        deliverables: [{
          run_id: 'run-responsive-delivery',
          task_code: 'T',
          task_id: 'task-responsive-delivery',
          task_label: 'T-responsive',
          task_type: '翻译任务',
          language: 'EN',
          created_at: '2026-07-11T08:54:54Z',
          updated_at: '2026-07-11T08:54:54Z',
          status: 'passed',
          processed_rows: 5,
          source_rows: 5,
          input_label: '已译语言表｜EN｜responsive-delivery｜2026-07-11',
          qa_status: 'passed',
          qa_hard_errors: 0,
          qa_soft_warnings: 0,
          files: { outputs: [] },
        }],
      }),
    })
  })

  await page.setViewportSize({ width: 1024, height: 768 })
  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.getByRole('button', { name: '交付', exact: true }).click()
  await expect(page.locator('.delivery-line')).toBeVisible()

  const metrics = await page.evaluate(() => {
    const main = document.querySelector('.main')!
    const content = document.querySelector('.main-content')!
    const card = document.querySelector('.delivery-line')!
    const tag = document.querySelector('.delivery-line .tag')!
    return {
      mainOverflow: main.scrollWidth - main.clientWidth,
      contentOverflow: content.scrollWidth - content.clientWidth,
      cardColumns: getComputedStyle(card).gridTemplateColumns.split(' ').length,
      tagHeight: tag.getBoundingClientRect().height,
    }
  })
  expect(metrics.mainOverflow).toBeLessThanOrEqual(1)
  expect(metrics.contentOverflow).toBeLessThanOrEqual(1)
  expect(metrics.cardColumns).toBe(2)
  expect(metrics.tagHeight).toBeLessThanOrEqual(30)
})
```

- [ ] **Step 2: Run the focused test and verify failure**

Run:

```powershell
npm run e2e -- --grep "delivery cards reflow without horizontal overflow at 1024px" --workers=1
```

Expected: FAIL with positive main/content overflow and a three-column card.

- [ ] **Step 3: Add delivery container-query rules**

In `frontend/src/styles/workbench.css`, add:

```css
.delivery-list {
  container-type: inline-size;
}

@container (max-width: 820px) {
  .delivery-line {
    grid-template-columns: minmax(0, 1fr) minmax(220px, 1fr);
  }

  .delivery-line-info,
  .delivery-actions {
    grid-column: 1 / -1;
  }

  .delivery-actions {
    justify-content: flex-start;
  }
}
```

Place the container query before the existing `@media (max-width: 980px)` rules so the mobile single-column rule remains authoritative.

- [ ] **Step 4: Run the focused test and production build**

Run:

```powershell
npm run e2e -- --grep "delivery cards reflow without horizontal overflow at 1024px" --workers=1
npm run build
```

Expected: focused test PASS; build exit 0.

- [ ] **Step 5: Commit the delivery reflow**

```powershell
git add frontend/e2e/studio-ui-flow.spec.ts frontend/src/styles/workbench.css
git commit -m "fix(frontend): reflow delivery cards at medium widths"
```

---

### Task 4: Make Mobile Tabs And History Tables Fully Readable

**Files:**
- Modify: `frontend/e2e/studio-ui-flow.spec.ts`
- Modify: `frontend/src/components/translationWizard/TaskHistoryTable.tsx`
- Modify: `frontend/src/styles/workbench.css`

**Interfaces:**
- Consumes: existing six `.view-tab` buttons and `TaskHistoryTable` markup.
- Produces: `table-scroll history-table-scroll` wrapper, `3 x 2` mobile project tabs, and stable mobile table minimum widths.

- [ ] **Step 1: Write the failing mobile navigation/table test**

Append:

```ts
test('mobile project tabs and history table stay readable', async ({ page, request }) => {
  const projectName = `E2E Mobile Tables ${Date.now()}`
  const project = await request.post(`${baseURL}/api/projects`, {
    data: { name: projectName, type: 'responsive', description: 'Mobile tab and table coverage.' },
  }).then((response) => response.json())
  await request.post(`${baseURL}/api/runs`, {
    data: { project_id: project.id, kind: 'translation', language: 'en' },
  })

  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(baseURL)
  await page.getByRole('button', { name: projectName }).click()
  await page.getByRole('button', { name: '翻译', exact: true }).click()

  const metrics = await page.evaluate(() => {
    const tabs = document.querySelector('.view-tabs')!
    const wrapper = document.querySelector('.history-table-scroll')!
    const table = document.querySelector('.history-table')!
    const tag = document.querySelector('.history-table .tag')!
    return {
      tabColumns: getComputedStyle(tabs).gridTemplateColumns.split(' ').length,
      tabOverflow: tabs.scrollWidth - tabs.clientWidth,
      wrapperOverflow: wrapper.scrollWidth - wrapper.clientWidth,
      tableWidth: table.getBoundingClientRect().width,
      tagHeight: tag.getBoundingClientRect().height,
    }
  })

  expect(metrics.tabColumns).toBe(3)
  expect(metrics.tabOverflow).toBeLessThanOrEqual(1)
  expect(metrics.wrapperOverflow).toBeGreaterThan(0)
  expect(metrics.tableWidth).toBeGreaterThanOrEqual(679)
  expect(metrics.tagHeight).toBeLessThanOrEqual(30)
})
```

- [ ] **Step 2: Run the focused test and verify failure**

Run:

```powershell
npm run e2e -- --grep "mobile project tabs and history table stay readable" --workers=1
```

Expected: FAIL because `.history-table-scroll` does not exist and mobile tabs remain a horizontally clipped flex row.

- [ ] **Step 3: Add the history scroll boundary**

Insert the scroll wrapper immediately before `<table className="history-table">` in `TaskHistoryTable.tsx`:

```tsx
<div className="table-scroll history-table-scroll">
  <table className="history-table">
```

Keep the current `thead` and `tbody` byte-for-byte. Replace the existing closing `</table>` with:

```tsx
  </table>
</div>
```

- [ ] **Step 4: Add mobile tab and table CSS**

Inside the existing `@media (max-width: 720px)` block in `frontend/src/styles/workbench.css`, add:

```css
.view-tabs {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0;
  overflow: visible;
}

.view-tab {
  min-height: 42px;
  justify-content: center;
  white-space: nowrap;
}

.history-table,
.glossary-wide-table {
  min-width: 680px;
}

.translation-wide-table {
  min-width: 880px;
}
```

Add the scroll treatment outside the media query:

```css
.history-table-scroll {
  border-radius: 7px;
  scrollbar-color: #b9c1c8 transparent;
}
```

- [ ] **Step 5: Run the focused test and production build**

Run:

```powershell
npm run e2e -- --grep "mobile project tabs and history table stay readable" --workers=1
npm run build
```

Expected: focused test PASS; build exit 0.

- [ ] **Step 6: Commit mobile navigation and table fixes**

```powershell
git add frontend/e2e/studio-ui-flow.spec.ts frontend/src/components/translationWizard/TaskHistoryTable.tsx frontend/src/styles/workbench.css
git commit -m "fix(frontend): keep mobile navigation and tables readable"
```

---

### Task 5: Full Regression And Visual Evidence

**Files:**
- Modify: `docs/superpowers/reports/ui-defect-audit-2026-07-11/` with accepted post-fix screenshots only.
- Modify: `docs/superpowers/reports/ux-full-audit-2026-07-11.md` if its current verification section does not include this responsive pass.

**Interfaces:**
- Consumes: all implementation changes from Tasks 1-4.
- Produces: passing build/tests, accepted screenshots, and an evidence-backed audit conclusion.

- [ ] **Step 1: Run all focused responsive tests together**

```powershell
npm run e2e -- --grep "mobile project overview exposes all three workflow entries|compact desktop keeps sidebar entries and command labels intact|delivery cards reflow without horizontal overflow at 1024px|mobile project tabs and history table stay readable|workflow remains usable without page overflow" --workers=1
```

Expected: all selected tests PASS.

- [ ] **Step 2: Run the complete frontend validation**

```powershell
npm run build
npm run e2e -- --workers=1
```

Expected: build exits 0 and the full E2E suite passes.

- [ ] **Step 3: Verify services**

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:5173
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

Expected: frontend HTTP 200 and backend `{ "ok": true }`.

- [ ] **Step 4: Capture and inspect post-fix screenshots**

Use the in-app browser at these exact viewports and states:

```text
1920 x 1080  project overview / delivery tab
1280 x 720   project overview with complete sidebar quick entries
1024 x 768   delivery tab, quick task, formal translation, announcement
390 x 844    overview, translation history, glossary, archive, QA, delivery, formal translation, announcement, quick task
```

Reject blank, black, loading, cropped, or wrong-state captures. Save accepted files with `after-` prefixes in `docs/superpowers/reports/ui-defect-audit-2026-07-11/`.

- [ ] **Step 5: Run programmatic visual checks in the in-app browser**

For each relevant state assert:

```js
const main = document.querySelector('.main')
const content = document.querySelector('.main-content')

if (!main || !content) {
  throw new Error('workbench layout not rendered')
}

return {
  mainOverflow: main.scrollWidth - main.clientWidth,
  contentOverflow: content.scrollWidth - content.clientWidth,
  tallTags: [...document.querySelectorAll('.tag')]
    .filter((element) => element.getBoundingClientRect().height > 30).length,
  clippedCommands: [...document.querySelectorAll('.btn')]
    .filter((element) => element.scrollHeight > element.clientHeight + 1).length,
  undersizedTargets: [...document.querySelectorAll('button,a[href],input,select,textarea,summary')]
    .filter((element) => {
      const rect = element.getBoundingClientRect()
      return rect.width > 0 && rect.height > 0 && (rect.width < 24 || rect.height < 24)
    }).length,
}
```

Expected: main/content overflow `<= 1`; `tallTags`, `clippedCommands`, and `undersizedTargets` all equal 0 in tested visible states.

- [ ] **Step 6: Update the audit report and run the UTF-8 gate**

Add the fixed issue list, screenshot names, viewport matrix, build result, and E2E result to the existing report. Then run:

```powershell
python D:\codex\codex\tools\output_quality_gate.py docs\superpowers\reports\ux-full-audit-2026-07-11.md --expect-cjk
```

Expected: every output-quality check PASS.

- [ ] **Step 7: Commit final evidence**

```powershell
git add docs/superpowers/reports/ui-defect-audit-2026-07-11 docs/superpowers/reports/ux-full-audit-2026-07-11.md
git commit -m "docs: record responsive UI verification"
```

- [ ] **Step 8: Verify branch state before push**

```powershell
git diff --check
git status -sb
git log -6 --oneline
```

Expected: no unstaged source changes; only explicitly excluded local tooling directories may remain untracked.
