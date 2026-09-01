# Vietnamese Language Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Vietnamese as a complete Studio language using canonical internal code `vn`, UI code `VN`, and workbook target header `VI`.

**Architecture:** Extend the central backend and frontend registries so all registry-driven workflows inherit Vietnamese automatically. Keep `vn` in Studio state, map it to `vi` only at read-only localization subprocess boundaries, and make QA repair helpers language-aware so the full non-English writeback path works.

**Tech Stack:** Python 3.14, FastAPI, openpyxl, pytest, React, TypeScript, Playwright.

## Global Constraints

- Studio canonical code is `vn`; `vi` and `vie` are compatibility aliases only.
- UI label/code is `VN 越南语` / `VN`; workbook target header is `VI`.
- Do not modify `workflow/localization` or `workflow/glossary`.
- Preserve all pre-existing dirty worktree files.
- Do not commit or push without a new explicit user instruction.

---

### Task 1: Backend language contract

**Files:**
- Modify: `backend/tests/test_risk_hardening.py`
- Modify: `backend/app/languages.py`

**Interfaces:**
- Consumes: existing `LanguageSpec`, `normalize_language()`, and `/api/languages` payload contract.
- Produces: canonical `vn`, compatibility aliases `vi` and `vie`, `visible_code=VN`, `target_header=VI`, and `workflow_language_code()` for subprocess boundaries.

- [ ] **Step 1: Write failing registry/API tests**

Add assertions equivalent to:

```python
assert normalize_language("vn") == "vn"
assert normalize_language("vi") == "vn"
assert normalize_language("vie") == "vn"
assert workflow_language_code("vn") == "vi"
assert workflow_language_code("vi") == "vi"
item = languages["vn"]
assert item["visible_code"] == "VN"
assert item["target_header"] == "VI"
assert {"vi", "vie", "vietnamese", "越南语", "越南文"}.issubset(set(item["target_aliases"]))
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
py -3.14 -m pytest backend/tests/test_risk_hardening.py -q
```

Expected: failure because `vn` is not registered and the API has no Vietnamese item.

- [ ] **Step 3: Implement the backend registry**

Extend `LanguageSpec` and `_spec()` with an optional UI-visible code whose default is the target header. Add:

```python
"vn": _spec(
    "vn",
    "VN 越南语",
    "Vietnamese",
    "VI",
    ("vi", "vie", "vietnamese", "越南语", "越南文"),
    visible_code="VN",
),
```

Append `vn` to the visible project/announcement order before hidden `ar`, map `vi` and `vie` to `vn`, return the UI code as `visible_code`, and keep `target_header=VI`. Add `workflow_language_code(value)` that returns `vi` for canonical `vn` and otherwise returns the supported Studio code unchanged.

- [ ] **Step 4: Run the focused backend test and verify GREEN**

Run the Step 2 command.

Expected: all tests in the file pass.

### Task 2: Frontend language contract and selector regression

**Files:**
- Modify: `frontend/src/languages.ts`
- Modify: `frontend/e2e/studio-ui-flow.spec.ts`

**Interfaces:**
- Consumes: `/api/languages` item with `code=vn`, `visible_code=VN`, `target_header=VI`.
- Produces: a stable `VN 越南语` option and normalized frontend state containing only `vn`.

- [ ] **Step 1: Write failing E2E expectations**

Update the full-language selector test to expect `VN 越南语`, click it, and assert the selected language request contains `vn`. Update fixed language counts and expected language arrays in project assets and announcement tests.

Use:

```ts
const expectedLanguages = ['en', 'fr', 'de', 'ru', 'it', 'es', 'pt', 'tr', 'idn', 'th', 'vn']
await expect(page.getByRole('button', { name: 'VN 越南语' })).toBeVisible()
```

- [ ] **Step 2: Run the focused E2E and verify RED**

Run:

```powershell
npm --prefix frontend run e2e -- --grep "full supported language set" --workers=1
```

Expected: failure because the frontend type/default registry rejects `vn`.

- [ ] **Step 3: Implement the frontend registry**

Add `vn` to `LanguageCode`, add the default option:

```ts
{ code: 'vn', label: 'VN 越南语', short: 'VN', targetHeader: 'VI', altHeader: '' }
```

Add aliases:

```ts
vi: 'vn', vie: 'vn'
```

Do not add `vn` to `hiddenUiLanguages`.

- [ ] **Step 4: Run the focused E2E and frontend build**

Run:

```powershell
npm --prefix frontend run e2e -- --grep "full supported language set" --workers=1
npm --prefix frontend run build
```

Expected: focused E2E and TypeScript/Vite build pass.

### Task 3: Language-aware QA repair/writeback

**Files:**
- Modify: `backend/tests/test_risk_hardening.py`
- Modify: `backend/app/workflow/translation.py`
- Modify: `backend/app/workflow/qa.py`
- Modify: `backend/app/workflow/qa_model_fixes.py`
- Modify: `backend/app/workflow/line_proofread.py`

**Interfaces:**
- Consumes: Studio run language such as `vn`, `workflow_language_code()`, and `target_aliases(language)`.
- Produces: localization subprocesses using `vi`, plus QA change collection, row resolution, manual/model fixes, and line-proofread writeback against the active Studio language column.

- [ ] **Step 1: Write failing VI-column repair tests**

Create before/after workbooks with headers `ID`, `CN`, `VI`. Assert:

```python
changes = workflow._collect_workbook_translation_changes(before, after, language="vn")
assert changes[0]["previous_translation"] == "Nhan thuong cu"
assert changes[0]["translation"] == "Nhận thưởng"

applied = workflow._apply_workbook_fixes(
    workbook,
    [{"sheet": "Language", "row": 2, "record_id": "1", "translation": "Nhận thưởng"}],
    "run-vn",
    language="vn",
)
assert applied[0]["previous_translation"] == "Nhan thuong cu"
```

- [ ] **Step 2: Run the focused QA tests and verify RED**

Run:

```powershell
py -3.14 -m pytest backend/tests/test_risk_hardening.py -q
```

Expected: helper signatures reject `language` or fail to locate `VI`.

- [ ] **Step 3: Make QA helpers language-aware**

Use `workflow_language_code(language)` for both translation-harness subprocess calls. In `run_localization_qa()`, use the same mapped code for `process_language.py`, `run_quality_harness.py`, and the expected `result_{code}.xlsx` / `report_{code}.xlsx` paths; keep all Studio metadata and subsequent Studio helpers on canonical `vn`.

Replace the hard-coded target alias constant in these helpers with `target_aliases(require_supported_language(language))`:

```python
def _collect_workbook_translation_changes(before_path: Path, after_path: Path, language: str = "en") -> list[dict[str, Any]]: ...
def _model_fix_row_context(path: Path, issue: dict[str, Any], language: str = "en") -> dict[str, Any]: ...
def _resolve_workbook_row_for_issue(..., language: str = "en") -> tuple[Any, int] | None: ...
def _apply_workbook_fixes(path: Path, fixes: list[dict[str, Any]], source_run_id: str, language: str = "en") -> list[dict[str, Any]]: ...
```

Thread `run.language` through manual fixes and model fixes, thread the existing `language` argument through line proofread, and pass `language` when collecting machine-QA changes.

- [ ] **Step 4: Run focused QA tests and verify GREEN**

Run the Step 2 command.

Expected: all focused tests pass, including legacy English behavior via default `language="en"`.

### Task 4: Vietnamese workflow coverage

**Files:**
- Modify: `backend/app/languages.py`
- Modify: `backend/app/workflow/multilingual.py`
- Modify: `backend/tests/test_workflow_e2e.py`
- Modify: `backend/tests/test_multilingual_orchestration.py`
- Modify: `frontend/e2e/studio-ui-flow.spec.ts`

**Interfaces:**
- Consumes: backend/frontend Vietnamese registry and language-aware QA helpers.
- Produces: `ui_language_code()` for UI/status payloads plus evidence that formal translation, QA/archive, quick task, announcement, glossary/archive wide views, and delivery accept `vn` while workbooks retain `VI`.

- [ ] **Step 1: Add a formal translation regression**

Use a multi-target workbook with `ID`, `CN`, `EN`, `VI`, start a fake-provider run with `language="vi"`, then assert the request normalizes to run/archive `vn`, the read-only translation manifest uses `vi`, the QA final path is `result_vi.xlsx`, and the final workbook contains translated `VI` cells while `EN` remains untouched.

- [ ] **Step 2: Add alias and auxiliary-flow assertions**

Verify a request using `vi` is normalized to `vn`. Add `ui_language_code(value)` returning the registry's UI code and use it for multilingual queue events/status so the payload is `language=vn`, `visible_language=VN`; keep `visible_language_code(value)` as the workbook/delivery header `VI`. Update the explicit quick-task, announcement, wide glossary/archive and frontend language-list assertions to include `vn` / `VN 越南语` and `VI` workbook columns.

- [ ] **Step 3: Run backend workflow tests**

Run:

```powershell
py -3.14 -m pytest backend/tests/test_workflow_e2e.py backend/tests/test_multilingual_orchestration.py -q
```

Expected: all tests pass without modifying read-only workflow files.

- [ ] **Step 4: Run the full frontend E2E suite**

Run:

```powershell
npm --prefix frontend run e2e -- --workers=1
```

Expected: all E2E tests pass; Vietnamese remains visible after `/api/languages` refresh.

### Task 5: Full verification and runtime acceptance

**Files:**
- Verify only; do not commit or push.

**Interfaces:**
- Consumes: all completed implementation tasks.
- Produces: reproducible acceptance evidence and a clean scope audit.

- [ ] **Step 1: Run static and unit/integration gates**

Run sequentially:

```powershell
py -3.14 -m pytest -q
py -3.14 -m compileall -q backend workflow
py -3.14 -m ruff check backend/app backend/tests --select E9,F
npm --prefix frontend run build
```

Expected: every command exits 0.

- [ ] **Step 2: Run frontend E2E separately**

Run:

```powershell
npm --prefix frontend run e2e -- --workers=1
```

Expected: all tests pass. Do not overlap this with pytest because both use shared runtime state.

- [ ] **Step 3: Restart and verify the local workbench**

Use the existing guarded starter, then verify ports `8000`, `5173`, `5174`, `/api/health`, `/api/languages`, and the independent monitor process. Confirm the live language payload contains exactly one Vietnamese item with `code=vn`.

- [ ] **Step 4: Audit scope and user-owned changes**

Run:

```powershell
git diff --check
git status --short --branch
git diff -- backend/app/languages.py backend/app/workflow/qa.py backend/app/workflow/qa_model_fixes.py backend/app/workflow/line_proofread.py backend/tests frontend/src/languages.ts frontend/e2e/studio-ui-flow.spec.ts
```

Expected: only request-traceable Vietnamese/QA changes plus the pre-existing user-owned dirty files; no changes under `workflow/localization` or `workflow/glossary`.
