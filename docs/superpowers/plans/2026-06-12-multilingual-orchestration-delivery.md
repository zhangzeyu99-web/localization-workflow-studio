# Multilingual Orchestration and Merged Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users select multiple target languages once, then have the workbench run translation, QA, archive, and final merged delivery automatically without manually switching languages back and forth.

**Architecture:** Keep the existing single-language `Run` as the reliable resumable unit. Add a thin project-level orchestration layer that creates/reuses one child run per selected language and a merged-delivery layer that combines passed child outputs back into one complete workbook. Existing single-language delivery remains available.

**Tech Stack:** FastAPI, SQLite-backed project DB, Python `openpyxl`, existing translation batch runner, React/TypeScript, Playwright E2E.

---

## Scope and Boundaries

### In scope
- Normal language-pack translation workflow Steps 6/7/8/9.
- Multi-language selected queue: EN/KR/JP/FR/DE/RU/IT/ES/PT/TR/ID/TH, following existing supported language list.
- One child run per language, each child keeps current resumable batch behavior.
- Final merged workbook generated at Step 9 from all passed child language outputs.
- UI progress that clearly shows per-language state and next action.

### Out of scope
- Announcement workflow rewrite. Announcement already has its own multi-language DOCX delivery path.
- True single API call that asks the model to translate multiple languages in one batch.
- Account/user permission system for cloud deployment.

### Product decision required before implementation
1. If one selected language fails QA, should merged delivery include only passed languages or block ALL delivery? Recommended: generate ALL delivery with passed languages and mark failed languages in `QA摘要.xlsx`.
2. Should Step 7 automatically continue into Step 8 after each language finishes translation? Recommended: yes, but only if the translation run status is passed/ready; otherwise stop on that language.
3. Should manual “Skip QA and archive” be allowed in multi-language queue? Recommended: yes, but each skipped language must be marked as `qa_skipped` in merged delivery summary.

---

## File Structure

### Backend files
- Modify: `D:\codex\localization-workflow-studio\backend\app\schemas.py`
  - Add request/response schemas for multi-language orchestration and merged delivery.
- Create: `D:\codex\localization-workflow-studio\backend\app\workflow\multilingual.py`
  - Owns selected-language queue, child run discovery/creation, per-language status summary.
- Modify: `D:\codex\localization-workflow-studio\backend\app\workflow\delivery.py`
  - Add merged workbook delivery builder while keeping existing single-run `build_delivery_package()`.
- Modify: `D:\codex\localization-workflow-studio\backend\app\routers\runs.py`
  - Add API to start/resume selected-language translation queue.
- Modify: `D:\codex\localization-workflow-studio\backend\app\routers\qa.py`
  - Add API to run selected-language QA queue.
- Modify: `D:\codex\localization-workflow-studio\backend\app\routers\delivery.py`
  - Add API to build merged delivery package.
- Test: `D:\codex\localization-workflow-studio\backend\tests\test_multilingual_orchestration.py`
- Test: `D:\codex\localization-workflow-studio\backend\tests\test_multilingual_delivery.py`

### Frontend files
- Modify: `D:\codex\localization-workflow-studio\frontend\src\main.tsx`
  - Replace single-language Step 7/8 action calls with orchestration calls.
- Modify: `D:\codex\localization-workflow-studio\frontend\src\components\translationWizard\TranslationWizard.tsx`
  - Show queue progress and merged delivery entry.
- Modify: `D:\codex\localization-workflow-studio\frontend\src\types.ts`
  - Add frontend types for multilingual queue/progress/delivery.
- Test: `D:\codex\localization-workflow-studio\frontend\e2e\studio-ui-flow.spec.ts`

---

## Task 1: Add backend multilingual queue status model

**Files:**
- Create: `D:\codex\localization-workflow-studio\backend\app\workflow\multilingual.py`
- Modify: `D:\codex\localization-workflow-studio\backend\app\schemas.py`
- Test: `D:\codex\localization-workflow-studio\backend\tests\test_multilingual_orchestration.py`

- [ ] **Step 1: Write failing tests for per-language child run discovery**

Add tests that create a project, one source artifact, and runs for EN/KR. Assert that the status response returns all selected languages and maps existing child runs by `language + input_artifact_id + kind`.

```python
# D:\codex\localization-workflow-studio\backend\tests\test_multilingual_orchestration.py

def test_multilingual_status_maps_existing_child_runs(client, tmp_path):
    project = client.post('/api/projects', json={'name': 'multi status', 'type': 'QA', 'description': ''}).json()
    artifact = client.post(
        f"/api/projects/{project['id']}/files?kind=language_table",
        files={'file': ('sample.xlsx', make_language_table_bytes(['EN', 'KR']), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')},
    ).json()
    en_run = client.post('/api/runs', json={
        'project_id': project['id'],
        'kind': 'translation',
        'language': 'en',
        'input_artifact_id': artifact['id'],
        'batch_size': 10,
    }).json()

    result = client.get(
        f"/api/projects/{project['id']}/multilingual/status",
        params={'input_artifact_id': artifact['id'], 'languages': 'en,ko'},
    ).json()

    assert [item['language'] for item in result['languages']] == ['en', 'ko']
    assert result['languages'][0]['run_id'] == en_run['id']
    assert result['languages'][0]['status'] in {'queued', 'running', 'passed', 'failed'}
    assert result['languages'][1]['run_id'] is None
    assert result['overall_status'] == 'partial'
```

- [ ] **Step 2: Run the test and confirm it fails**

Run:

```powershell
Set-Location 'D:\codex\localization-workflow-studio'
python -m pytest backend/tests/test_multilingual_orchestration.py -q
```

Expected: FAIL because `/api/projects/{id}/multilingual/status` does not exist.

- [ ] **Step 3: Implement `workflow/multilingual.py` status helpers**

Create functions:

```python
# D:\codex\localization-workflow-studio\backend\app\workflow\multilingual.py
from __future__ import annotations

from typing import Any

from backend.app import db
from backend.app.languages import normalize_language_code, visible_language_code

TRANSLATION_KINDS = {'translation', 'translation_run'}
QA_KINDS = {'qa', 'qa_run'}


def normalize_language_list(languages: list[str] | str) -> list[str]:
    raw = languages.split(',') if isinstance(languages, str) else languages
    normalized: list[str] = []
    for item in raw:
        code = normalize_language_code(str(item).strip())
        if code and code not in normalized:
            normalized.append(code)
    if not normalized:
        raise ValueError('请选择至少一种目标语言')
    return normalized


def find_child_run(project_id: str, language: str, input_artifact_id: str, kind: str) -> dict[str, Any] | None:
    project = db.get_project(project_id)
    for run in project.get('runs', []):
        metadata = run.get('metadata') or {}
        run_input = metadata.get('input_artifact_id') or run.get('input_artifact_id')
        if run.get('language') == language and run_input == input_artifact_id and run.get('kind') == kind:
            return run
    return None


def multilingual_status(project_id: str, input_artifact_id: str, languages: list[str] | str) -> dict[str, Any]:
    selected = normalize_language_list(languages)
    rows = []
    for language in selected:
        translation_run = find_child_run(project_id, language, input_artifact_id, 'translation')
        qa_run = find_child_run(project_id, language, input_artifact_id, 'qa')
        active_run = qa_run or translation_run
        rows.append({
            'language': language,
            'visible_language': visible_language_code(language),
            'run_id': active_run.get('id') if active_run else None,
            'translation_run_id': translation_run.get('id') if translation_run else None,
            'qa_run_id': qa_run.get('id') if qa_run else None,
            'status': active_run.get('status') if active_run else 'pending',
            'step': 'qa' if qa_run else ('translation' if translation_run else 'pending'),
        })
    if all(item['status'] == 'passed' for item in rows):
        overall = 'passed'
    elif any(item['status'] in {'running', 'queued'} for item in rows):
        overall = 'running'
    elif any(item['status'] == 'failed' for item in rows):
        overall = 'failed'
    else:
        overall = 'partial'
    return {'project_id': project_id, 'input_artifact_id': input_artifact_id, 'overall_status': overall, 'languages': rows}
```

- [ ] **Step 4: Add route and schema**

Add schema fields:

```python
# D:\codex\localization-workflow-studio\backend\app\schemas.py
class MultilingualQueueRequest(BaseModel):
    input_artifact_id: str
    languages: list[str]
    batch_size: int | None = None
    task_code: str | None = None

class MultilingualQueueStatus(BaseModel):
    project_id: str
    input_artifact_id: str
    overall_status: str
    languages: list[dict[str, Any]]
```

Add route:

```python
# D:\codex\localization-workflow-studio\backend\app\routers\runs.py
@router.get('/api/projects/{project_id}/multilingual/status')
def get_multilingual_status(project_id: str, input_artifact_id: str, languages: str):
    return multilingual_status(project_id, input_artifact_id, languages)
```

- [ ] **Step 5: Run backend test**

Run:

```powershell
python -m pytest backend/tests/test_multilingual_orchestration.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/workflow/multilingual.py backend/app/schemas.py backend/app/routers/runs.py backend/tests/test_multilingual_orchestration.py
git commit -m "feat: add multilingual run status model"
```

---

## Task 2: Add backend queue start/resume for translation runs

**Files:**
- Modify: `D:\codex\localization-workflow-studio\backend\app\workflow\multilingual.py`
- Modify: `D:\codex\localization-workflow-studio\backend\app\routers\runs.py`
- Test: `D:\codex\localization-workflow-studio\backend\tests\test_multilingual_orchestration.py`

- [ ] **Step 1: Write failing test for queue start creating one child run per language**

```python
def test_start_multilingual_translation_creates_missing_child_runs(client):
    project = client.post('/api/projects', json={'name': 'multi translate', 'type': 'QA', 'description': ''}).json()
    artifact = upload_language_table(client, project['id'], ['EN', 'KR'])

    result = client.post(f"/api/projects/{project['id']}/multilingual/translate/start", json={
        'input_artifact_id': artifact['id'],
        'languages': ['en', 'ko'],
        'batch_size': 10,
        'task_code': 'T',
    }).json()

    assert result['overall_status'] in {'queued', 'running', 'partial'}
    assert {item['language'] for item in result['languages']} == {'en', 'ko'}
    assert all(item['translation_run_id'] for item in result['languages'])
```

- [ ] **Step 2: Implement queue creator**

Add helper:

```python
def ensure_translation_child_runs(project_id: str, input_artifact_id: str, languages: list[str], *, batch_size: int | None, task_code: str | None) -> dict[str, Any]:
    created: list[str] = []
    for language in normalize_language_list(languages):
        existing = find_child_run(project_id, language, input_artifact_id, 'translation')
        if existing:
            continue
        run = db.create_run(project_id=project_id, kind='translation', language=language, metadata={
            'input_artifact_id': input_artifact_id,
            'batch_size': batch_size,
            'task_code': task_code or 'T',
            'task_origin': 'multilingual_queue',
            'parent_input_artifact_id': input_artifact_id,
        })
        created.append(run['id'])
    status = multilingual_status(project_id, input_artifact_id, languages)
    status['created_run_ids'] = created
    return status
```

- [ ] **Step 3: Add API route**

```python
@router.post('/api/projects/{project_id}/multilingual/translate/start')
def start_multilingual_translation(project_id: str, payload: MultilingualQueueRequest):
    return ensure_translation_child_runs(
        project_id,
        payload.input_artifact_id,
        payload.languages,
        batch_size=payload.batch_size,
        task_code=payload.task_code,
    )
```

- [ ] **Step 4: Run test**

Run:

```powershell
python -m pytest backend/tests/test_multilingual_orchestration.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/workflow/multilingual.py backend/app/routers/runs.py backend/tests/test_multilingual_orchestration.py
git commit -m "feat: create multilingual translation child runs"
```

---

## Task 3: Add merged workbook delivery builder

**Files:**
- Modify: `D:\codex\localization-workflow-studio\backend\app\workflow\delivery.py`
- Modify: `D:\codex\localization-workflow-studio\backend\app\routers\delivery.py`
- Test: `D:\codex\localization-workflow-studio\backend\tests\test_multilingual_delivery.py`

- [ ] **Step 1: Write failing test for merged workbook output**

```python
def test_merged_delivery_combines_passed_language_outputs(client):
    project = client.post('/api/projects', json={'name': 'merged delivery', 'type': 'QA', 'description': ''}).json()
    source = upload_language_table(client, project['id'], ['EN', 'KR'])
    en_run = create_passed_run_with_final_workbook(client, project['id'], source['id'], 'en', {'EN': ['Start', 'Reward']})
    kr_run = create_passed_run_with_final_workbook(client, project['id'], source['id'], 'ko', {'KR': ['시작', '보상']})

    result = client.post(f"/api/projects/{project['id']}/delivery-package/merged", json={
        'input_artifact_id': source['id'],
        'languages': ['en', 'ko'],
    }).json()

    final_file = next(item for item in result['files'] if item['role'] == 'merged_final')
    rows = read_xlsx_rows(final_file['path'])
    assert rows[0] == ['ID', 'CN', 'EN', 'KR']
    assert rows[1][2] == 'Start'
    assert rows[1][3] == '시작'
```

- [ ] **Step 2: Implement language-column merge**

Add helper functions to `delivery.py`:

```python
def build_merged_delivery_package(project_id: str, input_artifact_id: str, languages: list[str]) -> dict[str, Any]:
    project = db.get_project(project_id)
    selected_languages = normalize_language_list(languages)
    source_artifact = db.get_artifact(input_artifact_id)
    if source_artifact['project_id'] != project_id:
        raise ValueError('输入文件不属于当前项目')

    output_dir = project_dir(project_id) / 'delivery'
    output_dir.mkdir(parents=True, exist_ok=True)
    merged_path = output_dir / f"{safe_delivery_name(project['name'])}_ALL_{datetime.now().strftime('%Y%m%d%H%M')}_final.xlsx"
    shutil.copy2(source_artifact['path'], merged_path)

    merged_languages: list[str] = []
    skipped_languages: list[str] = []
    for language in selected_languages:
        run = _find_passed_translation_or_qa_run(project_id, input_artifact_id, language)
        if not run:
            skipped_languages.append(language)
            continue
        final_artifact = _deliverable_final_artifact(run)
        if not final_artifact or not Path(final_artifact['path']).exists():
            skipped_languages.append(language)
            continue
        _merge_language_column(merged_path, Path(final_artifact['path']), language)
        merged_languages.append(language)

    if not merged_languages:
        raise ValueError('没有可合并的已通过语言，请先完成翻译或 QA')

    qa_summary = _write_merged_delivery_summary(output_dir, merged_languages, skipped_languages)
    return {
        'project_id': project_id,
        'project_name': project['name'],
        'merged_languages': [visible_language_code(code) for code in merged_languages],
        'skipped_languages': [visible_language_code(code) for code in skipped_languages],
        'files': [
            _delivery_file('merged_final', merged_path),
            _delivery_file('qa_summary', qa_summary),
        ],
    }
```

Add exact merge behavior:

```python
def _merge_language_column(target_path: Path, source_path: Path, language: str) -> None:
    target_wb = load_workbook(target_path)
    source_wb = load_workbook(source_path, data_only=False)
    visible = visible_language_code(language)
    target_ws = target_wb[target_wb.sheetnames[0]]
    source_ws = source_wb[source_wb.sheetnames[0]]
    target_col = _find_or_create_header_column(target_ws, visible)
    source_col = _find_header_column(source_ws, visible)
    id_target_col = _find_header_column(target_ws, 'ID')
    id_source_col = _find_header_column(source_ws, 'ID')
    source_by_id = {str(row[id_source_col - 1].value): row[source_col - 1].value for row in source_ws.iter_rows(min_row=2)}
    for row in target_ws.iter_rows(min_row=2):
        row_id = str(row[id_target_col - 1].value)
        if row_id in source_by_id:
            target_ws.cell(row=row[0].row, column=target_col).value = source_by_id[row_id]
    target_wb.save(target_path)
```

- [ ] **Step 3: Add route**

```python
@router.post('/api/projects/{project_id}/delivery-package/merged')
def create_merged_delivery_package(project_id: str, payload: MultilingualQueueRequest):
    return build_merged_delivery_package(project_id, payload.input_artifact_id, payload.languages)
```

- [ ] **Step 4: Run delivery tests**

Run:

```powershell
python -m pytest backend/tests/test_multilingual_delivery.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/workflow/delivery.py backend/app/routers/delivery.py backend/tests/test_multilingual_delivery.py
git commit -m "feat: build merged multilingual delivery workbook"
```

---

## Task 4: Frontend Step 7 queue action

**Files:**
- Modify: `D:\codex\localization-workflow-studio\frontend\src\types.ts`
- Modify: `D:\codex\localization-workflow-studio\frontend\src\main.tsx`
- Modify: `D:\codex\localization-workflow-studio\frontend\src\components\translationWizard\TranslationWizard.tsx`
- Test: `D:\codex\localization-workflow-studio\frontend\e2e\studio-ui-flow.spec.ts`

- [ ] **Step 1: Add frontend types**

```ts
export type MultilingualQueueLanguage = {
  language: LanguageCode
  visible_language: string
  run_id?: string | null
  translation_run_id?: string | null
  qa_run_id?: string | null
  status: string
  step: 'pending' | 'translation' | 'qa' | 'delivery'
}

export type MultilingualQueueStatus = {
  project_id: string
  input_artifact_id: string
  overall_status: string
  languages: MultilingualQueueLanguage[]
  created_run_ids?: string[]
}
```

- [ ] **Step 2: Replace single start button behavior when multiple languages selected**

In `main.tsx`, add:

```ts
async function startMultilingualTranslationQueue() {
  if (!current || !sourceArtifact) return
  setBusy(true)
  setStatus(`正在创建 ${selectedLanguages.map((code) => languageSpec(code).short).join(' / ')} 翻译队列...`)
  try {
    const result = await api<MultilingualQueueStatus>(`/api/projects/${current.id}/multilingual/translate/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        input_artifact_id: sourceArtifact.id,
        languages: selectedLanguages,
        batch_size: selectedBatchSize,
        task_code: taskCode,
      }),
    })
    setStatus(`已创建多语言队列：${result.languages.map((item) => item.visible_language).join(' / ')}。工作台会按语言逐个处理。`)
    await refresh()
  } catch (error) {
    setStatus(`多语言队列启动失败：${errorText(error)}`)
  } finally {
    setBusy(false)
  }
}
```

- [ ] **Step 3: Wire button text**

In `TranslationWizard.tsx` Step 7:

```tsx
<button className="btn" disabled={busy || !sourceArtifact} onClick={selectedLanguages.length > 1 ? onStartMultilingualTranslationQueue : onStartTranslation}>
  {selectedLanguages.length > 1 ? `开始 ${selectedLanguages.length} 种语言队列` : `开始 ${languageSpec(selectedLanguage).short} 翻译`}
</button>
```

- [ ] **Step 4: E2E smoke assertion**

Add test:

```ts
test('translation step starts multilingual queue from selected languages', async ({ page }) => {
  await createProjectAndOpenTranslationWizard(page)
  await uploadLanguageTableWithHeaders(page, ['ID', 'CN', 'EN', 'KR'])
  await page.getByRole('button', { name: /EN 英语/ }).click()
  await page.getByRole('button', { name: /KR 韩语/ }).click()
  await page.getByRole('button', { name: /开始 2 种语言队列/ }).click()
  await expect(page.getByText(/已创建多语言队列/)).toBeVisible()
})
```

- [ ] **Step 5: Run frontend checks**

Run:

```powershell
Set-Location 'D:\codex\localization-workflow-studio\frontend'
npm run build
npm run e2e -- --workers=1
```

Expected: build PASS, E2E PASS.

- [ ] **Step 6: Commit**

```powershell
git add frontend/src/types.ts frontend/src/main.tsx frontend/src/components/translationWizard/TranslationWizard.tsx frontend/e2e/studio-ui-flow.spec.ts
git commit -m "feat: start multilingual translation queue from wizard"
```

---

## Task 5: Frontend Step 8 queue QA action

**Files:**
- Modify: `D:\codex\localization-workflow-studio\frontend\src\main.tsx`
- Modify: `D:\codex\localization-workflow-studio\frontend\src\components\translationWizard\TranslationWizard.tsx`
- Modify: `D:\codex\localization-workflow-studio\backend\app\workflow\multilingual.py`
- Modify: `D:\codex\localization-workflow-studio\backend\app\routers\qa.py`

- [ ] **Step 1: Add backend QA queue helper**

```python
def ensure_qa_child_runs(project_id: str, input_artifact_id: str, languages: list[str]) -> dict[str, Any]:
    created: list[str] = []
    for language in normalize_language_list(languages):
        existing = find_child_run(project_id, language, input_artifact_id, 'qa')
        if existing:
            continue
        source_run = find_child_run(project_id, language, input_artifact_id, 'translation')
        if not source_run or source_run.get('status') not in {'passed', 'translated', 'completed'}:
            continue
        final_artifact = _find_final_artifact_for_run(source_run['id'])
        if not final_artifact:
            continue
        run = db.create_run(project_id=project_id, kind='qa', language=language, metadata={
            'input_artifact_id': final_artifact['id'],
            'source_translation_run_id': source_run['id'],
            'task_origin': 'multilingual_queue',
            'parent_input_artifact_id': input_artifact_id,
        })
        created.append(run['id'])
    status = multilingual_status(project_id, input_artifact_id, languages)
    status['created_run_ids'] = created
    return status
```

- [ ] **Step 2: Add API route**

```python
@router.post('/api/projects/{project_id}/multilingual/qa/start')
def start_multilingual_qa(project_id: str, payload: MultilingualQueueRequest):
    return ensure_qa_child_runs(project_id, payload.input_artifact_id, payload.languages)
```

- [ ] **Step 3: Add frontend action**

```ts
async function startMultilingualQaQueue() {
  if (!current || !sourceArtifact) return
  setBusy(true)
  setStatus(`正在创建 ${selectedLanguages.length} 种语言 QA 队列...`)
  try {
    const result = await api<MultilingualQueueStatus>(`/api/projects/${current.id}/multilingual/qa/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ input_artifact_id: sourceArtifact.id, languages: selectedLanguages }),
    })
    setStatus(`QA 队列已创建：${result.languages.map((item) => `${item.visible_language} ${item.status}`).join(' / ')}`)
    await refresh()
  } catch (error) {
    setStatus(`QA 队列启动失败：${errorText(error)}`)
  } finally {
    setBusy(false)
  }
}
```

- [ ] **Step 4: UI copy**

Step 8 should display:

```tsx
<div className="info-line compact">
  已选 {selectedLanguageText}。点击“运行多语言 QA”后，工作台会按语言逐个校对；失败语言可断点继续，不影响已通过语言。
</div>
```

- [ ] **Step 5: Run tests and commit**

```powershell
python -m pytest backend/tests/test_multilingual_orchestration.py -q
Set-Location 'D:\codex\localization-workflow-studio\frontend'
npm run build
npm run e2e -- --workers=1
git add backend/app/workflow/multilingual.py backend/app/routers/qa.py frontend/src/main.tsx frontend/src/components/translationWizard/TranslationWizard.tsx
git commit -m "feat: orchestrate multilingual QA queue"
```

---

## Task 6: Frontend Step 9 merged delivery UI

**Files:**
- Modify: `D:\codex\localization-workflow-studio\frontend\src\main.tsx`
- Modify: `D:\codex\localization-workflow-studio\frontend\src\components\translationWizard\TranslationWizard.tsx`

- [ ] **Step 1: Add merged delivery action**

```ts
async function createMergedDeliveryPackage() {
  if (!current || !sourceArtifact) return
  setBusy(true)
  setStatus(`正在生成 ${selectedLanguages.map((code) => languageSpec(code).short).join(' / ')} 合并交付...`)
  try {
    const result = await api<{ files: DeliveryFile[]; merged_languages: string[]; skipped_languages: string[] }>(`/api/projects/${current.id}/delivery-package/merged`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ input_artifact_id: sourceArtifact.id, languages: selectedLanguages }),
    })
    await refreshDeliverables()
    setStatus(`合并交付已生成：${result.merged_languages.join(' / ')}；文件 ${result.files.length} 个。`)
  } catch (error) {
    setStatus(`合并交付生成失败：${errorText(error)}`)
  } finally {
    setBusy(false)
  }
}
```

- [ ] **Step 2: Add Step 9 button**

```tsx
<button className="btn" disabled={busy || selectedLanguages.length < 2 || !sourceArtifact} onClick={onCreateMergedDeliveryPackage}>
  生成多语言合并交付
</button>
```

- [ ] **Step 3: Clarify single-language fallback**

Step 9 should show two blocks:

```tsx
<section className="delivery-choice-card">
  <strong>多语言合并交付</strong>
  <p>适用于本次勾选了多个目标语言的语言包。输出一个完整 workbook，包含已通过语言列。</p>
</section>
<section className="delivery-choice-card muted">
  <strong>单语言交付</strong>
  <p>保留现有 final/changes 下载，用于单独交付或问题排查。</p>
</section>
```

- [ ] **Step 4: E2E assertion**

```ts
test('step 9 exposes merged delivery for selected languages', async ({ page }) => {
  await openProjectWithPassedEnAndKrRuns(page)
  await page.getByRole('button', { name: '交付' }).click()
  await expect(page.getByRole('button', { name: /生成多语言合并交付/ })).toBeVisible()
})
```

- [ ] **Step 5: Run and commit**

```powershell
Set-Location 'D:\codex\localization-workflow-studio\frontend'
npm run build
npm run e2e -- --workers=1
git add frontend/src/main.tsx frontend/src/components/translationWizard/TranslationWizard.tsx frontend/e2e/studio-ui-flow.spec.ts
git commit -m "feat: add merged delivery action to translation wizard"
```

---

## Task 7: Full validation and release checkpoint

**Files:**
- Modify: `D:\codex\localization-workflow-studio\docs\codex-handoffs\2026-06-12-multilingual-delivery-orchestration.md`

- [ ] **Step 1: Run backend validation**

```powershell
Set-Location 'D:\codex\localization-workflow-studio'
python -m pytest -q
python -m compileall -q backend workflow
python -m ruff check backend/app backend/tests --select E9,F
```

Expected:
- All tests pass.
- Compileall returns no output.
- Ruff says `All checks passed!`.

- [ ] **Step 2: Run frontend validation**

```powershell
Set-Location 'D:\codex\localization-workflow-studio\frontend'
npm run build
npm run e2e -- --workers=1
```

Expected:
- TypeScript build passes.
- Playwright E2E passes.

- [ ] **Step 3: Run forbidden MT scan**

```powershell
Set-Location 'D:\codex\localization-workflow-studio'
rg -n -i "deep_translator|googletrans|GoogleTranslator|translate\.google|google translate|Google Translate|GOOGLE_TRANSLATE|google_trans" backend workflow frontend --glob "!frontend/node_modules/**" --glob "!frontend/dist/**"
```

Expected: no matches.

- [ ] **Step 4: Update handoff note**

Append:

```markdown
## Implementation result
- Multi-language selected queue implemented for normal language-pack translation.
- Single-language run remains the resumable child unit.
- Step 9 can generate a merged ALL workbook from passed child outputs.
- Existing single-language final/changes delivery remains available.
```

- [ ] **Step 5: Commit validation note**

```powershell
git add docs/codex-handoffs/2026-06-12-multilingual-delivery-orchestration.md
git commit -m "docs: record multilingual delivery implementation result"
```

---

## Rollback Plan

- If queue creation breaks translation, revert Task 2 commit only. Existing single-language workflow remains intact because old `/api/runs` path is unchanged.
- If merged delivery workbook has format issues, revert Task 3 and Task 6 commits only. Single-language delivery remains intact.
- If Step 8 queue QA is unstable, hide the multi-language QA button and keep the single-language QA action until backend status is fixed.

## Acceptance Criteria

- User can select EN/KR/JP once in Step 6.
- Step 7 starts/reuses all selected language translation child runs without manual language switching.
- Step 8 starts/reuses all selected language QA child runs without manual language switching.
- Step 9 generates a merged final workbook containing all passed selected language columns.
- Failed languages are visible and resumable; passed languages are not rerun.
- Existing single-language workflow and delivery still work.
- Announcement workflow remains unchanged.
- Full validation passes.
