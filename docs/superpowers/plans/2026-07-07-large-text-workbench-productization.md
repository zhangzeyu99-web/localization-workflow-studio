# Large Text Workbench Productization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put the large-text multilingual handling now living in the local workflow harness into the Workbench product flow, so large language-table runs get visible preflight, deterministic cache gates, delivery readback, and retro evidence without losing existing translation, QA, quick task, announcement, or merged-delivery behavior.

**Architecture:** Keep the current product model: one resumable `Run` per language, current `/api/runs/*`, `/api/projects/*/multilingual/*`, QA, archive, and delivery APIs remain valid. Add a product-side `large_text` helper layer that reuses the same rules as the local harness, stores gate outputs as artifacts and run metadata, and exposes small UI panels in Step 7, task history, and delivery. Do not import secrets into generated artifacts; do not move API keys into manifests.

**Tech Stack:** FastAPI, SQLite-backed local DB, existing Python translation harness, `openpyxl`, React/TypeScript, Playwright, pytest.

---

## Current State

- Already implemented in product:
  - `backend/app/workflow/multilingual.py` creates/reuses one child translation/QA run per selected language.
  - `backend/app/workflow/translation_orchestrator.py` already handles dynamic batch manifests, concurrency cap, retry, timeout, cancellation, resume, and batch debug downloads.
  - `backend/app/workflow/delivery.py` already supports single-run delivery and merged multilingual delivery.
  - `frontend/src/components/translationWizard/TranslationWizard.tsx` Step 7 already shows selected-language progress and batch progress.

- Already implemented outside product:
  - `workflow/localization/utils/large_text_multilingual_gate.py` has preflight, cache lint, apply dry-run, and readback gate rules.
  - `workflow/localization/utils/large_text_multilingual_runner.py` creates a local agent manifest without API secrets.
  - `workflow/localization/utils/large_text_multilingual_retro.py` renders skipped/waived gate status and long-task review.

- Missing product integration:
  - Translation runs do not persist large-text preflight metrics.
  - Product translation does not run the improved number/token/term cache-lint before applying AI output.
  - Delivery does not run a product readback gate against newly generated final files.
  - UI does not explain large-text mode, gate status, skipped/waived reason, or long-task review.

## Full-Range Tech Repo Read Addendum

Source range read for this plan:

- Workbench repo `D:\codex\localization-workflow-studio`: `07644a9..4989114`.
- Technical knowledge repo `D:\codex\codex`: local commits from `2026-07-06 00:00:00` through `d4ddb71`.

Implications now locked into this plan:

- Do not implement a simplified product numeric/token parser. Product cache lint must reuse, factor, or faithfully port the current behavior in `workflow/localization/utils/large_text_multilingual_gate.py`.
- The current gate behavior includes machine-like bracket token protection only, placeholder/font/newline token preservation, CJK residue checks, large-number tolerance, CJK date/month and small-number filtering, English/Indonesian/Spanish/Portuguese word multipliers, and Chinese/ASCII unit conversion.
- Gate statuses are not just pass/fail. Product metadata and UI must support `passed`, `failed`, `skipped`, and `waived`, with `reason` and `alternative_check` when skipped or waived.
- Long tasks over 3600 seconds require a review payload in retro output. This is not a blocker by itself; it is evidence for whether batch sizing, retries, skipped gates, or unexpected manual fixes need follow-up.
- Deep line proofreading/subagent execution remains outside product v1 unless explicitly requested by a separate workflow. Product v1 records evidence and deterministic gates; it does not spawn agent reviewers.
- Process artifacts stay as workbench artifacts and must not be packed as final delivery content. Final user delivery remains final files plus QA/readback summary.

## New Update Read Addendum: Announcement Glossary AI Supplement

Source range read for this update:

- Workbench `master` and fetched `origin/master` are at `1d30ff6` (`chore: update 1.0.3 repo metadata`), which updates `CHANGELOG.md`, README version text, `VERSION`, `backend/app/main.py`, and frontend package versions without changing runtime workflow behavior.
- Workbench remote branch `origin/codex/multilingual-announcement-workflow` is an ancestor of current `master`, not a new integration target. Do not merge or reverse-port its large public-cleanup diff into the current product tree.
- Glossary extraction repo `D:\codex\glossary-extraction-workflow`: read `d11fc4d..ae37b4e`, including tag `v0.3.0` and repository-management docs (`README.md`, `CHANGELOG.md`, `VERSION`) that mark the current workflow baseline.
- The workbench embedded `workflow/glossary/scripts/extract_glossary.py` is already near-parity with the standalone glossary repo and currently has an extra Windows UTF-8 stdio fix. Do not blindly overwrite it from the standalone repo.
- Product implementation and docs should treat `1.0.3` as the repo metadata baseline when running local validation.

Capabilities from the glossary repo now locked into this plan:

- Announcement-specific glossary lookup can auto-detect exported language-table headers after metadata rows.
- Structured or JSON-like cells such as `["活动名"]`, `["活动名", "#色值"]`, and nested help-title rows can produce clean term candidates.
- Multi-language announcement lookup uses explicit `--language-table LANG=path` inputs and emits one `Glossary` table with `ID / CN / EN / FR...`.
- Low-value generic terms are demoted rather than deleted, so users can still inspect them when needed.
- AI supplement is an evidence-bounded layer: packet contains only announcement text, already matched terms, relevant evidence rows, project name, and response schema; it must not contain the full language table or API secrets.
- AI supplement response can add only medium/high confidence, evidence-backed terms that appear in the announcement and have translations. Low-confidence, unbacked, or inferred translations stay report-only.
- Missing official project-name translation is a warning in the sidecar report, not a fake row in the main glossary.

Product-design implications:

- The announcement Step 4 experience should explain three states separately: deterministic lookup result, AI supplement status, and report-only warnings.
- Users should see the useful result first: term count, AI-added term count, missing translations, project-name warning, and downloadable workbook/report. Packet/response artifacts stay secondary.
- If provider/API is not configured, packet-only fallback is acceptable, but the UI should say AI supplement produced a packet/report and did not call a model.
- Do not ask users to run Codex packet flow manually inside the product path unless they choose an explicit upload-response path.

## Scope and Boundaries

### In scope

- Normal language-table translation workflow, including single-language and selected-language queue.
- Large text and large multilingual packs detected from workpack rows, target-language count, workbook count, and estimated target cells.
- Product-side deterministic gates:
  - preflight metrics
  - cache lint before workbook apply
  - delivery readback after final file generation
  - retro/long-task review artifact
- UI visibility in Step 7, run details, and delivery results.

### Out of scope

- No database schema migration.
- No replacement of current translation provider, prompt generation, QA, archive, or delivery APIs.
- No new external dependency.
- No product-level subagent execution in v1. Product can record `proofread_mode`, but agent/subagent deep proofreading stays outside the workbench until a separate plan.
- No DOCX/PDF large-text product gate in v1; product readback gate starts with workbook delivery and final TXT quick-task output only when already supported by existing delivery.

### Product decisions locked for v1

- Default mode is `auto`: enforce large-text cache lint only when the run is detected as large pack; still record skipped status for non-large runs.
- `strict` mode can be added later, but this plan only passes `auto` from the UI to avoid a new user-facing toggle.
- If cache lint fails, do not apply AI output to the workbook. Preserve `translation_response`, batch files, and `large_text_cache_lint` artifact for repair.
- If delivery readback fails, block the delivery response with a user-facing error after writing a readback artifact. “带问题摘要交付” can allow linguistic QA issues, not missing columns or blank target cells.
- Generated artifacts and metadata must not contain `api_key`.

---

## File Structure

### Backend

- Create: `D:\codex\localization-workflow-studio\backend\app\workflow\large_text.py`
  - Product helper for preflight, cache building, cache lint, readback gate, gate status normalization, and retro payloads.
- Modify: `D:\codex\localization-workflow-studio\backend\app\workflow\translation.py`
  - Call product large-text preflight after workpack generation.
  - Call cache lint before applying translation response.
  - Store gate artifact IDs and summaries in run metadata.
- Modify: `D:\codex\localization-workflow-studio\backend\app\workflow\multilingual.py`
  - Surface per-language `large_text` metadata in multilingual status.
- Modify: `D:\codex\localization-workflow-studio\backend\app\workflow\delivery.py`
  - Run readback gate for single and merged delivery outputs.
  - Add readback artifact IDs to delivery metadata.
- Modify: `D:\codex\localization-workflow-studio\backend\app\schemas.py`
  - Add optional `large_text_mode` to `TranslateRequest` and `MultilingualQueueRequest`.
- Modify: `D:\codex\localization-workflow-studio\backend\app\workflow\__init__.py`
  - Export helper functions only if tests need workflow-level imports.
- Test: `D:\codex\localization-workflow-studio\backend\tests\test_large_text_productization.py`
- Test: `D:\codex\localization-workflow-studio\backend\tests\test_multilingual_orchestration.py`
- Test: `D:\codex\localization-workflow-studio\backend\tests\test_multilingual_delivery.py`

### Frontend

- Modify: `D:\codex\localization-workflow-studio\frontend\src\types.ts`
  - Add typed metadata shapes for large-text preflight, gate, readback, retro, and multilingual language status.
- Modify: `D:\codex\localization-workflow-studio\frontend\src\main.tsx`
  - Pass `large_text_mode: 'auto'` on translation and multilingual queue starts.
- Modify: `D:\codex\localization-workflow-studio\frontend\src\components\translationWizard\TranslationWizard.tsx`
  - Add Step 7 large-text panel and RunDetail gate artifacts/status.
  - Add delivery readback status in Step 9/delivery cards.
- Modify: `D:\codex\localization-workflow-studio\frontend\src\styles.css`
  - Small styles for large-text panel; no design-system rewrite.
- Test: `D:\codex\localization-workflow-studio\frontend\e2e\studio-ui-flow.spec.ts`

### Local harness

- Keep:
  - `workflow/localization/utils/large_text_multilingual_gate.py`
  - `workflow/localization/utils/large_text_multilingual_runner.py`
  - `workflow/localization/utils/large_text_multilingual_retro.py`
- Add parity tests instead of moving these files in v1. This avoids breaking local CLI usage while product integration lands.

---

## Task 1: Product Large-Text Helper

**Files:**
- Create: `backend/app/workflow/large_text.py`
- Test: `backend/tests/test_large_text_productization.py`

- [ ] **Step 1: Write failing tests for product preflight**

Add this test file:

```python
# backend/tests/test_large_text_productization.py
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

os.environ["LWS_DATA_ROOT"] = str(Path(tempfile.gettempdir()) / "lws-test-data")

import app.db as db
from app.config import DEFAULT_SETTINGS, save_settings
from app.workflow.large_text import build_large_text_preflight, normalize_large_text_mode
from conftest import reset_data_root, wait_for_background_jobs


def setup_function() -> None:
    reset_data_root(Path(os.environ["LWS_DATA_ROOT"]))
    db.init_db()
    save_settings(DEFAULT_SETTINGS)


def teardown_function() -> None:
    wait_for_background_jobs()
    save_settings(DEFAULT_SETTINGS)


def test_build_large_text_preflight_marks_large_multilingual_pack() -> None:
    rows = [{"id": f"row-{index}", "source": "长文本" * 160} for index in range(6000)]

    result = build_large_text_preflight(
        rows,
        target_languages=["en", "ko", "ja", "fr", "de"],
        source_rows=6000,
        workbook_count=1,
        full_proofread=False,
    )

    assert result["workflow"] == "large_text_product_v1"
    assert result["unique_items"] == 6000
    assert result["target_language_count"] == 5
    assert result["estimated_target_cells"] == 30000
    assert result["long_text_items"] == 6000
    assert result["large_pack"] is True
    assert {"unique_items>5000", "target_languages>4"} <= set(result["large_pack_reasons"])


def test_normalize_large_text_mode_defaults_to_auto() -> None:
    assert normalize_large_text_mode(None) == "auto"
    assert normalize_large_text_mode("strict") == "strict"
    assert normalize_large_text_mode("off") == "off"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
cd D:\codex\localization-workflow-studio
python -m pytest backend/tests/test_large_text_productization.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.workflow.large_text'`.

- [ ] **Step 3: Implement product preflight helper**

Create:

```python
# backend/app/workflow/large_text.py
from __future__ import annotations

import json
import re
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

WORKFLOW_VERSION = "large_text_product_v1"
ALLOWED_MODES = {"auto", "strict", "off"}
CJK_RE = re.compile(r"[\u3400-\u9fff]")


def normalize_large_text_mode(value: str | None) -> str:
    mode = str(value or "auto").strip().lower()
    if mode not in ALLOWED_MODES:
        return "auto"
    return mode


def row_key(row: dict[str, Any], fallback: int) -> str:
    return str(row.get("key") or row.get("id") or row.get("para_id") or fallback)


def source_text(row: dict[str, Any]) -> str:
    return str(row.get("cn") or row.get("CN") or row.get("source") or "")


def build_large_text_preflight(
    rows: list[dict[str, Any]],
    *,
    target_languages: list[str],
    source_rows: int | None = None,
    workbook_count: int = 1,
    full_proofread: bool = False,
) -> dict[str, Any]:
    target_langs = [str(lang).strip().lower() for lang in target_languages if str(lang).strip()]
    unique_keys = {row_key(row, index) for index, row in enumerate(rows, 1)}
    long_text_items = [row for row in rows if int(row.get("char_len") or len(source_text(row))) > 300]
    estimated_cells = len(unique_keys) * len(target_langs)
    reasons: list[str] = []
    if len(unique_keys) > 5000:
        reasons.append("unique_items>5000")
    if len(target_langs) > 4:
        reasons.append("target_languages>4")
    if workbook_count > 1:
        reasons.append("workbook_count>1")
    if long_text_items:
        reasons.append("long_text_items>0")
    if full_proofread:
        reasons.append("full_proofread_requested")
    recommended_shards = 1
    if reasons:
        recommended_shards = max(2, min(8, (estimated_cells // 25000) + 2))
    return {
        "workflow": WORKFLOW_VERSION,
        "unique_items": len(unique_keys),
        "source_rows": source_rows,
        "target_languages": target_langs,
        "target_language_count": len(target_langs),
        "estimated_target_cells": estimated_cells,
        "long_text_items": len(long_text_items),
        "workbook_count": workbook_count,
        "large_pack": bool(reasons),
        "large_pack_reasons": reasons,
        "recommended_translation_shards": recommended_shards,
        "recommended_deep_proofread_shards": max(recommended_shards, 4) if full_proofread else recommended_shards,
    }
```

- [ ] **Step 4: Run tests**

Run:

```powershell
python -m pytest backend/tests/test_large_text_productization.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/workflow/large_text.py backend/tests/test_large_text_productization.py
git commit -m "feat: add product large text preflight helper"
```

---

## Task 2: Cache-Lint Gate Before Workbook Apply

**Files:**
- Modify: `backend/app/workflow/large_text.py`
- Modify: `backend/app/workflow/translation.py`
- Test: `backend/tests/test_large_text_productization.py`

- [ ] **Step 1: Write failing tests for cache conversion and lint**

Append:

```python
from app.workflow.large_text import build_translation_cache_rows, cache_lint_rows


def test_cache_lint_blocks_missing_machine_token_and_number() -> None:
    workpack = [
        {"id": "a", "source": "领取 100K 奖励 {count}"},
        {"id": "b", "source": "分享 [SDT] {num}"},
    ]
    translated = [
        {"id": "a", "translation": "Claim rewards {count}"},
        {"id": "b", "translation": "Share {num}"},
    ]

    cache_rows = build_translation_cache_rows(workpack, translated, "en")
    result = cache_lint_rows(cache_rows, target_languages=["en"])

    assert result["hard_blockers"] == 2
    assert result["hard_by_type"]["number_missing"] == 1
    assert result["hard_by_type"]["protected_token_missing"] == 1
```

Also add product parity tests for the current workflow gate behavior:

- `test_cache_lint_matches_workflow_gate_for_unit_and_word_multiplier_numbers`
  - Source examples must cover `100K`, `123.1万`, `one million`, `1 juta`, `2 millones`, and a translated value within the accepted 0.5% large-number tolerance.
- `test_cache_lint_ignores_expected_cjk_small_numbers_and_dates`
  - Source examples must cover month/date-ish values and small CJK counters that should not become hard blockers.
- `test_cache_lint_only_auto_protects_machine_like_bracket_tokens`
  - `[SDT]`, `[A_1]`, and `{count}` must be protected.
  - Translatable labels such as `[Monster]` must not be auto-protected unless explicitly listed in row protected tokens.

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m pytest backend/tests/test_large_text_productization.py::test_cache_lint_blocks_missing_machine_token_and_number -q
```

Expected: FAIL because `build_translation_cache_rows` and `cache_lint_rows` do not exist.

- [ ] **Step 3: Implement current-gate-aligned cache helpers**

Add to `backend/app/workflow/large_text.py`:

Mandatory implementation rule:

- Treat `workflow/localization/utils/large_text_multilingual_gate.py` as the source of truth.
- Prefer factoring shared pure helpers from that module if it can be done without pulling local-agent file-system assumptions into product code.
- If factoring is too invasive, port the current pure parsing and lint behavior into `backend/app/workflow/large_text.py` and add parity tests that compare representative rows against the workflow gate.
- The implementation must preserve: machine-like bracket token filtering, newline/font/placeholder token checks, CJK small-number/date filtering, Chinese unit conversion, English/Indonesian/Spanish/Portuguese word multipliers, number-word handling, and 0.5% large-number tolerance.
- The sketch below is only the product-side shape. If it conflicts with the current workflow gate implementation, the current workflow gate wins.

```python
TOKEN_RE = re.compile(r"\\n|\{[^{}\s]+\}|%[sdif]|##\d+|</?[A-Za-z][^>\s]*[^>]*>|\[[A-Za-z0-9_:/#=.,-]+\]")
NUMBER_RE = re.compile(
    r"\d+(?:[,.]\d+)?(?:\s*(?:千|万|萬|亿|億|(?i:thousand|million|billion|ribu|rb|juta|miliar|millones|millón|milhao|milhão|milhões|mil)\b)|[KkMBWw](?![A-Za-z]))%?"
    r"|\d{1,3}(?:[,\s.]\d{3})+(?:[,.]\d+)?%?"
    r"|\d+(?:[,.]\d+)?%?"
)
CJK_ALLOWED_LANGS = {"cn", "zh", "zh-cn", "ja", "jp"}


def build_translation_cache_rows(
    workpack_rows: list[dict[str, Any]],
    translated_rows: list[dict[str, Any]],
    language: str,
) -> list[dict[str, Any]]:
    by_id = {str(row.get("id")): str(row.get("translation") or "") for row in translated_rows}
    lang = language.lower()
    cache_rows: list[dict[str, Any]] = []
    for index, row in enumerate(workpack_rows, 1):
        key = row_key(row, index)
        item = dict(row)
        item["key"] = key
        item["source"] = source_text(row)
        item["translations"] = {lang: by_id.get(str(row.get("id")), "")}
        cache_rows.append(item)
    return cache_rows


def is_auto_protected_token(token: str) -> bool:
    if token.startswith("[") and token.endswith("]"):
        inner = token[1:-1]
        return bool(re.search(r"[\d_:/#=.,-]", inner) or (inner.isupper() and len(inner) <= 12))
    return True


def protected_tokens(row: dict[str, Any]) -> list[str]:
    raw_tokens = row.get("tokens") or row.get("protected_tokens") or []
    tokens: list[str] = []
    if isinstance(raw_tokens, str):
        try:
            parsed = json.loads(raw_tokens)
            raw_tokens = parsed if isinstance(parsed, list) else [raw_tokens]
        except json.JSONDecodeError:
            raw_tokens = [raw_tokens]
    if isinstance(raw_tokens, list):
        tokens.extend(str(token) for token in raw_tokens if str(token))
    tokens.extend(token for token in TOKEN_RE.findall(source_text(row)) if is_auto_protected_token(token))
    return sorted(set(tokens), key=len, reverse=True)


def parse_number_token(token: str) -> Decimal | None:
    raw = token.strip().replace(" ", "")
    if not raw:
        return None
    if raw.endswith("%"):
        raw = raw[:-1]
    suffix = ""
    if raw and raw[-1] in "KkMBWw":
        suffix = raw[-1].upper()
        raw = raw[:-1]
    elif raw.endswith(("千", "万", "萬", "亿", "億")):
        suffix = raw[-1]
        raw = raw[:-1]
    raw = raw.replace(",", "")
    try:
        multiplier = {
            "千": Decimal("1000"),
            "万": Decimal("10000"),
            "萬": Decimal("10000"),
            "亿": Decimal("100000000"),
            "億": Decimal("100000000"),
            "K": Decimal("1000"),
            "M": Decimal("1000000"),
            "B": Decimal("1000000000"),
            "W": Decimal("10000"),
        }.get(suffix, Decimal(1))
        return (Decimal(raw) * multiplier).normalize()
    except InvalidOperation:
        return None


def numeric_values(text: str) -> set[Decimal]:
    values: set[Decimal] = set()
    for token in NUMBER_RE.findall(text or ""):
        parsed = parse_number_token(token)
        if parsed is not None:
            values.add(parsed)
    return values


def numeric_value_present(value: Decimal, targets: set[Decimal]) -> bool:
    if value in targets:
        return True
    if abs(value) >= Decimal("1000"):
        return any(target and abs(target - value) / abs(value) <= Decimal("0.005") for target in targets)
    return False


def row_translation(row: dict[str, Any], language: str) -> str:
    translations = row.get("translations")
    if isinstance(translations, dict):
        return str(translations.get(language.lower()) or translations.get(language.upper()) or "")
    return str(row.get(language) or row.get(language.upper()) or "")


def add_issue(issues: list[dict[str, Any]], issue_type: str, key: str, lang: str, detail: str) -> None:
    issues.append({"severity": "hard", "type": issue_type, "key": key, "lang": lang, "detail": detail})


def cache_lint_rows(cache_rows: list[dict[str, Any]], *, target_languages: list[str]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    seen: set[str] = set()
    langs = [lang.lower() for lang in target_languages]
    for index, row in enumerate(cache_rows, 1):
        key = row_key(row, index)
        if key in seen:
            add_issue(issues, "duplicate_key", key, "", "cache contains duplicate source key")
        seen.add(key)
        src_numbers = numeric_values(source_text(row))
        tokens = protected_tokens(row)
        for lang in langs:
            target = row_translation(row, lang).strip()
            if not target:
                add_issue(issues, "empty_translation", key, lang, "target translation is empty")
                continue
            if lang not in CJK_ALLOWED_LANGS and CJK_RE.search(target):
                add_issue(issues, "cjk_residue", key, lang, "target translation still contains Chinese/Japanese ideographs")
            for token in tokens:
                if token and token not in target:
                    add_issue(issues, "protected_token_missing", key, lang, f"missing protected token {token}")
            target_numbers = numeric_values(target)
            missing_numbers = {number for number in src_numbers if not numeric_value_present(number, target_numbers)}
            if missing_numbers:
                add_issue(issues, "number_missing", key, lang, f"missing numeric value(s): {sorted(str(value) for value in missing_numbers)}")
    by_type = Counter(issue["type"] for issue in issues)
    return {
        "workflow": WORKFLOW_VERSION,
        "checked_items": len(cache_rows),
        "target_languages": langs,
        "hard_blockers": len(issues),
        "hard_by_type": dict(sorted(by_type.items())),
        "issues": issues,
        "ok_to_apply": len(issues) == 0,
    }
```

- [ ] **Step 4: Wire translation pre-apply gate**

In `backend/app/workflow/translation.py`, after `translated_rows` is written to `translation_response.jsonl` and before `apply_args`, add:

```python
from .large_text import (
    build_large_text_preflight,
    build_translation_cache_rows,
    cache_lint_rows,
    normalize_large_text_mode,
)
```

Add inside `translate_run` after `rows = read_jsonl(workpack_path)`:

```python
large_text_mode = normalize_large_text_mode(getattr(request, "large_text_mode", None) or metadata.get("large_text_mode"))
large_text_preflight = build_large_text_preflight(
    rows,
    target_languages=[language],
    source_rows=int(readiness.get("source_rows") or len(rows)),
    workbook_count=1,
    full_proofread=False,
)
preflight_path = work_dir / "large_text_preflight.json"
preflight_path.write_text(json.dumps(large_text_preflight, ensure_ascii=False, indent=2), encoding="utf-8")
preflight_artifact = db.add_artifact(
    project["id"],
    "Large text preflight",
    preflight_path,
    "large_text_preflight",
    run_id=run_id,
    mime="application/json",
    origin="generated",
    metadata={"mode": large_text_mode, "large_pack": large_text_preflight["large_pack"]},
)
db.update_run(run_id, metadata={**db.get_run(run_id).get("metadata", {}), "large_text": {"mode": large_text_mode, "preflight": large_text_preflight, "preflight_artifact_id": preflight_artifact["id"]}})
```

After writing `translation_response.jsonl`, add:

```python
cache_rows = build_translation_cache_rows(rows, translated_rows, language)
cache_lint = cache_lint_rows(cache_rows, target_languages=[language])
cache_lint_path = work_dir / "large_text_cache_lint.json"
cache_lint_path.write_text(json.dumps(cache_lint, ensure_ascii=False, indent=2), encoding="utf-8")
cache_artifact = db.add_artifact(
    project["id"],
    "Large text cache lint",
    cache_lint_path,
    "large_text_cache_lint",
    run_id=run_id,
    mime="application/json",
    origin="generated",
    metadata={"hard_blockers": cache_lint["hard_blockers"], "ok_to_apply": cache_lint["ok_to_apply"]},
)
should_enforce = large_text_mode == "strict" or (large_text_mode == "auto" and bool(large_text_preflight.get("large_pack")))
large_text_state = {
    "mode": large_text_mode,
    "preflight": large_text_preflight,
    "preflight_artifact_id": preflight_artifact["id"],
    "cache_lint": {
        "status": "passed" if cache_lint["ok_to_apply"] else "failed",
        "hard_blockers": cache_lint["hard_blockers"],
        "artifact_id": cache_artifact["id"],
    },
}
if large_text_mode == "off":
    large_text_state["cache_lint"] = {"status": "skipped", "reason": "large_text_mode_off", "artifact_id": cache_artifact["id"]}
elif not should_enforce:
    large_text_state["cache_lint"]["status"] = "skipped"
    large_text_state["cache_lint"]["reason"] = "not_large_pack"
if should_enforce and not cache_lint["ok_to_apply"]:
    current = db.get_run(run_id)
    db.update_run(run_id, status="failed", metadata={**current.get("metadata", {}), "large_text": large_text_state, "error": "大文本门禁未通过，未写入最终 workbook。"})
    db.add_event(run_id, f"large text cache lint failed: hard_blockers={cache_lint['hard_blockers']}", level="error")
    return {"run": db.get_run(run_id), "artifacts": [preflight_artifact, cache_artifact], "quality": None, "quality_summary": {"passed": False, "hard_errors": cache_lint["hard_blockers"]}}
db.update_run(run_id, metadata={**db.get_run(run_id).get("metadata", {}), "large_text": large_text_state})
```

- [ ] **Step 5: Add schema field**

In `backend/app/schemas.py`:

```python
class TranslateRequest(BaseModel):
    provider: str | None = None
    protocol: str | None = None
    preset: str | None = None
    batch_size: int | None = None
    confirm_api_budget: bool = False
    confirm_term_gap: bool = False
    large_text_mode: str | None = None


class MultilingualQueueRequest(BaseModel):
    input_artifact_id: str
    languages: list[str] = Field(default_factory=list)
    batch_size: int | None = None
    task_code: str | None = None
    term_artifact_id: str | None = None
    reference_artifact_ids: list[str] = Field(default_factory=list)
    confirm_api_budget: bool = False
    confirm_term_gap: bool = False
    large_text_mode: str | None = None
```

In `backend/app/workflow/multilingual.py`, include `large_text_mode` in child metadata and in `TranslateRequest(...)`:

```python
"large_text_mode": payload.large_text_mode or "auto",
```

```python
request = TranslateRequest(
    batch_size=payload.batch_size,
    confirm_api_budget=payload.confirm_api_budget,
    confirm_term_gap=payload.confirm_term_gap,
    large_text_mode=payload.large_text_mode or "auto",
)
```

- [ ] **Step 6: Run focused backend tests**

Run:

```powershell
python -m pytest backend/tests/test_large_text_productization.py backend/tests/test_long_text_orchestration.py backend/tests/test_multilingual_orchestration.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add backend/app/workflow/large_text.py backend/app/workflow/translation.py backend/app/workflow/multilingual.py backend/app/schemas.py backend/tests/test_large_text_productization.py
git commit -m "feat: enforce large text cache gate in translation runs"
```

---

## Task 3: Multilingual Status Includes Large-Text State

**Files:**
- Modify: `backend/app/workflow/multilingual.py`
- Modify: `frontend/src/types.ts`
- Test: `backend/tests/test_multilingual_orchestration.py`

- [ ] **Step 1: Write failing backend test**

Add to `backend/tests/test_multilingual_orchestration.py`:

```python
def test_multilingual_status_exposes_large_text_metadata(tmp_path: Path) -> None:
    project = db.insert_project("multi large text", "QA", "")
    artifact = _add_language_table(project["id"], tmp_path / "source.xlsx", ["EN"])
    run = db.insert_run(
        project["id"],
        "translation",
        "en",
        metadata={
            "input_artifact_id": artifact["id"],
            "task_origin": "translation_run",
            "large_text": {
                "mode": "auto",
                "preflight": {"large_pack": True, "unique_items": 6001, "estimated_target_cells": 6001},
                "cache_lint": {"status": "passed", "hard_blockers": 0},
            },
        },
    )

    with TestClient(app) as client:
        response = client.get(
            f"/api/projects/{project['id']}/multilingual/status",
            params={"input_artifact_id": artifact["id"], "languages": "en"},
        )

    assert response.status_code == 200
    item = response.json()["languages"][0]
    assert item["translation_run_id"] == run["id"]
    assert item["large_text"]["preflight"]["large_pack"] is True
    assert item["large_text"]["cache_lint"]["status"] == "passed"
```

- [ ] **Step 2: Implement status passthrough**

In `_language_status`:

```python
large_text = ((run_for_status or {}).get("metadata") or {}).get("large_text") or {}
```

Add to returned dict:

```python
"large_text": large_text,
```

- [ ] **Step 3: Add frontend types**

In `frontend/src/types.ts`:

```ts
export type LargeTextPreflight = {
  workflow?: string
  unique_items?: number
  source_rows?: number
  target_languages?: string[]
  target_language_count?: number
  estimated_target_cells?: number
  long_text_items?: number
  workbook_count?: number
  large_pack?: boolean
  large_pack_reasons?: string[]
  recommended_translation_shards?: number
}

export type LargeTextGateStatus = {
  status?: 'passed' | 'failed' | 'skipped' | 'waived' | string
  hard_blockers?: number
  reason?: string
  artifact_id?: string
}

export type LargeTextRunState = {
  mode?: 'auto' | 'strict' | 'off' | string
  preflight?: LargeTextPreflight
  preflight_artifact_id?: string
  cache_lint?: LargeTextGateStatus
  readback_gate?: LargeTextGateStatus
  retro_artifact_id?: string
}
```

Add to `MultilingualQueueLanguage`:

```ts
large_text?: LargeTextRunState
```

- [ ] **Step 4: Run tests**

Run:

```powershell
python -m pytest backend/tests/test_multilingual_orchestration.py::test_multilingual_status_exposes_large_text_metadata -q
npm --prefix frontend run build
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/workflow/multilingual.py backend/tests/test_multilingual_orchestration.py frontend/src/types.ts
git commit -m "feat: surface large text status in multilingual queues"
```

---

## Task 4: Delivery Readback Gate

**Files:**
- Modify: `backend/app/workflow/large_text.py`
- Modify: `backend/app/workflow/delivery.py`
- Test: `backend/tests/test_multilingual_delivery.py`
- Test: `backend/tests/test_large_text_productization.py`

- [ ] **Step 1: Write failing readback helper test**

Add:

```python
from openpyxl import Workbook
from app.workflow.large_text import readback_gate_files


def test_readback_gate_files_blocks_blank_target_cells(tmp_path: Path) -> None:
    workbook = tmp_path / "final.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Language"
    ws.append(["ID", "CN", "EN"])
    ws.append([1, "开始游戏", "Start Game"])
    ws.append([2, "领取奖励", ""])
    wb.save(workbook)
    wb.close()

    result = readback_gate_files([workbook], target_languages=["en"])

    assert result["readback_verified"] is False
    assert result["hard_blockers"] == 1
    assert result["issues"][0]["type"] == "blank_target_cell"
```

- [ ] **Step 2: Implement file-scoped readback gate**

Add to `backend/app/workflow/large_text.py`:

```python
from openpyxl import load_workbook

SOURCE_HEADERS = {"CN", "ZH", "SOURCE", "TEXT", "原文"}


def readback_gate_files(paths: list[Path], *, target_languages: list[str]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    targets = [lang.upper() for lang in target_languages]
    for path in paths:
        files.append({"name": path.name, "bytes": path.stat().st_size if path.exists() else 0})
        if not path.exists():
            add_issue(issues, "delivery_file_missing", path.name, "", "delivery file does not exist")
            continue
        if path.suffix.lower() not in {".xlsx", ".xlsm"}:
            continue
        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            for sheet in workbook.worksheets:
                first_row = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True), ())
                headers = [str(value).strip().upper() if value is not None else "" for value in first_row]
                header_set = {header for header in headers if header}
                if not header_set.intersection(set(targets)) and not header_set.intersection(SOURCE_HEADERS):
                    continue
                col_by_lang = {header: index for index, header in enumerate(headers) if header}
                for lang in targets:
                    col_index = col_by_lang.get(lang)
                    if col_index is None:
                        add_issue(issues, "target_column_missing", f"{path.name}:{sheet.title}", lang, "target language column is missing")
                        continue
                    for row_index, row_values in enumerate(sheet.iter_rows(min_row=2, values_only=True), 2):
                        value = row_values[col_index] if col_index < len(row_values) else None
                        if value is None or str(value).strip() == "":
                            add_issue(issues, "blank_target_cell", f"{path.name}:{sheet.title}!R{row_index}C{col_index + 1}", lang, "target cell is blank")
        finally:
            workbook.close()
    by_type = Counter(issue["type"] for issue in issues)
    return {
        "workflow": WORKFLOW_VERSION,
        "files": files,
        "target_languages": target_languages,
        "hard_blockers": len(issues),
        "hard_by_type": dict(sorted(by_type.items())),
        "issues": issues,
        "readback_verified": len(issues) == 0,
    }
```

- [ ] **Step 3: Wire single delivery readback**

In `backend/app/workflow/delivery.py`, import:

```python
from .large_text import readback_gate_files
```

In `build_delivery_package`, after final/changing files are copied and before return:

```python
readback = readback_gate_files([final_path], target_languages=[run.get("language") or "en"])
readback_path = output_dir / f"{final_path.stem}_readback_gate.json"
readback_path.write_text(json.dumps(readback, ensure_ascii=False, indent=2), encoding="utf-8")
readback_artifact = db.add_artifact(
    project_id,
    f"{project['name']} readback gate",
    readback_path,
    "delivery_readback_gate",
    run_id=run["id"],
    mime="application/json",
    origin="generated",
    metadata={"hard_blockers": readback["hard_blockers"], "readback_verified": readback["readback_verified"]},
)
if not readback["readback_verified"]:
    raise ValueError(f"交付读回门禁未通过：{readback['hard_blockers']} 个硬错误")
summary["files"]["readback_gate"] = _artifact_delivery_file("readback_gate", readback_artifact)
```

Add `import json` at top.

- [ ] **Step 4: Wire merged delivery readback**

In `build_merged_delivery_package`, after `summary_artifact` and before `final_artifact` return metadata:

```python
readback = readback_gate_files(output_path and [output_path] or [], target_languages=selected_languages)
readback_path = output_dir / f"{output_path.stem}_readback_gate.json"
readback_path.write_text(json.dumps(readback, ensure_ascii=False, indent=2), encoding="utf-8")
readback_artifact = db.add_artifact(
    project_id,
    f"{project['name']} ALL readback gate",
    readback_path,
    "delivery_readback_gate",
    mime="application/json",
    origin="generated",
    metadata={"hard_blockers": readback["hard_blockers"], "readback_verified": readback["readback_verified"]},
)
if not readback["readback_verified"]:
    raise ValueError(f"合并交付读回门禁未通过：{readback['hard_blockers']} 个硬错误")
```

Add to merged final artifact metadata:

```python
"readback_gate_artifact_id": readback_artifact["id"],
"readback_gate": {"status": "passed", "hard_blockers": 0},
```

Add to returned files:

```python
files = [
    _artifact_delivery_file("merged_final", final_artifact),
    _artifact_delivery_file("qa_summary", summary_artifact),
    _artifact_delivery_file("readback_gate", readback_artifact),
]
```

- [ ] **Step 5: Run tests**

Run:

```powershell
python -m pytest backend/tests/test_large_text_productization.py backend/tests/test_multilingual_delivery.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/workflow/large_text.py backend/app/workflow/delivery.py backend/tests/test_large_text_productization.py backend/tests/test_multilingual_delivery.py
git commit -m "feat: add delivery readback gate"
```

---

## Task 5: Retro Artifact and Long-Task Review

**Files:**
- Modify: `backend/app/workflow/large_text.py`
- Modify: `backend/app/workflow/translation.py`
- Modify: `backend/app/workflow/delivery.py`
- Test: `backend/tests/test_large_text_productization.py`

- [ ] **Step 1: Write retro rendering test**

Add:

```python
from app.workflow.large_text import render_large_text_retro


def test_render_large_text_retro_marks_skipped_and_long_task() -> None:
    report = render_large_text_retro(
        {
            "task": "large pack",
            "translation_progress": {"elapsed_seconds": 3900, "total_rows": 6000, "completed_rows": 6000},
            "preflight": {"large_pack": True, "unique_items": 6000, "estimated_target_cells": 30000},
            "cache_lint": {"status": "skipped", "reason": "not_large_pack", "hard_blockers": 0},
            "readback_gate": {"status": "passed", "hard_blockers": 0},
        }
    )

    assert "长任务复盘触发" in report
    assert "status=triggered" in report
    assert "cache-lint: status=skipped, reason=not_large_pack" in report
```

- [ ] **Step 2: Implement markdown renderer**

Add:

```python
LONG_TASK_REVIEW_SECONDS = 3600


def _gate_line(label: str, gate: dict[str, Any]) -> str:
    status = str(gate.get("status") or ("passed" if int(gate.get("hard_blockers") or 0) == 0 else "failed"))
    reason = f", reason={gate.get('reason')}" if status in {"skipped", "waived"} and gate.get("reason") else ""
    return f"- {label}: status={status}, hard={gate.get('hard_blockers', 'n/a')}{reason}"


def render_large_text_retro(metrics: dict[str, Any]) -> str:
    progress = metrics.get("translation_progress") or {}
    elapsed = int(progress.get("elapsed_seconds") or 0)
    long_status = "triggered" if elapsed >= LONG_TASK_REVIEW_SECONDS else "not_triggered"
    return f"""# 大文本处理复盘

## 执行规模

- unique_items: {(metrics.get("preflight") or {}).get("unique_items", "n/a")}
- estimated_target_cells: {(metrics.get("preflight") or {}).get("estimated_target_cells", "n/a")}
- total_rows: {progress.get("total_rows", "n/a")}
- completed_rows: {progress.get("completed_rows", "n/a")}

## 执行门禁结果

{_gate_line("cache-lint", metrics.get("cache_lint") or {})}
{_gate_line("readback-gate", metrics.get("readback_gate") or {})}

## 长任务复盘触发

- status={long_status}, threshold=3600s, elapsed={elapsed}s
- review_focus=判断耗时是否只是任务规模导致；检查失败/重试/跳过门禁/意外修复；重复出现或可机器检查的问题沉淀为测试、gate 或文档，偶发问题只记录。
"""
```

- [ ] **Step 3: Generate retro artifact at translation terminal**

In `translation.py`, before final `db.update_run(... status=status ...)`, build a report from `final_metadata.get("large_text")`, `final_progress`, and QA summary:

```python
from .large_text import render_large_text_retro
```

```python
large_text_state = final_metadata.get("large_text") if isinstance(final_metadata.get("large_text"), dict) else {}
retro_text = render_large_text_retro(
    {
        "task": project["name"],
        "translation_progress": final_progress if isinstance(final_progress, dict) else {},
        "preflight": large_text_state.get("preflight") or {},
        "cache_lint": large_text_state.get("cache_lint") or {"status": "skipped", "reason": "not provided"},
        "readback_gate": large_text_state.get("readback_gate") or {"status": "skipped", "reason": "delivery not generated yet"},
    }
)
retro_path = work_dir / "large_text_retro.md"
retro_path.write_text(retro_text, encoding="utf-8")
retro_artifact = db.add_artifact(project["id"], "Large text retro", retro_path, "large_text_retro", run_id=run_id, mime="text/markdown", origin="generated")
large_text_state["retro_artifact_id"] = retro_artifact["id"]
```

Add `retro_artifact` to `artifacts`.

- [ ] **Step 4: Update retro after delivery readback**

In `delivery.py`, if a run has `metadata.large_text`, write a delivery-time retro file with `readback_gate` included and add it as artifact kind `large_text_retro`.

```python
large_text_state = dict((run.get("metadata") or {}).get("large_text") or {})
if large_text_state:
    large_text_state["readback_gate"] = {"status": "passed", "hard_blockers": readback["hard_blockers"], "artifact_id": readback_artifact["id"]}
    current = db.get_run(run["id"])
    db.update_run(run["id"], metadata={**current.get("metadata", {}), "large_text": large_text_state})
```

- [ ] **Step 5: Run tests and commit**

```powershell
python -m pytest backend/tests/test_large_text_productization.py backend/tests/test_workflow_e2e.py -q
git add backend/app/workflow/large_text.py backend/app/workflow/translation.py backend/app/workflow/delivery.py backend/tests/test_large_text_productization.py
git commit -m "feat: write large text retro artifacts"
```

---

## Task 6: Frontend Large-Text Panels

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/main.tsx`
- Modify: `frontend/src/components/translationWizard/TranslationWizard.tsx`
- Modify: `frontend/src/styles.css`
- Test: `frontend/e2e/studio-ui-flow.spec.ts`

- [ ] **Step 1: Pass large text mode from frontend**

In `main.tsx`, add `large_text_mode: 'auto'` to translation request bodies:

```ts
body: JSON.stringify({
  provider: settings.provider,
  protocol: settings.protocol,
  preset: settings.preset,
  batch_size: selectedBatchSize,
  confirm_api_budget: confirmBudget,
  confirm_term_gap: confirmedTermGap,
  large_text_mode: 'auto'
})
```

In multilingual queue start:

```ts
body: JSON.stringify({
  input_artifact_id: sourceArtifact.id,
  languages,
  batch_size: selectedBatchSize,
  task_code: taskCode,
  term_artifact_id: termArtifact?.id || null,
  confirm_api_budget: false,
  confirm_term_gap: confirmedTermGap,
  large_text_mode: 'auto'
})
```

- [ ] **Step 2: Add Step 7 product panel**

In `TranslationWizard.tsx`, add:

```tsx
function LargeTextPanel({ run, readiness, selectedLanguageCount }: { run?: Run | null; readiness?: TranslationReadiness | null; selectedLanguageCount: number }) {
  const state = run?.metadata?.large_text as LargeTextRunState | undefined
  const preflight = state?.preflight
  const estimatedCells = readiness ? readiness.source_rows * Math.max(1, selectedLanguageCount) : preflight?.estimated_target_cells
  const large = Boolean(preflight?.large_pack || (estimatedCells && estimatedCells > 25000) || (readiness && readiness.source_rows > 5000) || selectedLanguageCount > 4)
  const cache = state?.cache_lint
  return (
    <div className={`large-text-panel ${large ? 'large' : ''}`} data-testid="large-text-panel">
      <div className="readiness-head">
        <strong>大文本处理</strong>
        <span>{large ? '已启用自动门禁' : '普通规模'}</span>
      </div>
      <p>{preflight ? `${preflight.unique_items || 0} 条唯一文本 / ${preflight.estimated_target_cells || 0} 个目标单元 / 长文本 ${preflight.long_text_items || 0} 条` : `预计 ${estimatedCells || '-'} 个目标单元`}</p>
      {cache ? <p>cache-lint: {cache.status || '-'}{typeof cache.hard_blockers === 'number' ? ` / hard ${cache.hard_blockers}` : ''}</p> : <p>启动后会记录 preflight 和 cache-lint。</p>}
    </div>
  )
}
```

Place it below the existing `translation-readiness-box`:

```tsx
<LargeTextPanel run={currentTranslationRun} readiness={readiness} selectedLanguageCount={selectedLanguages.length} />
```

- [ ] **Step 3: Show gate artifacts in RunDetail**

Extend `inputItems`:

```ts
['大文本预检', (run.metadata?.large_text as LargeTextRunState | undefined)?.preflight_artifact_id],
['大文本复盘', (run.metadata?.large_text as LargeTextRunState | undefined)?.retro_artifact_id],
```

Extend `visibleArtifacts` filter to include:

```ts
['large_text_preflight', 'large_text_cache_lint', 'delivery_readback_gate', 'large_text_retro']
```

- [ ] **Step 4: Add CSS**

```css
.large-text-panel {
  border: 1px solid rgba(255,255,255,.08);
  border-radius: 8px;
  padding: 12px;
  background: rgba(255,255,255,.03);
}
.large-text-panel.large {
  border-color: rgba(245,158,11,.35);
  background: rgba(245,158,11,.08);
}
.large-text-panel p {
  margin: 6px 0 0;
  color: #a1a1aa;
  font-size: 12px;
}
```

- [ ] **Step 5: Add E2E smoke**

In `frontend/e2e/studio-ui-flow.spec.ts`, add a small UI assertion after entering Step 7:

```ts
await expect(page.getByTestId('large-text-panel')).toBeVisible()
await expect(page.getByTestId('large-text-panel')).toContainText(/大文本处理/)
```

- [ ] **Step 6: Run frontend checks**

```powershell
npm --prefix frontend run build
npm --prefix frontend run e2e -- --workers=1
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add frontend/src/types.ts frontend/src/main.tsx frontend/src/components/translationWizard/TranslationWizard.tsx frontend/src/styles.css frontend/e2e/studio-ui-flow.spec.ts
git commit -m "feat: show large text gates in translation wizard"
```

---

## Task 7: Documentation and Validation

**Files:**
- Modify: `docs/LARGE_TEXT_MULTILINGUAL_WORKFLOW.md`
- Modify: `docs/FEATURE_MATRIX.md`
- Modify: `docs/STABILITY_TEST_LIST.md`

- [ ] **Step 1: Update product boundary docs**

Append to `docs/LARGE_TEXT_MULTILINGUAL_WORKFLOW.md`:

```markdown
## 产品工作台内置能力

- 工作台翻译 run 会在 workpack 生成后写入 `large_text_preflight` artifact，并在 run metadata 的 `large_text.preflight` 暴露规模、长文本数量、目标语言数量和推荐分片。
- 当 `large_text_mode=auto` 且检测为 large pack 时，工作台在写入最终 workbook 前执行 `large_text_cache_lint`。未通过时保留批次和 AI 响应，但不写入最终 workbook。
- 交付生成会执行 `delivery_readback_gate`，读回本次生成的最终文件，阻断目标列缺失和空目标单元格。
- 工作台生成的 `large_text_retro` 只记录 host/path/model/provider/protocol 和门禁结果，不写入 `api_key`。
```

- [ ] **Step 2: Update feature matrix**

In `docs/FEATURE_MATRIX.md`, add one row:

```markdown
| 大文本产品化门禁 | 大语言表/多语言包在 Step 7 显示 preflight，翻译写入前跑 cache-lint，交付时跑 readback gate，并生成 retro artifact | `backend/tests/test_large_text_productization.py`, `backend/tests/test_long_text_orchestration.py`, `frontend/e2e/studio-ui-flow.spec.ts` |
```

- [ ] **Step 3: Run full validation**

Run:

```powershell
cd D:\codex\localization-workflow-studio
python -m ruff check backend/app backend/tests scripts --select E9,F
python -m compileall -q backend workflow scripts
python -m pytest workflow/localization/tests/test_large_text_multilingual_gate.py workflow/localization/tests/test_large_text_multilingual_retro.py workflow/localization/tests/test_large_text_multilingual_runner.py -q
python -m pytest backend/tests/test_large_text_productization.py backend/tests/test_long_text_orchestration.py backend/tests/test_multilingual_orchestration.py backend/tests/test_multilingual_delivery.py -q
npm --prefix frontend run build
npm --prefix frontend run e2e -- --workers=1
```

If focused tests pass and this branch is ready for release confidence, run:

```powershell
python -m pytest -q
```

- [ ] **Step 4: Commit docs**

```powershell
git add docs/LARGE_TEXT_MULTILINGUAL_WORKFLOW.md docs/FEATURE_MATRIX.md docs/STABILITY_TEST_LIST.md
git commit -m "docs: document product large text gates"
```

---

## Task 8: Announcement Glossary AI Supplement Parity

This task is intentionally after the large-text gates. It improves announcement glossary quality without changing the normal translation, QA, quick-task, or delivery APIs.

**Files:**
- Inspect before editing: `workflow/glossary/scripts/extract_glossary.py`
- Inspect before editing: `workflow/glossary/tests/test_extract_glossary_workflow.py`
- Modify if needed: `backend/app/workflow/announcement.py`
- Modify if needed: `backend/app/workflow/announcement_ai.py`
- Modify if needed: `frontend/src/components/announcement/AnnouncementWorkflow.tsx`
- Test: `backend/tests/test_workflow_e2e.py`
- Test: `workflow/glossary/tests/test_extract_glossary_workflow.py`
- Test: `frontend/e2e/studio-ui-flow.spec.ts`

- [ ] **Step 1: Confirm embedded extractor parity**

Compare the standalone glossary repo and embedded workbench copy before making changes:

```powershell
git diff --no-index --stat D:\codex\glossary-extraction-workflow\scripts\extract_glossary.py D:\codex\localization-workflow-studio\workflow\glossary\scripts\extract_glossary.py
git diff --no-index --stat D:\codex\glossary-extraction-workflow\tests\test_extract_glossary_workflow.py D:\codex\localization-workflow-studio\workflow\glossary\tests\test_extract_glossary_workflow.py
```

Expected current difference: workbench has a Windows UTF-8 stdio hardening delta. Preserve that delta unless the standalone repo receives the same fix.

- [ ] **Step 2: Add product-level regression tests for announcement supplement**

Extend `backend/tests/test_workflow_e2e.py` with focused cases:

- Extract terms with `ai_supplement=True` and no provider key: packet/report artifacts are created, provider status is packet/no-provider fallback, and no unbacked terms enter the workbook.
- Uploaded AI supplement response adds an evidence-backed term to the main announcement terms workbook.
- Low-confidence, unbacked, or non-announcement terms stay report-only and do not appear in `metadata.terms`.
- Missing project-name translation is surfaced in task metadata and the AI supplement report.
- Multi-language lookup preserves selected language columns and explicit language mapping.
- Exported language tables with metadata rows and structured cells still produce clean announcement terms.

- [ ] **Step 3: Tighten backend metadata and artifact contract**

In `backend/app/workflow/announcement.py` and `backend/app/workflow/announcement_ai.py`, keep the current API shape, but make sure `metadata.ai_supplement` consistently exposes:

```json
{
  "enabled": true,
  "provider": "openai|uploaded|packet|no_evidence|provider_error",
  "provider_status": "provider_response|uploaded_response|packet_fallback|no_evidence|provider_error",
  "provider_error": "",
  "term_count": 0,
  "added_to_main": 0,
  "report_only": 0,
  "project_name_translation_missing": false,
  "packet_artifact_id": "artifact_...",
  "response_artifact_id": "artifact_...",
  "report_artifact_id": "artifact_..."
}
```

Rules:

- Packet/report/response artifacts must not include `api_key`.
- Packet must stay bounded to announcement text, matched terms, compact evidence rows, project name, and response schema.
- Main terms workbook gets only evidence-backed, translated, medium/high confidence terms.
- Report-only findings remain visible through report artifact and UI summary.

- [ ] **Step 4: Improve Step 4 UI clarity without adding a new flow**

Update the announcement terms panel only where current data already exists:

- Show deterministic term count.
- Show AI supplement provider/status.
- Show `added_to_main` and `report_only` counts separately.
- Show project-name translation warning if present.
- Keep packet/response/report artifact links secondary.
- Do not expose raw packet JSON as the primary success state.

- [ ] **Step 5: Add documentation and feature matrix rows**

Update docs to say:

- Announcement term extraction first runs deterministic lookup.
- AI supplement is optional evidence-bounded leak-checking, not free glossary generation.
- Workbench product path should not require manual Codex packet handling unless users choose upload-response mode.
- Standalone glossary repo `v0.3.0` is the behavior baseline, but workbench keeps its embedded extractor copy with Windows stdio hardening.

- [ ] **Step 6: Validation**

Run:

```powershell
python -m pytest workflow/glossary/tests/test_extract_glossary_workflow.py -q
python -m pytest backend/tests/test_workflow_e2e.py::test_announcement_task_extract_terms_accepts_ai_supplement_response backend/tests/test_workflow_e2e.py::test_announcement_task_extract_terms_calls_provider_for_ai_supplement -q
python -m ruff check backend/app backend/tests workflow/glossary/scripts workflow/glossary/tests scripts --select E9,F
npm --prefix frontend run build
npm --prefix frontend run e2e -- --workers=1
```

If Task 8 touches shared announcement flow, also run:

```powershell
python -m pytest backend/tests/test_workflow_e2e.py -q
```

---

## Rollback Plan

- If cache lint creates false blockers, revert Task 2 only. Translation returns to existing QA-only behavior; preflight helper can remain.
- If delivery readback blocks valid deliveries, revert Task 4 only. Existing single and merged delivery continue to work.
- If UI causes regressions, revert Task 6 only. Backend artifacts remain downloadable through run details/API.
- If announcement AI supplement parity creates regressions, revert Task 8 only. Existing deterministic announcement terms extraction, lookup, translation, QA, and delivery continue to work.
- If full pytest fails in unrelated old paths, keep focused tests green and record the failing unrelated test before deciding whether to broaden the fix.

## Acceptance Criteria

- Existing quick-task paste/upload translation still works.
- Existing single-language translation, QA, manual fix, model fix, archive, and delivery still work.
- Existing multilingual queue and merged delivery still work.
- For a detected large pack, run metadata contains `large_text.preflight`, `large_text.cache_lint`, and later `large_text.readback_gate`.
- Cache lint blocks missing protected machine tokens, obvious CJK residue, empty translation, and missing large numeric values before workbook apply.
- Product cache lint has parity tests for the current workflow gate's number parsing, word multipliers, CJK filtering, and machine-like bracket-token behavior.
- Skipped and waived gates persist `status`, `reason`, and `alternative_check` instead of disappearing from metadata.
- Runs over 3600 seconds include a long-task review section in the retro artifact.
- Delivery readback blocks missing target columns and blank target cells in generated final workbooks.
- UI Step 7 shows large-text processing state without requiring users to understand local CLI harnesses.
- Announcement Step 4 preserves deterministic lookup, AI supplement, upload-response, and manual-edit paths.
- Announcement AI supplement adds only evidence-backed terms to the main workbook and keeps low-confidence or unbacked terms report-only.
- Announcement AI supplement UI surfaces provider status, AI-added count, report-only count, missing language/project-name warnings, and report downloads.
- Generated artifacts do not contain `api_key`.
- Validation commands above pass.
