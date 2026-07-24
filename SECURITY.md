# Security Policy

Localization Workflow Studio is designed for local-first workflows. The main security risk is accidental exposure of private localization data or provider credentials through public repositories, screenshots, issues, or generated artifacts.

## Supported Versions

Security fixes target the latest version on the default branch and the latest published release.

Current version:

```text
1.6.4
```

## Sensitive Data Boundary

Keep these outside the public repository:

- provider API keys,
- `settings.local.json`,
- SQLite databases,
- uploaded workbooks,
- customer source strings,
- reference screenshots or design docs from private projects,
- run logs,
- workpacks,
- QA reports,
- final delivery workbooks.

The recommended local runtime directory is:

```text
D:\codex\localization-workflow-studio-data
```

## Reporting a Vulnerability

Use a private disclosure path when the report includes secrets, private customer data, or exploitable details. If GitHub private vulnerability reporting is enabled for the repository, use that. Otherwise, open a public issue with only a minimal, sanitized summary and ask for a private contact path.

Do not paste:

- API keys,
- real workbook rows,
- customer names,
- unreleased game strings,
- private file paths containing sensitive project names,
- full logs with provider responses.

## Safe Public Reports

Public issues are fine for:

- dependency vulnerability alerts without secrets,
- failing CI details,
- reproducible crashes with synthetic data,
- incorrect QA results on public fixtures,
- documentation problems.

Use `examples/synthetic-language.xlsx` whenever possible.

## Maintainer Response

Expected response flow:

1. Confirm receipt.
2. Reproduce with synthetic or sanitized data.
3. Patch the issue on a dedicated branch.
4. Run relevant backend, workflow, frontend, and E2E checks.
5. Publish a release note if users need to update configuration or rotate secrets.

If a committed secret is discovered, rotate it immediately. Removing it from the latest commit is not enough once it has been pushed.
