# Project Brief Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reusable project-audit output to full language-table scans so translators receive project context, style guidance, and a reusable translation prompt alongside the glossary.

**Architecture:** Extend `scripts/extract_glossary.py` after record loading and term extraction. The new logic remains deterministic and local: infer project signals from source entries, summarize term distribution from extracted rows, and write a Markdown brief plus an optional prompt-only text file.

**Tech Stack:** Python 3, openpyxl for existing workbook IO, argparse CLI, unittest/pytest regression tests.

---

### Task 1: Project Brief Model And Output

**Files:**
- Modify: `scripts/extract_glossary.py`
- Test: `tests/test_extract_glossary_workflow.py`

- [x] **Step 1: Write a unit test for signal inference**

```python
def test_build_project_brief_infers_project_signals_and_prompt(self):
    records = [
        MODULE.Record("1", "升级基地", "Upgrade HQ"),
        MODULE.Record("2", "攻击力提升", "ATK Up"),
        MODULE.Record("3", "公会排行榜", "Guild Ranking"),
        MODULE.Record("4", "限时礼包", "Limited Pack"),
    ]
    all_rows, glossary_rows, _high_risk, manual_rows, _final_rows = MODULE.build_term_rows(
        records=records,
        min_hit=1,
        glossary_hit_threshold=1,
        curated_rules=MODULE.new_curated_rules(),
        observations_store=MODULE.new_observation_store(),
        input_digest="brief-fixture",
    )
    markdown, prompt = MODULE.build_project_brief(
        project_name="Fixture Game",
        sheet_name="Sheet0",
        records=records,
        all_rows=all_rows,
        glossary_rows=glossary_rows,
        manual_rows=manual_rows,
    )
    self.assertIn("Fixture Game", markdown)
    self.assertIn("基地/建筑经营", markdown)
    self.assertIn("战斗/RPG养成", markdown)
    self.assertIn("翻译目标", prompt)
```

- [x] **Step 2: Run the focused test and verify it fails**

Run: `python -m pytest tests/test_extract_glossary_workflow.py::UtilityTests::test_build_project_brief_infers_project_signals_and_prompt -q`

Expected: FAIL with `AttributeError: module 'extract_glossary' has no attribute 'build_project_brief'`.

- [x] **Step 3: Implement deterministic project signal inference**

Add keyword groups for combat/RPG, base building, live ops monetization, social/guild, aircraft/shooter, survival, and narrative. Add helpers that count source-row hits and top evidence keywords.

- [x] **Step 4: Implement Markdown and prompt rendering**

Create `build_project_brief(...) -> tuple[str, str]` and `write_text_output(path, content)`. The Markdown must contain input snapshot, inferred project signals, terminology distribution, translation style guide, risk focus, and a reusable prompt block.

- [x] **Step 5: Run the focused test and verify it passes**

Run: `python -m pytest tests/test_extract_glossary_workflow.py::UtilityTests::test_build_project_brief_infers_project_signals_and_prompt -q`

Expected: PASS.

### Task 2: CLI Integration

**Files:**
- Modify: `scripts/extract_glossary.py`
- Modify: `tests/test_extract_glossary_workflow.py`

- [x] **Step 1: Write a CLI integration test**

Extend `test_cli_generates_detail_final_and_store_outputs` to pass:

```python
"--project-name", "Fixture Game",
"--project-brief-output", str(project_brief_path),
"--translation-prompt-output", str(prompt_path),
```

Assert both files exist and contain `Fixture Game` and `翻译目标`.

- [x] **Step 2: Add CLI options**

Add `--project-name`, `--project-brief-output`, `--translation-prompt-output`, and `--no-project-brief`. Default behavior writes `*_project_brief_YYYYMMDD.md` next to the input workbook.

- [x] **Step 3: Wire output generation into `main`**

After glossary rows are built and Excel outputs are written, call `build_project_brief(...)`. Write Markdown unless `--no-project-brief` is set. Write prompt-only text only when `--translation-prompt-output` is provided.

- [x] **Step 4: Run integration tests**

Run: `python -m pytest tests/test_extract_glossary_workflow.py -q`

Expected: all tests pass.

### Task 3: Documentation And Regression

**Files:**
- Modify: `README.md`
- Modify: `docs/workflow.md`

- [x] **Step 1: Document the new default output**

Add a section explaining `*_project_brief_YYYYMMDD.md`, `--project-name`, `--project-brief-output`, `--translation-prompt-output`, and `--no-project-brief`.

- [x] **Step 2: Document where it fits in the workflow**

In `docs/workflow.md`, add a project-audit step after input audit and before term extraction.

- [x] **Step 3: Run full verification**

Run:

```bash
python -m pytest
python scripts/run_glossary_harness.py fixtures/core_regression.json fixtures/observation_feedback_regression.json
```

Expected: pytest passes; harness prints `all_passed: true`.
