# Changelog

本文件记录术语提取工作流仓库的版本变化，方便后续维护 README、脚本能力和回归基线。

## v0.4.0 - 2026-07-08

### Changed

- Refactored the monolithic `scripts/extract_glossary.py` (about 3,900 lines) into the `glossary_extraction/` package: `constants`, `models`, `heuristics`, `experience`, `excel_io`, `announcement`, `ai_supplement`, `reporting`, and `cli` modules.
- `scripts/extract_glossary.py` is now a thin facade that re-exports every original top-level symbol, so `import extract_glossary`, `spec_from_file_location` loading, and test monkeypatching keep working unchanged.
- Consolidated the duplicated announcement/AI-supplement orchestration (workbook write, validation report, stdout summary) from three CLI branches into shared functions in `glossary_extraction/cli.py`.
- Merged back the UTF-8 stdio patch (`configure_utf8_stdio()` called at `main()` start) that previously lived only in the embedded copy inside localization-workflow-studio.
- Bumped `requirements.txt` floors to `openpyxl>=3.1.5` and `pytest>=8.4.2` to match the verified environment.

### Repository management

- This repository is now the single maintenance source for the glossary workflow. The embedded copy at `localization-workflow-studio/workflow/glossary` is a sync artifact regenerated from here (see its `SYNC.md`); do not edit it directly.

### Notes

- Behavior is unchanged: CLI arguments, output file naming, stdout format, exit codes, and `data/experience/*.json` formats are identical. Verified by 44 unit tests plus all four harness fixtures.

## v0.3.0 - 2026-07-07

### Added

- Documented the current repository version and supported workflow surface in `README.md`.
- Added this changelog and a plain `VERSION` file for lightweight repository version tracking.
- Marked the current workflow baseline as `v0.3.0`, covering:
  - full language-table glossary extraction,
  - source-only extraction,
  - project brief generation,
  - announcement-specific glossary lookup,
  - explicit multi-language announcement lookup,
  - optional AI supplement packet/file/OpenAI provider flow,
  - Codex-thread AI supplement review protocol,
  - regression harness coverage for core extraction, observation feedback, announcement lookup, and AI supplement behavior.

### Notes

- This release is a documentation and repository-management update. It does not change script behavior.

## v0.2.0 - 2026-06-09

### Added

- Added AI supplement support for announcement glossary lookup.
- Added compact AI packet generation and structured response merge behavior.
- Added Codex-thread supplement guidance so model-assisted leak checks do not require putting full language tables into model context.

## v0.1.0 - 2026-05-09

### Added

- Added the first announcement term lookup workflow.
- Established the initial glossary extraction harness baseline.
- Added delivery-ready glossary output conventions for `ID / CN / EN / EN2`.
