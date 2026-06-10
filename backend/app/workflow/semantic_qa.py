from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..config import REAL_PROVIDERS, load_settings, normalize_provider_name
from ..languages import language_spec, require_supported_language
from ..providers import call_text
from .subprocess_runner import user_facing_error

def run_semantic_qa_report(
    run_id: str,
    project_id: str,
    workbook_path: Path,
    quality: dict[str, Any],
    project_quality: dict[str, Any],
    language: str = "en",
) -> dict[str, Any]:
    language = require_supported_language(language)
    spec = language_spec(language)
    settings = load_settings()
    provider = normalize_provider_name(settings.get("provider"))
    model = str(settings.get("model") or "")
    issue_context = {
        "global_issue_count": len(quality.get("issues", [])),
        "project_harness_issue_count": len(project_quality.get("issues", [])),
        "sample_issues": (quality.get("issues", []) or [])[:20],
        "project_issues": (project_quality.get("issues", []) or [])[:20],
    }
    base = {
        "source": "semantic_qa",
        "provider": provider,
        "model": model,
        "prompt_context": {"run_id": run_id, "project_id": project_id, "language": language, **issue_context},
        "issues": [],
        "soft_warnings": 0,
    }
    if provider not in REAL_PROVIDERS or not settings.get("api_key"):
        return {**base, "status": "skipped_no_key", "passed": True, "hard_errors": 0}

    prompt = (
        f"You are doing semantic QA for a {spec.prompt_name} game localization workbook. "
        "Review the machine QA context and return strict JSON only: "
        "{\"passed\": boolean, \"issues\": [{\"severity\":\"hard|soft\", \"message\":\"...\", \"sheet\":\"\", \"row\":0}]}.\n"
        f"Workbook: {workbook_path.name}\n"
        f"Context:\n{json.dumps(issue_context, ensure_ascii=False)}"
    )
    try:
        text = _call_semantic_provider(settings, prompt)
        payload = _parse_semantic_qa_payload(text)
        issues = payload.get("issues", []) if isinstance(payload.get("issues"), list) else []
        hard_errors = len([issue for issue in issues if str(issue.get("severity", "hard")).lower() == "hard"])
        return {
            **base,
            "status": "model_reviewed",
            "passed": bool(payload.get("passed", hard_errors == 0)) and hard_errors == 0,
            "hard_errors": hard_errors,
            "soft_warnings": len([issue for issue in issues if str(issue.get("severity", "")).lower() == "soft"]),
            "issues": issues,
        }
    except Exception as exc:
        return {
            **base,
            "status": "provider_error",
            "passed": False,
            "hard_errors": 1,
            "issues": [{"severity": "hard", "message": f"Semantic QA provider failed: {user_facing_error(exc)}", "sheet": "", "row": 0}],
        }


def _call_semantic_provider(settings: dict[str, Any], prompt: str) -> str:
    return call_text(settings, prompt, system="Return strict JSON only.")


def _parse_semantic_qa_payload(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        start = cleaned.find("{")
        while start != -1:
            try:
                payload, _ = decoder.raw_decode(cleaned[start:])
                if isinstance(payload, dict):
                    return payload
            except json.JSONDecodeError:
                start = cleaned.find("{", start + 1)
                continue
        raise
