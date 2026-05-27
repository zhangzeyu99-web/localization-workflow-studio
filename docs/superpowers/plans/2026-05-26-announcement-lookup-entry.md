# Announcement Lookup Entry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an announcement/long-text lookup entry that retrieves project-approved terminology and QA-passed translation-memory rows for later secondary long-text translation, without translating the long text itself.

**Architecture:** This is a retrieval workflow, not a translation workflow. It reads announcement materials, matches them against language-scoped project glossary terms and QA-passed archived translations, then writes a deterministic lookup pack for the localization QA/translation workflow to consume later. Keep it separate from full glossary extraction: existing `glossary/extract` may keep `announcement_only` compatibility, but the canonical product entry should be a new announcement lookup endpoint/run kind.

**Tech Stack:** FastAPI backend, SQLite project DB, openpyxl workbook export, existing artifact/run/event model, React frontend, pytest, Playwright only if UI flow changes.

---

## Design Boundary

### What this workflow does

1. Accepts one or more announcement/long-text artifacts (`txt/md/docx/json/csv/tsv/xlsx`) or future raw text input.
2. Loads the Chinese announcement text.
3. Retrieves language-scoped, already-approved project assets:
   - `glossary_terms` where `confirmed = 1` and `language = requested language`.
   - `translation_entries` imported from QA-passed final workbooks or manually curated archive where `language = requested language` and `target` is non-empty.
4. Matches announcement text by deterministic source-side containment.
5. Outputs an audit-friendly lookup pack:
   - matched terms for terminology constraints;
   - matched translation-memory rows for reference phrasing;
   - prompt context text for the downstream long-text translator;
   - JSON manifest for migration.

### What this workflow must not do

- Must not call model translation for the announcement body.
- Must not create or mutate glossary terms automatically.
- Must not import new translation entries.
- Must not treat a raw language table as authoritative unless it has already been archived into `translation_entries` or is explicitly passed as an additional lookup corpus in a later extension.
- Must not mix languages: EN/KO/JA lookup must only use that `language`.

### Recommended product wording

Use ?????/?????? or ??????????, not ??????, because the output is lookup context, not final translation.

---

## File Map

- Modify: `D:/codex/localization-workflow-studio/backend/app/schemas.py`
  - Add request/response-facing schema for announcement lookup.
- Modify: `D:/codex/localization-workflow-studio/backend/app/main.py`
  - Add `POST /api/projects/{project_id}/announcement-lookup`.
- Modify: `D:/codex/localization-workflow-studio/backend/app/workflow.py`
  - Add lookup orchestration, text loading, matching, workbook/JSON export, run metadata.
- Modify: `D:/codex/localization-workflow-studio/backend/app/db.py`
  - Add artifact role mapping for new lookup artifacts.
- Modify: `D:/codex/localization-workflow-studio/frontend/src/main.tsx`
  - Add a small entry card/button for ???????, likely near Step 5 glossary/reference prep or the glossary tab.
- Test: `D:/codex/localization-workflow-studio/backend/tests/test_mock_e2e.py`
  - Backend integration tests for archive/glossary based lookup.
- Test: `D:/codex/localization-workflow-studio/workflow/glossary/tests/test_extract_glossary_workflow.py`
  - Keep current announcement material parsing regression; no need to expand full CLI extraction unless backend reuses it.

---

## Data Contract

### Request

```python
class AnnouncementLookupRequest(BaseModel):
    material_artifact_ids: list[str] = Field(default_factory=list)
    text: str = ""
    language: str = "en"
    min_term_length: int = 2
    min_translation_length: int = 4
    max_terms: int = 300
    max_translation_rows: int = 300
    include_glossary: bool = True
    include_translation_archive: bool = True
```

Validation rules:
- `language` must be one of `en/ko/ja`.
- At least one of `material_artifact_ids` or `text` must be non-empty.
- `min_term_length >= 2`, `min_translation_length >= 2`.
- Hard cap outputs to avoid giant prompt packs: `max_terms <= 1000`, `max_translation_rows <= 1000`.

### Output artifact kinds

- `announcement_lookup_workbook` role `reference_pack`
- `announcement_lookup_manifest` role `reference_pack`
- `announcement_lookup_prompt_context` role `reference_pack`

If keeping artifact roles minimal in v1, map all three to `glossary_source` or `run_snapshot` only if the UI cannot yet filter `reference_pack`. Recommended: add `reference_pack` because these are not glossary sources to import directly.

### Workbook sheets

1. `Overview`
   - project, language, material count, text length, matched term count, matched TM count, generated_at.
2. `MatchedTerms`
   - `CN`, target header (`EN/KO/JA`), alt header, category, note, first_position, hit_count, term_id.
3. `MatchedTranslations`
   - `ID`, `CN`, target header, alt header, source_type, sheet, row_number, first_position, hit_count, entry_id.
4. `PromptContext`
   - one-column rows with downstream prompt-ready sections.

### JSON manifest

```json
{
  "project_id": "...",
  "language": "en",
  "materials": ["artifact_id"],
  "text_fingerprint": "sha256:...",
  "terms": [{"source":"??","target":"Trial Realm","first_position":6}],
  "translations": [{"entry_key":"T1","source":"??????","target":"New Trial Realm gameplay","first_position":0}],
  "limits": {"max_terms":300,"max_translation_rows":300}
}
```

---

## Matching Policy

### Normalization

- Collapse whitespace.
- Keep Chinese punctuation and variables unchanged.
- Do not lowercase source Chinese for matching; do casefold only for non-CJK fallback comparisons if later needed.
- Preserve the original source text in exports.

### Term matching

- Source: `db.list_glossary_terms(project_id, language=language)`.
- Candidate if `len(source) >= min_term_length` and target or alt exists.
- Match by `source in announcement_text`.
- Sort by first position, then longer source first, then source text.
- Suppress overlapping source terms within `MatchedTerms` only when they start at same position or fully overlap; prefer longer term.
- Keep term matching independent from TM matching; do not drop a glossary term just because a longer archived sentence matched.

### Translation-memory matching

- Source: `db.list_translation_entries(project_id, language=language)`.
- Candidate if `len(source) >= min_translation_length` and target exists.
- Match by `source in announcement_text`.
- Sort by first position, then longer source first, then entry_key.
- Suppress overlapping TM rows so a long approved sentence beats its shorter substrings.
- Rank source_type priority when positions/length tie: `qa_passed > manual > imported > generated > unknown`.

### Why exact retrieval first

Do not add fuzzy/semantic retrieval in v1. Fuzzy matching can introduce wrong references into long-text translation. If later needed, add a separate `semantic_suggestions` section clearly marked non-authoritative.

---

## Task 1: Backend Tests for Archive-Based Lookup

**Files:**
- Modify: `D:/codex/localization-workflow-studio/backend/tests/test_mock_e2e.py`

- [ ] **Step 1: Write failing test for glossary + QA archive retrieval**

Add this test near existing glossary/archive tests:

```python
def test_announcement_lookup_uses_glossary_and_qa_passed_archive(tmp_path: Path) -> None:
    notice = tmp_path / "notice.txt"
    notice.write_text("???????????????????", encoding="utf-8")

    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "Lookup Project", "type": "QA"}).json()
        client.post(
            f"/api/projects/{project['id']}/glossary",
            json={"source": "??", "target": "Trial Realm", "language": "en", "confirmed": True},
        )
        client.post(
            f"/api/projects/{project['id']}/translations",
            json={
                "entry_key": "T1",
                "source": "??????",
                "target": "New Trial Realm gameplay",
                "language": "en",
                "source_type": "qa_passed",
            },
        )
        client.post(
            f"/api/projects/{project['id']}/translations",
            json={
                "entry_key": "T2",
                "source": "??",
                "target": "Shop",
                "language": "en",
                "source_type": "qa_passed",
            },
        )
        with notice.open("rb") as fh:
            material = client.post(
                f"/api/projects/{project['id']}/files?kind=asset",
                files={"file": ("notice.txt", fh, "text/plain")},
            ).json()

        response = client.post(
            f"/api/projects/{project['id']}/announcement-lookup",
            json={"material_artifact_ids": [material["id"]], "language": "en"},
        )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["run"]["kind"] == "announcement_lookup"
        assert payload["summary"]["matched_terms"] == 1
        assert payload["summary"]["matched_translations"] == 1
        artifacts = {artifact["kind"]: artifact for artifact in payload["artifacts"]}
        assert "announcement_lookup_workbook" in artifacts

        wb = load_workbook(Path(artifacts["announcement_lookup_workbook"]["path"]), read_only=True, data_only=True)
        try:
            term_rows = list(wb["MatchedTerms"].iter_rows(values_only=True))
            tm_rows = list(wb["MatchedTranslations"].iter_rows(values_only=True))
        finally:
            wb.close()
        assert term_rows[1][0] == "??"
        assert term_rows[1][1] == "Trial Realm"
        assert tm_rows[1][0] == "T1"
        assert tm_rows[1][1] == "??????"
        assert tm_rows[1][2] == "New Trial Realm gameplay"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m pytest -q backend/tests/test_mock_e2e.py::test_announcement_lookup_uses_glossary_and_qa_passed_archive
```

Expected: `404 Not Found` or route missing for `/announcement-lookup`.

---

## Task 2: Schema and Endpoint

**Files:**
- Modify: `D:/codex/localization-workflow-studio/backend/app/schemas.py`
- Modify: `D:/codex/localization-workflow-studio/backend/app/main.py`

- [ ] **Step 1: Add schema**

Add to `schemas.py`:

```python
class AnnouncementLookupRequest(BaseModel):
    material_artifact_ids: list[str] = Field(default_factory=list)
    text: str = ""
    language: str = "en"
    min_term_length: int = 2
    min_translation_length: int = 4
    max_terms: int = 300
    max_translation_rows: int = 300
    include_glossary: bool = True
    include_translation_archive: bool = True
```

- [ ] **Step 2: Add route**

Import `AnnouncementLookupRequest` and `run_announcement_lookup`, then add:

```python
@app.post("/api/projects/{project_id}/announcement-lookup")
def announcement_lookup(project_id: str, payload: AnnouncementLookupRequest) -> dict[str, Any]:
    try:
        payload.language = _query_language(payload.language) or "en"
        return run_announcement_lookup(project_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project or artifact not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
```

- [ ] **Step 3: Run failing test again**

Expected: route exists, but fails with `NameError` or missing `run_announcement_lookup`.

---

## Task 3: Backend Lookup Implementation

**Files:**
- Modify: `D:/codex/localization-workflow-studio/backend/app/workflow.py`
- Modify: `D:/codex/localization-workflow-studio/backend/app/db.py`

- [ ] **Step 1: Add artifact roles**

In `ARTIFACT_ROLE_BY_KIND`, add:

```python
"announcement_lookup_workbook": "reference_pack",
"announcement_lookup_manifest": "reference_pack",
"announcement_lookup_prompt_context": "reference_pack",
```

- [ ] **Step 2: Add text loading helpers**

Implement small backend-local helpers. Reuse existing workbook/docx parsing style; do not shell out to the glossary CLI for this workflow.

```python
def _load_lookup_material_text(material_artifact_ids: list[str], inline_text: str = "") -> tuple[str, list[dict[str, Any]]]:
    chunks = [str(inline_text or "").strip()] if str(inline_text or "").strip() else []
    materials = []
    for artifact_id in material_artifact_ids:
        artifact = db.get_artifact(artifact_id)
        path = Path(artifact["path"])
        text = _read_lookup_material_path(path)
        if text.strip():
            chunks.append(text)
        materials.append({"id": artifact_id, "label": artifact.get("label", ""), "path": str(path), "chars": len(text)})
    text = re.sub(r"\s+", " ", " ".join(chunks)).strip()
    return text, materials
```

Implement `_read_lookup_material_path(path)` with support for `.txt/.md/.json/.csv/.tsv/.xlsx/.docx`, matching current glossary script behavior.

- [ ] **Step 3: Add matching helpers**

```python
def _find_source_matches(text: str, rows: list[dict[str, Any]], source_key: str, min_length: int, limit: int) -> list[dict[str, Any]]:
    candidates = []
    for row in rows:
        source = str(row.get(source_key) or row.get("source") or "").strip()
        if len(source) < min_length:
            continue
        positions = [match.start() for match in re.finditer(re.escape(source), text)]
        if not positions:
            continue
        hit = dict(row)
        hit["first_position"] = min(positions)
        hit["hit_count"] = len(positions)
        candidates.append(hit)
    candidates.sort(key=lambda item: (int(item["first_position"]), -len(str(item.get(source_key) or item.get("source") or "")), str(item.get("entry_key") or item.get("id") or "")))
    return _suppress_overlapping_matches(candidates, source_key=source_key)[:limit]
```

For glossary, call with source key `source`. For translation archive, call with source key `source` but apply source_type priority in tie-break if needed.

- [ ] **Step 4: Add workbook/prompt/manifest writers**

Create:

```python
def _write_announcement_lookup_workbook(path: Path, project: dict[str, Any], language: str, materials: list[dict[str, Any]], text: str, terms: list[dict[str, Any]], translations: list[dict[str, Any]]) -> None:
    ...
```

Required sheets: `Overview`, `MatchedTerms`, `MatchedTranslations`, `PromptContext`.

- [ ] **Step 5: Add orchestration**

```python
def run_announcement_lookup(project_id: str, request: Any) -> dict[str, Any]:
    project = db.get_project(project_id)
    language = require_supported_language(getattr(request, "language", "en") or "en")
    material_ids = list(getattr(request, "material_artifact_ids", []) or [])
    inline_text = str(getattr(request, "text", "") or "")
    if not material_ids and not inline_text.strip():
        raise ValueError("announcement lookup requires material_artifact_ids or text")

    run = db.insert_run(project_id, kind="announcement_lookup", language=language, metadata={"material_artifact_ids": material_ids})
    db.update_run(run["id"], status="running")
    output_dir = run_dir(run["id"]) / "announcement_lookup"
    output_dir.mkdir(parents=True, exist_ok=True)

    text, materials = _load_lookup_material_text(material_ids, inline_text)
    if not text:
        raise ValueError("announcement lookup text is empty")

    terms = _find_source_matches(
        text,
        db.list_glossary_terms(project_id, language=language) if getattr(request, "include_glossary", True) else [],
        source_key="source",
        min_length=max(2, int(getattr(request, "min_term_length", 2) or 2)),
        limit=max(1, min(1000, int(getattr(request, "max_terms", 300) or 300))),
    )
    translations = _find_source_matches(
        text,
        db.list_translation_entries(project_id, language=language) if getattr(request, "include_translation_archive", True) else [],
        source_key="source",
        min_length=max(2, int(getattr(request, "min_translation_length", 4) or 4)),
        limit=max(1, min(1000, int(getattr(request, "max_translation_rows", 300) or 300))),
    )

    workbook_path = output_dir / "announcement_lookup_pack.xlsx"
    manifest_path = output_dir / "announcement_lookup_manifest.json"
    prompt_path = output_dir / "announcement_lookup_prompt_context.txt"
    _write_announcement_lookup_workbook(workbook_path, project, language, materials, text, terms, translations)
    manifest = _announcement_lookup_manifest(project_id, language, materials, text, terms, translations)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    prompt_path.write_text(_announcement_lookup_prompt_context(language, terms, translations), encoding="utf-8")

    artifacts = [
        db.add_artifact(project_id, "Announcement lookup workbook", workbook_path, "announcement_lookup_workbook", run_id=run["id"]),
        db.add_artifact(project_id, "Announcement lookup manifest", manifest_path, "announcement_lookup_manifest", run_id=run["id"], mime="application/json"),
        db.add_artifact(project_id, "Announcement lookup prompt context", prompt_path, "announcement_lookup_prompt_context", run_id=run["id"], mime="text/plain"),
    ]
    summary = {"matched_terms": len(terms), "matched_translations": len(translations), "text_chars": len(text)}
    db.update_run(run["id"], status="passed", metadata={"summary": summary, "materials": materials})
    return {"run": db.get_run(run["id"]), "artifacts": artifacts, "summary": summary, "manifest": manifest}
```

- [ ] **Step 6: Run test**

Run:

```powershell
python -m pytest -q backend/tests/test_mock_e2e.py::test_announcement_lookup_uses_glossary_and_qa_passed_archive
```

Expected: PASS.

---

## Task 4: Language Scoping and No-Mutation Tests

**Files:**
- Modify: `D:/codex/localization-workflow-studio/backend/tests/test_mock_e2e.py`

- [ ] **Step 1: Add KO/EN isolation test**

```python
def test_announcement_lookup_is_language_scoped_and_does_not_mutate_terms(tmp_path: Path) -> None:
    notice = tmp_path / "notice.txt"
    notice.write_text("?????????", encoding="utf-8")
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "Scoped Lookup", "type": "QA"}).json()
        client.post(f"/api/projects/{project['id']}/glossary", json={"source":"??","target":"Warplane","language":"en"})
        client.post(f"/api/projects/{project['id']}/glossary", json={"source":"??","target":"???","language":"ko"})
        with notice.open("rb") as fh:
            material = client.post(f"/api/projects/{project['id']}/files?kind=asset", files={"file": ("notice.txt", fh, "text/plain")}).json()

        before = client.get(f"/api/projects/{project['id']}/glossary?language=ko").json()
        response = client.post(f"/api/projects/{project['id']}/announcement-lookup", json={"material_artifact_ids":[material["id"]], "language":"ko"})
        assert response.status_code == 200, response.text
        after = client.get(f"/api/projects/{project['id']}/glossary?language=ko").json()
        assert before == after
        terms = response.json()["manifest"]["terms"]
        assert terms[0]["target"] == "???"
        assert all(term["target"] != "Warplane" for term in terms)
```

- [ ] **Step 2: Run targeted tests**

```powershell
python -m pytest -q backend/tests/test_mock_e2e.py::test_announcement_lookup_is_language_scoped_and_does_not_mutate_terms
```

Expected: PASS after implementing language filtering.

---

## Task 5: Frontend Entry

**Files:**
- Modify: `D:/codex/localization-workflow-studio/frontend/src/main.tsx`

- [ ] **Step 1: Add state and action**

Add an action similar to `runGlossaryExtract`, but separate:

```ts
async function runAnnouncementLookup() {
  if (!current || !assetArtifacts.length) return
  setBusy(true)
  setStatus('??????/??????...')
  try {
    const result = await api<{ run: Run; artifacts: Artifact[]; summary: { matched_terms: number; matched_translations: number } }>(`/api/projects/${current.id}/announcement-lookup`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        material_artifact_ids: assetArtifacts.map((artifact) => artifact.id),
        language: selectedLanguage
      })
    })
    setLatestRun(result.run)
    await refreshCurrent()
    setStatus(`???????? ${result.summary.matched_terms} ??QA???? ${result.summary.matched_translations} ?`)
  } catch (error) {
    setStatus(`???????${errorText(error)}`)
  } finally {
    setBusy(false)
  }
}
```

- [ ] **Step 2: Add card in Step 5 or glossary tab**

Recommended location: Step 5 under high-frequency scan, because this is also reference preparation.

Copy:

```tsx
<div className="action-card">
  <strong>??/??????</strong>
  <span className="asset-meta">???????????????????????????? QA ?????</span>
  <button className="btn btn-ghost" disabled={!assetArtifacts.length || busy} onClick={onAnnouncementLookup}>???????</button>
</div>
```

- [ ] **Step 3: Wire props through `Wizard` and `StepFreqV2`**

Add `onAnnouncementLookup` to the same prop chain as `onGlossaryExtract`.

- [ ] **Step 4: Build**

```powershell
cd D:\codex\localization-workflow-studio\frontend
npm run build
```

Expected: `tsc && vite build` passes.

---

## Task 6: Regression and Verification

- [ ] **Backend targeted tests**

```powershell
python -m pytest -q backend/tests/test_mock_e2e.py::test_announcement_lookup_uses_glossary_and_qa_passed_archive backend/tests/test_mock_e2e.py::test_announcement_lookup_is_language_scoped_and_does_not_mutate_terms
```

Expected: PASS.

- [ ] **Backend full tests**

```powershell
python -m pytest -q
```

Expected: all pass.

- [ ] **Glossary workflow tests**

```powershell
cd D:\codex\localization-workflow-studio\workflow\glossary
python -m pytest -q tests
```

Expected: all pass.

- [ ] **Frontend build**

```powershell
cd D:\codex\localization-workflow-studio\frontend
npm run build
```

Expected: pass.

- [ ] **Optional E2E if UI changes are non-trivial**

```powershell
cd D:\codex\localization-workflow-studio\frontend
npm run e2e
```

Expected: pass. If e2e fixtures do not include announcement lookup, add only a smoke assertion for the new button label and disabled/enabled state.

---

## Open Decision

**Question:** Should the canonical product entry be a new endpoint/run kind (`announcement_lookup`) or an option under existing `glossary/extract`?

**Recommended answer:** New endpoint/run kind. Reason: this workflow consumes QA-passed translation archive and project glossary; full glossary extraction consumes a language table and generates candidate terms. Overloading the old endpoint will blur audit logs and make migration to the localization QA workflow harder.

---

## Migration Contract for Later Long-Text Translation

The downstream localization workflow should consume only these stable fields:

- `manifest.language`
- `manifest.terms[].source / target / target_alt / category / note`
- `manifest.translations[].entry_key / source / target / target_alt / source_type`
- `announcement_lookup_prompt_context.txt`

Do not make the downstream workflow depend on current workbook formatting except as a human-readable audit artifact.
