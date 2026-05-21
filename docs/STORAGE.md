# Storage Model

Localization Workflow Studio separates public source code from private runtime data.

## Public Repository

The GitHub repository stores only product code, documentation, fixtures, and safe examples:

- `frontend/`: React/Vite application source.
- `backend/`: FastAPI application source.
- `workflow/`: embedded reusable localization and glossary workflow code.
- `docs/`: documentation and the GitHub Pages static demo.
- `examples/`: synthetic sample files only.
- `settings.example.json`: non-secret configuration shape.

Do not commit real project workbooks, customer assets, provider keys, SQLite files, generated delivery files, logs, or local run artifacts.

## Local Runtime Data

Default local data root:

```text
D:\codex\localization-workflow-studio-data
```

This directory is intentionally outside the public repository. It stores:

```text
localization-workflow-studio-data/
  settings.local.json
  studio.sqlite3
  projects/
    <project_id>/
      uploads/
      assets/
      profile/
        project_harness.json
      glossary/
      runs/
        <run_id>/
          translation/
          qa/
          delivery/
```

Key rules:

- `settings.local.json` contains provider settings and must remain private.
- `studio.sqlite3` contains project metadata and run records.
- `uploads/` contains source workbooks, term bases, translated workbooks, and reference materials.
- `runs/` contains workpacks, QA reports, model outputs, final workbooks, and delivery files.
- Project harness and prompt snapshots are runtime data because they may encode customer/project requirements.

## Git Ignore Coverage

`.gitignore` excludes the default data directory plus common runtime artifacts:

- `localization-workflow-studio-data/`
- `settings.local.json`
- `*.sqlite`, `*.sqlite3`, `*.db`
- `uploads/`, `artifacts/`, `runs/`, `projects/`, `outputs/`
- generated final/output workbooks
- logs and local env files

Synthetic workbook fixtures under `examples/` and workflow templates are allowed because they are not real project data.

## Shared Deployment

For a shared deployment, do not use the repository filesystem as runtime storage.

Recommended production split:

| Data type | Recommended storage |
|---|---|
| Project metadata, users, runs | Postgres |
| Uploaded workbooks and reference assets | S3, Cloudflare R2, OSS, MinIO, or private persistent volume |
| Generated workbooks and reports | Same object storage as uploads |
| Provider keys | Backend secret manager or environment variables |
| Temporary workpacks | Private backend working directory with cleanup policy |

For a single-user private server, SQLite plus a persistent private volume is acceptable. For team usage, prefer Postgres and object storage so uploads and delivery files are not tied to one machine.

## Sharing Policy

Use one of three sharing modes:

- Public demo: GitHub Pages static page only, with no real data or backend.
- Private app: authenticated backend plus private storage.
- Result sharing: export final workbook and change report, then share those files through a controlled channel.

Do not expose the local data directory through GitHub Pages or commit it into the repository.
