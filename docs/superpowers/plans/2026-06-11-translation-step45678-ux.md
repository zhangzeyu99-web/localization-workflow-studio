# Translation Step 4-8 Logic and UX Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Step 4-8 correctly branch between translation input, already-translated QA input, and invalid format, while keeping the UI clear for users.

**Architecture:** Keep the existing 9-step wizard and backend API shape. Add one small classification layer around language-table readiness, then let the frontend route users to the right next step without adding new steps. Backend remains the source of truth for file structure/readiness; frontend only displays and routes.

**Tech Stack:** FastAPI, SQLite, openpyxl, React/TypeScript, Playwright.

---

## Product brief

- Product: localization workflow studio, main translation wizard.
- Screen/flow: new translation task Step 4-8.
- Visual direction: keep existing dark workbench style; reduce ambiguity with compact cards, clear branch labels, and a single primary next action.
- Interactivity: full working states; upload, detection, route-to-translation, route-to-QA, and invalid replacement must work.

## Correct user flow

```text
STEP 4 上传/选择语言表
  -> 后端检查结构和目标列
  -> A. 待翻译表: ID + CN + 目标语言列为空/缺译文/中文残留
        下一步 = STEP 5 扫描术语候选 -> STEP 6 目标语言确认 -> STEP 7 模型翻译 -> STEP 8 QA
  -> B. 已译校对表: ID + CN + 目标语言列完整
        下一步 = STEP 8 QA，不走 STEP 5/7
  -> C. 格式错误: 缺 ID/CN/可识别语言列，或文件不可读
        不设为当前输入，提示重新上传；新上传替换旧选择
```

## Files

- Modify: `backend/app/workflow/translation_readiness.py`
- Modify: `backend/app/routers/projects.py`
- Modify: `frontend/src/domain/translationFlow.ts`
- Modify: `frontend/src/components/translationWizard/TranslationWizard.tsx`
- Modify: `frontend/src/main.tsx`
- Test: `backend/tests/test_workflow_e2e.py`
- Test: `frontend/e2e/studio-ui-flow.spec.ts`

## Task 1: Backend readiness returns user-action classification

- [ ] Add fields to `inspect_translation_readiness()` result:
  - `input_mode`: `needs_translation | ready_for_qa | invalid`
  - `next_step`: `5 | 8 | 4`
  - `format_errors`: string array
  - `user_message`: short Chinese instruction

Expected mapping:

```python
if not source_rows:
    input_mode = "invalid"
    next_step = 4
    user_message = "未检测到 CN/原文行，请上传包含 ID 和 CN 的语言表。"
elif invalid_id_rows:
    input_mode = "invalid"
    next_step = 4
    user_message = "有行缺少可回写 ID，请修正后重新上传。"
elif ready_for_qa:
    input_mode = "ready_for_qa"
    next_step = 8
    user_message = "检测到已有完整译文，可跳过模型翻译，直接进入校对。"
else:
    input_mode = "needs_translation"
    next_step = 5
    user_message = "检测到待翻译内容，请先扫描术语候选。"
```

- [ ] Keep existing fields (`ready_for_qa`, `needs_translation`, `reason`) for compatibility.
- [ ] Add backend tests:
  - empty target table returns `input_mode=needs_translation`, `next_step=5`.
  - full translated table returns `input_mode=ready_for_qa`, `next_step=8`.
  - missing ID or missing CN returns `input_mode=invalid`, `next_step=4`.

Run:

```powershell
python -m pytest backend/tests/test_workflow_e2e.py -q
```

## Task 2: Frontend centralizes input classification

- [ ] Add helpers in `frontend/src/domain/translationFlow.ts`:
  - `translationInputMode(readiness)`
  - `translationNextStep(readiness)`
  - `translationReadinessUserMessage(readiness)`
- [ ] Preserve `canSkipModelTranslation()` but make it call the new mode helper.
- [ ] Add TypeScript fields to `TranslationReadiness` in `frontend/src/types.ts`.

Run:

```powershell
cd frontend
npm run build
```

## Task 3: Step 4 becomes the decision point

- [ ] Rename visible title from `导入待翻译内容` to `导入语言表 / 已译表`.
- [ ] After upload, immediately run target detection + readiness.
- [ ] If mode is `needs_translation`:
  - set `sourceArtifact`.
  - clear `qaArtifact` if it points to another language table.
  - show status: `检测到待翻译语言表：下一步扫描术语候选。`
- [ ] If mode is `ready_for_qa`:
  - set `sourceArtifact` and `qaArtifact` to the uploaded artifact.
  - show primary CTA: `去校对`.
  - make wizard 下一步 route to Step 8.
- [ ] If mode is `invalid`:
  - do not set `sourceArtifact`.
  - clear stale `translationReadiness`.
  - show red/amber error card with backend `user_message`.
  - show `重新上传并替换` guidance.

No raw JSON, no traceback, no backend English reason in user-facing copy.

## Task 4: Step 5 only appears as active for translation-needed inputs

- [ ] If no valid language table: show “请先回 STEP 4 上传正确语言表”.
- [ ] If mode is `ready_for_qa`: show a compact skip card:

```text
这份表已有完整译文，不需要扫描术语候选。
下一步：去 STEP 8 校对；QA 通过后写入译文归档并生成交付。
```

- [ ] Disable `扫描术语候选` for `ready_for_qa` and `invalid`.
- [ ] Keep manual step clicking allowed, but each step displays the correct blocker/action.

## Task 5: Step 6-8 copy and actions follow the branch

- [ ] Step 6 remains target language confirmation; if language was detected in Step 4, show it as already selected.
- [ ] Step 7:
  - For `needs_translation`, show model translation controls.
  - For `ready_for_qa`, show only `这份表已含译文，请直接校对` + `去校对`.
- [ ] Step 8:
  - If `qaArtifact` is the Step 4 table, show “来自 Step 4 已译表”.
  - If QA fails, show failed reason and repair entry, not only a failed badge.
  - Keep “跳过 QA 直接归档” in collapsed advanced area only.

## Task 6: Replace wrong format cleanly

- [ ] On invalid upload, do not leave the invalid file selected.
- [ ] On next successful upload, replace the previous selected source and refresh readiness.
- [ ] If backend still stored the invalid artifact, hide it from the Step 4 picker by default when metadata/readiness marks it invalid. If no metadata marker exists, hide only current invalid upload in local state for v1.

## Task 7: E2E coverage

Add Playwright scenarios:

- [ ] Upload empty target workbook in Step 4 -> Step 5 is enabled and Step 7 shows translation path.
- [ ] Upload already-translated workbook in Step 4 -> Step 5 skip card appears; `去校对` routes to Step 8.
- [ ] Upload bad workbook -> human error appears; source picker does not select the bad file; re-upload good workbook replaces state.

Run:

```powershell
cd frontend
npm run e2e -- --workers=1 --reporter=line
```

## Final verification

```powershell
python -m pytest -q
python -m compileall -q backend workflow
python -m ruff check backend/app backend/tests --select E9,F
cd frontend
npm run build
npm run e2e -- --workers=1 --reporter=line
```

## Acceptance criteria

- Step 4 clearly tells the user which type of file was detected.
- Empty/untranslated language table continues to Step 5 and translation.
- Already translated workbook skips model translation and goes to Step 8 QA.
- Invalid format gives a human-readable error and does not poison the current source selection.
- Step 5/7 no longer suggest unnecessary work for already-translated input.
- No API/backend traceback appears in the UI.
