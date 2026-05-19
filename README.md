# Localization Workflow Studio

Local web studio for game localization workflows. It combines project onboarding, multimodal project analysis, glossary extraction, English translation harnessing, model-provider translation, strict QA, and artifact history.

## Quick Start

```powershell
cd D:\codex\localization-workflow-studio
python -m pip install -r backend\requirements.txt
cd frontend
npm install
npm run build
cd ..
python -m pytest -q
python backend\app\main.py
```

The default data directory is outside the public repository:

```text
D:\codex\localization-workflow-studio-data
```

## Provider Settings

Public repository files only include `settings.example.json`. Runtime secrets are stored in:

```text
D:\codex\localization-workflow-studio-data\settings.local.json
```

Default provider is `mock`, so local tests and CI do not require an API key. `chat-completions` is the default real protocol, with `responses` also supported.

