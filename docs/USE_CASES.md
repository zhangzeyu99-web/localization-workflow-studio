# Use Cases

![Localization Workflow Studio use-case map](assets/use-case-map.svg)

## 1. Mock EN Regression

Use this before every workflow integration change.

```powershell
cd D:\codex\localization-workflow-studio\frontend
$env:E2E_BASE_URL = "http://127.0.0.1:5173"
npm run e2e
```

Expected result:

- Project is created from the web UI.
- Manual glossary term is saved.
- Project prompt is generated.
- Workbook is uploaded.
- Glossary extraction completes.
- Mock translation run passes.
- QA gate passes.
- Final workbook download is available.

## 2. Recent Real Project Replay

Use this to verify the integration with a completed local task while keeping provider cost at zero.

```powershell
cd D:\codex\localization-workflow-studio\frontend
$root = "C:\Users\Administrator\Desktop\本地化处理\明日2_5.15"
$env:E2E_BASE_URL = "http://127.0.0.1:5173"
$env:E2E_SOURCE_WORKBOOK = Join-Path $root "2.0欧美翻译需求0515NT全语.xlsx"
$env:E2E_TERM_WORKBOOK = Join-Path $root "明日2术语表.xlsx"
npm run e2e
```

Expected result:

- Source workbook and term workbook are copied into the external data directory.
- Glossary outputs are archived.
- Mock final workbook, QA report, QA result, manifest, and response JSONL are archived.
- Web project history shows both glossary and translation runs.

## 3. Real Provider Smoke

Use this only after `settings.local.json` contains a valid provider key.

```powershell
cd D:\codex\localization-workflow-studio
python backend\app\main.py
```

Then open `http://127.0.0.1:5173`, set provider to `openai-compatible`, keep protocol as Chat Completions unless testing Responses, and run the same EN workflow with a small workbook first.

## Image-Gen Prompt

The use-case map is maintained as a static repository asset. When regenerating it with image-gen, use this prompt:

```text
Create a clean product documentation illustration for a local web app named Localization Workflow Studio. Show three user paths as connected panels: Mock EN Regression, Recent Real Project Replay, and Real Provider Smoke. Include visual motifs for React/Vite frontend, FastAPI backend, SQLite external data directory, workbook upload, glossary extraction, JSONL translation, QA gate, and artifact download. Style: crisp technical product diagram, dark navy background, cyan and violet accents, readable labels, no logos, 16:9.
```
