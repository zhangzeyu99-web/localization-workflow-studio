from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .. import db
from ..config import REAL_PROVIDERS, TEST_FAKE_PROVIDER, load_settings, normalize_provider_name
from ..languages import language_spec, require_supported_language
from ..providers import call_text
from ..translation_batches import manage_project_prompt_context as _manage_project_prompt_context
from .announcement_segments import _read_language_table_rows
from .common import _CJK_RE
from .glossary_keys import _glossary_source_key
from .semantic_qa import _parse_semantic_qa_payload
from .subprocess_runner import user_facing_error


def _language_table_ai_audit_rows(rows: list[dict[str, Any]], language: str, existing_sources: set[str], limit: int = 400) -> list[dict[str, str]]:
    selected: dict[str, dict[str, str]] = {}
    for row in rows:
        source = str(row.get("source") or "").strip()
        source_key = _glossary_source_key(source)
        if not source or source_key in existing_sources or source_key in selected:
            continue
        if not _CJK_RE.search(source):
            continue
        translations = row.get("translations") if isinstance(row.get("translations"), dict) else {}
        selected[source_key] = {
            "id": str(row.get("id") or "").strip(),
            "source": source,
            "translation": str((translations or {}).get(language) or "").strip(),
        }
    values = list(selected.values())
    values.sort(key=lambda item: (0 if 2 <= len(item["source"]) <= 24 else 1, len(item["source"]), item["source"]))
    return values[:limit]


def _glossary_ai_supplement_prompt(
    *,
    project: dict[str, Any],
    language: str,
    candidates: list[dict[str, Any]],
    audit_rows: list[dict[str, str]],
    settings: dict[str, Any] | None = None,
) -> str:
    spec = language_spec(language)
    profile = project.get("profile") or {}
    prompt_text = str((profile.get("prompts_by_language") or {}).get(language) or project.get("prompt_text") or "").strip()
    prompt_text = _manage_project_prompt_context(prompt_text, settings if settings is not None else load_settings())
    candidate_sources = [
        {"cn": item.get("source"), "translation": item.get("target")}
        for item in candidates[:500]
        if str(item.get("source") or "").strip()
    ]
    packet = {
        "task": "language_table_glossary_ai_supplement",
        "target_language": spec.prompt_name,
        "visible_language": spec.target_header,
        "project": {
            "name": project.get("name", ""),
            "type": project.get("type", ""),
            "profile": {
                key: profile.get(key)
                for key in ("game_type", "target_audience", "content_scope", "translation_style", "tone")
                if profile.get(key)
            },
            "prompt": prompt_text,
        },
        "existing_candidates": candidate_sources,
        "source_rows_for_audit": audit_rows,
        "response_schema": {
            "supplement_terms": [
                {
                    "cn": "必须逐字出现在 source_rows_for_audit.source 中的中文术语",
                    "translation": f"{spec.target_header} 建议译文；不确定则留空",
                    "confidence": "medium|high",
                    "reason": "为什么本地规则漏掉且值得人工审核",
                    "evidence_ids": ["source_rows_for_audit.id"],
                }
            ]
        },
    }
    return (
        "你在做游戏语言表术语候选的漏词审计。本地脚本已经先按规则扫描了一批候选，"
        "你只补充明显漏掉的游戏专名、系统名、玩法名、道具/角色/活动名或关键 UI 术语。\n"
        "硬规则：\n"
        "1. 只能从 source_rows_for_audit 里补，cn 必须逐字出现在某条 source 中。\n"
        "2. 不要补整句、长句、纯标点、普通动词、泛泛说明词。\n"
        "3. 不要重复 existing_candidates 里已有的 CN。\n"
        "4. 有同一行译文证据时给 translation；不确定就留空，交给人工。\n"
        "5. 只返回 confidence 为 medium 或 high 的项，最多 30 条。\n"
        "6. 返回严格 JSON 对象，不要 markdown。\n\n"
        f"Packet JSON:\n{json.dumps(packet, ensure_ascii=False, indent=2)}"
    )


def _normalize_glossary_ai_supplement_terms(payload: dict[str, Any]) -> list[dict[str, Any]]:
    terms = payload.get("supplement_terms")
    if not isinstance(terms, list):
        return []
    return [item for item in terms if isinstance(item, dict)]


def supplement_language_table_glossary_candidates_with_ai(
    *,
    project_id: str,
    batch_id: str,
    input_path: Path,
    language: str,
    run_id: str | None = None,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    language = require_supported_language(language)
    result: dict[str, Any] = {
        "status": "skipped",
        "added": 0,
        "reviewed_rows": 0,
        "provider": "",
        "reason": "",
    }
    if not batch_id:
        result["reason"] = "no_candidate_batch"
        return result

    settings = settings if settings is not None else load_settings()
    provider = normalize_provider_name(settings.get("provider"))
    result["provider"] = provider
    if provider == TEST_FAKE_PROVIDER:
        result["reason"] = "test_provider"
        return result
    if provider in REAL_PROVIDERS and not str(settings.get("api_key") or "").strip():
        result["reason"] = "api_key_missing"
        if run_id:
            db.add_event(run_id, "AI glossary supplement skipped: API key is not configured.", level="warn")
        return result

    project = db.get_project(project_id)
    existing_sources = {
        _glossary_source_key(item.get("source"))
        for item in db.list_glossary_terms(project_id, language=language)
        if _glossary_source_key(item.get("source"))
    }
    batch_candidates = db.list_glossary_candidates(project_id, batch_id=batch_id, language=language)
    existing_sources.update(
        _glossary_source_key(item.get("source"))
        for item in batch_candidates
        if _glossary_source_key(item.get("source"))
    )
    audit_rows = _language_table_ai_audit_rows(_read_language_table_rows(input_path, [language]), language, existing_sources)
    result["reviewed_rows"] = len(audit_rows)
    if not audit_rows:
        result["reason"] = "no_audit_rows"
        return result

    prompt = _glossary_ai_supplement_prompt(
        project=project,
        language=language,
        candidates=batch_candidates,
        audit_rows=audit_rows,
        settings=settings,
    )
    try:
        response_text = call_text(settings, prompt, system="Return strict JSON only.")
        payload = _parse_semantic_qa_payload(response_text)
    except Exception as exc:
        result["status"] = "provider_error"
        result["reason"] = user_facing_error(exc)
        if run_id:
            db.add_event(run_id, f"AI glossary supplement failed: {result['reason']}", level="warn")
        return result

    evidence_by_id = {str(item.get("id") or "").strip(): item for item in audit_rows if str(item.get("id") or "").strip()}
    evidence_sources = [item["source"] for item in audit_rows]
    added = 0
    skipped = 0
    for term in _normalize_glossary_ai_supplement_terms(payload):
        cn = str(term.get("cn") or "").strip()
        source_key = _glossary_source_key(cn)
        confidence = str(term.get("confidence") or "").strip().lower()
        if not cn or source_key in existing_sources or confidence not in {"medium", "high"}:
            skipped += 1
            continue
        evidence_ids = term.get("evidence_ids") if isinstance(term.get("evidence_ids"), list) else []
        evidence_rows = [evidence_by_id.get(str(item).strip()) for item in evidence_ids]
        evidence_rows = [item for item in evidence_rows if item]
        if evidence_rows:
            appears = any(cn in str(item.get("source") or "") for item in evidence_rows)
        else:
            appears = any(cn in source for source in evidence_sources)
        if not appears:
            skipped += 1
            continue
        translation = str(term.get("translation") or "").strip()
        note_bits = ["AI 漏词补充候选，需人工确认"]
        if confidence:
            note_bits.append(f"置信度 {confidence}")
        reason = str(term.get("reason") or "").strip()
        if reason:
            note_bits.append(reason)
        db.add_glossary_candidate(
            project_id,
            batch_id,
            {
                "term_key": str((evidence_rows[0] or {}).get("id") or "") if evidence_rows else "",
                "source": cn,
                "target": translation,
                "target_alt": "",
                "language": language,
                "category": "",
                "note": "；".join(note_bits),
                "action": "new",
                "translation_status": "suggested" if translation else "needs_translation",
                "translation_source": "ai_supplement" if translation else "none",
                "metadata": {
                    "ai_supplement": {
                        "provider": provider,
                        "model": settings.get("model") or "",
                        "confidence": confidence,
                        "reason": reason,
                        "evidence_ids": evidence_ids,
                    }
                },
            },
        )
        existing_sources.add(source_key)
        added += 1

    result.update({"status": "passed", "added": added, "skipped": skipped, "reason": ""})
    if run_id:
        db.add_event(run_id, f"AI glossary supplement added {added} candidates, skipped {skipped}.")
    return result


