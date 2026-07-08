# Localization Workflow Studio Context

## Domain Terms

- Project: A local work area that owns source materials, glossary data, language tables, runs, artifacts, and delivery outputs.
- Run: A resumable execution record for translation, QA, announcement, quick task, import, or delivery work.
- Artifact: A stored file produced or uploaded during a project or run, with metadata that lets the UI display or download it safely.
- Formal Translation: A Studio translation run that produced prompt snapshot, workpack, provider response, validated workbook, and final QA report for the same run.
- Direct QA: A QA run against an uploaded translated workbook. It is QA evidence, not formal translation evidence.
- Hard Block: A QA or gate failure that prevents clean final delivery but still must offer inspection, repair, rerun, or explicit issue-delivery paths.
- Large Text Pack: A language-table workload whose rows, target-language count, workbook count, or estimated target cells require deterministic gates beyond normal QA.
- Delivery Readback: A post-generation check that reads the final output file and verifies target columns and non-empty target cells before exposing downloads.

## workflow/localization Dual Role

`workflow/localization/` is shared between the running product and agent-only
tooling. Treat the two halves with different change discipline:

- Product runtime dependencies: `scripts/run_translation_harness.py`,
  `utils/quality_harness.py`, `utils/announcement_docx_harness.py`, and
  `process_language.py`. The FastAPI backend invokes these as subprocesses
  (see `backend/app/workflow/subprocess_runner.py` and its callers). Any
  change here must be validated with the backend test suite
  (`python -m pytest backend/tests -q`), not just the local
  `workflow/localization/tests`.
- Agent-only tooling: `utils/large_text_multilingual_gate.py`,
  `utils/large_text_multilingual_runner.py`,
  `utils/large_text_multilingual_retro.py`, `cli.py`, and
  `workspace_runner.py`. These support Codex/agent-driven large-pack workflows
  outside the product's request path and are not imported or subprocessed by
  the backend at runtime.

## Architecture Terms

- Module: Anything with an Interface and an Implementation.
- Interface: Everything a caller must know to use the Module.
- Implementation: The code inside the Module.
- Depth: Leverage at the Interface.
- Seam: Where an Interface lives.
- Adapter: A concrete thing satisfying an Interface at a Seam.
- Leverage: What callers get from Depth.
- Locality: What maintainers get when change and bugs are concentrated.
