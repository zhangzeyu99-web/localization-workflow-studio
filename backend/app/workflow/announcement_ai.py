from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openpyxl import Workbook

from .. import db
from ..config import REAL_PROVIDERS, load_settings, normalize_provider_name
from ..languages import ANNOUNCEMENT_LANGUAGE_ORDER, require_supported_language, target_aliases, visible_language_code
from .announcement_shared import ANNOUNCEMENT_STEP, _announcement_task_metadata, _count_lookup_hits
from .announcement_outputs import _announcement_task_source_stem, _today_stamp, _visible_language_code
from .announcement_segments import _announcement_task_source_text, _glossary_extractor_module
from .common import run_dir
from .table_helpers import _wide_source_key
from .qa import _call_semantic_provider, _parse_semantic_qa_payload
from .subprocess_runner import user_facing_error

def _announcement_ai_headers(languages: list[str]) -> list[str]:
    return ["ID", "CN", *[visible_language_code(language) for language in languages]]


def _announcement_term_to_ai_row(row: dict[str, Any], languages: list[str]) -> dict[str, object]:
    output: dict[str, object] = {
        "ID": str(row.get("id") or row.get("ID") or "").strip(),
        "CN": str(row.get("source") or row.get("CN") or "").strip(),
    }
    translations = row.get("translations") if isinstance(row.get("translations"), dict) else {}
    for language in languages:
        output[visible_language_code(language)] = str((translations or {}).get(language) or "").strip()
    return output


def _normalize_ai_supplement_response(response: dict[str, Any], languages: list[str]) -> dict[str, Any]:
    terms = response.get("supplement_terms")
    if not isinstance(terms, list):
        return {"supplement_terms": []}
    normalized_terms: list[dict[str, Any]] = []
    for term in terms:
        if not isinstance(term, dict):
            continue
        item = dict(term)
        translations = item.get("translations")
        if isinstance(translations, dict):
            normalized_translations = {str(key): value for key, value in translations.items()}
            lower_lookup = {str(key).strip().lower(): value for key, value in translations.items()}
            for language in languages:
                header = visible_language_code(language)
                if str(normalized_translations.get(header) or "").strip():
                    continue
                aliases = {language, header.lower(), *[alias.lower() for alias in target_aliases(language)]}
                for alias in aliases:
                    if alias in lower_lookup and str(lower_lookup[alias] or "").strip():
                        normalized_translations[header] = lower_lookup[alias]
                        break
            item["translations"] = normalized_translations
        normalized_terms.append(item)
    return {**response, "supplement_terms": normalized_terms}


def _announcement_ai_rows_to_terms(ai_rows: list[dict[str, object]], original_rows: list[dict[str, Any]], source_text: str, languages: list[str]) -> list[dict[str, Any]]:
    original_by_source = {_wide_source_key(row.get("source")): row for row in original_rows if _wide_source_key(row.get("source"))}
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ai_row in ai_rows:
        source = str(ai_row.get("CN") or "").strip()
        key = _wide_source_key(source)
        if not key or key in seen:
            continue
        seen.add(key)
        if key in original_by_source:
            output.append(original_by_source[key])
            continue
        hit_count, first_position = _count_lookup_hits(source_text, source)
        translations = {
            language: str(ai_row.get(visible_language_code(language)) or "").strip()
            for language in languages
        }
        output.append(
            {
                "id": str(ai_row.get("ID") or "").strip(),
                "source": source,
                "translations": translations,
                "hit_count": hit_count,
                "first_position": first_position,
                "source_type": "ai_supplement",
            }
        )
    return output


def _read_ai_supplement_response_artifact(project_id: str, artifact_id: str | None) -> dict[str, Any] | None:
    if not artifact_id:
        return None
    artifact = db.get_artifact(artifact_id)
    if artifact["project_id"] != project_id:
        raise KeyError(artifact_id)
    payload = json.loads(Path(artifact["path"]).read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("AI supplement response must be a JSON object")
    return payload


def _ai_supplement_provider_prompt(packet: dict[str, Any]) -> str:
    return (
        "You are auditing a game announcement glossary extraction result.\n"
        "Use only the supplied packet. Do not invent translations without evidence_rows.\n"
        "Return strict JSON only, no markdown fences, matching packet.response_schema.\n"
        "Only add terms that appear verbatim in announcement_text and are backed by evidence_ids.\n\n"
        f"Packet JSON:\n{json.dumps(packet, ensure_ascii=False, indent=2)}"
    )


def _call_ai_supplement_provider(settings: dict[str, Any], packet: dict[str, Any]) -> dict[str, Any]:
    text = _call_semantic_provider(settings, _ai_supplement_provider_prompt(packet))
    payload = _parse_semantic_qa_payload(text)
    if not isinstance(payload, dict):
        raise ValueError("AI supplement provider must return a JSON object")
    return payload


def _apply_announcement_ai_supplement(
    *,
    project_id: str,
    output_dir: Path,
    base_name: str,
    source_text: str,
    rows: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    languages: list[str],
    request: Any,
    project_name: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not bool(getattr(request, "ai_supplement", False)):
        return rows, {}
    extractor = _glossary_extractor_module()
    headers = _announcement_ai_headers(languages)
    packet_path = output_dir / f"{base_name}_ai_supplement_packet_{_today_stamp()}.json"
    report_path = output_dir / f"{base_name}_ai_supplement_report_{_today_stamp()}.md"
    matched_rows = [_announcement_term_to_ai_row(row, languages) for row in rows]
    candidate_rows = [_announcement_term_to_ai_row(row, languages) for row in candidates]
    packet = extractor.build_ai_supplement_packet(
        announcement_text=source_text,
        matched_rows=matched_rows,
        candidate_rows=candidate_rows,
        headers=headers,
        project_name=project_name,
    )
    packet_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8")
    response_artifact_id = str(getattr(request, "ai_supplement_response_artifact_id", "") or "")
    response_path: Path | None = None
    provider = ""
    provider_status = "not_configured"
    provider_error = ""
    response = _read_ai_supplement_response_artifact(project_id, response_artifact_id)
    if response is not None:
        provider = "uploaded"
        provider_status = "uploaded_response"
    elif not packet.get("evidence_rows"):
        provider_status = "no_evidence"
        response = {"supplement_terms": []}
    else:
        settings = load_settings()
        configured_provider = normalize_provider_name(settings.get("provider"))
        if configured_provider in REAL_PROVIDERS and settings.get("api_key"):
            provider = configured_provider
            try:
                response = _call_ai_supplement_provider(settings, packet)
                provider_status = "provider_response"
                response_path = output_dir / f"{base_name}_ai_supplement_response_{_today_stamp()}.json"
                response_path.write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as exc:
                provider_status = "provider_error"
                provider_error = user_facing_error(exc)
                response = {"supplement_terms": []}
        else:
            response = {"supplement_terms": []}
    response = _normalize_ai_supplement_response(response, languages)
    merged_ai_rows, report = extractor.apply_ai_supplement_response(
        announcement_rows=matched_rows,
        headers=headers,
        announcement_text=source_text,
        packet=packet,
        response=response,
        project_name=project_name,
    )
    report["provider"] = provider or provider_status
    if provider_error:
        report["provider_error"] = provider_error
    report_markdown = extractor.build_ai_supplement_report_markdown(
        report=report,
        packet_path=packet_path,
        response_path=Path(db.get_artifact(response_artifact_id)["path"]) if response_artifact_id else response_path,
        output_path=report_path,
    )
    report_path.write_text(report_markdown, encoding="utf-8")
    merged_rows = _announcement_ai_rows_to_terms(merged_ai_rows, rows, source_text, languages)
    report_terms = report.get("terms") if isinstance(report.get("terms"), list) else []
    ai_summary = {
        "enabled": True,
        "packet_path": str(packet_path),
        "report_path": str(report_path),
        "response_path": str(response_path or ""),
        "response_artifact_id": response_artifact_id,
        "provider": provider,
        "provider_status": provider_status,
        "provider_error": provider_error,
        "term_count": len(report_terms),
        "added_to_main": sum(1 for term in report_terms if isinstance(term, dict) and term.get("status") == "added_to_main"),
        "project_name_translation_missing": bool(report.get("project_name_translation_missing")),
        "report": report,
    }
    return merged_rows, ai_summary


def _save_announcement_terms(task_id: str, rows: list[dict[str, Any]], languages: list[str], *, run_kind: str) -> dict[str, Any]:
    task = db.get_announcement_task(task_id)
    project_id = task["project_id"]
    metadata = _announcement_task_metadata(task)
    source_text = _announcement_task_source_text(task)
    run = db.insert_run(project_id, kind=run_kind, language=languages[0] if languages else "en", metadata={"task_id": task_id, "languages": languages})
    db.update_run(run["id"], status="running")
    output = run_dir(run["id"]) / "announcement_terms"
    output.mkdir(parents=True, exist_ok=True)
    base = _announcement_task_source_stem(task)
    stamp = _today_stamp()
    workbook_path = output / f"{base}_announcement_terms_{stamp}.xlsx"
    manifest_path = output / f"{base}_announcement_terms_manifest_{stamp}.json"
    validation_path = output / f"{base}_announcement_terms_validation_{stamp}.md"
    _write_announcement_terms_workbook(workbook_path, rows, languages)
    summary = {"terms": len(rows), "languages": languages, "source_chars": len(source_text)}
    manifest = {"kind": "announcement_terms", "task_id": task_id, "project_id": project_id, "languages": languages, "summary": summary, "terms": rows}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    validation_path.write_text(_announcement_terms_validation(summary, rows, languages), encoding="utf-8")
    artifacts = [
        db.add_artifact(project_id, "公告术语表", workbook_path, "announcement_terms_workbook", run_id=run["id"], mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", metadata={"task_id": task_id, "languages": languages}),
        db.add_artifact(project_id, "公告术语 manifest", manifest_path, "announcement_terms_manifest", run_id=run["id"], mime="application/json", metadata={"task_id": task_id, "languages": languages}),
        db.add_artifact(project_id, "公告术语 validation", validation_path, "announcement_terms_validation", run_id=run["id"], mime="text/markdown", metadata={"task_id": task_id, "languages": languages}),
    ]
    metadata.update({"languages": languages, "terms": rows, "terms_artifact_id": artifacts[0]["id"], "terms_manifest_artifact_id": artifacts[1]["id"], "terms_validation_artifact_id": artifacts[2]["id"], "terms_summary": summary})
    task = db.update_announcement_task(task_id, status="terms_ready", current_step=ANNOUNCEMENT_STEP["lookup"], selected_languages=languages, metadata=metadata)
    for language in languages:
        missing = sum(1 for row in rows if not str((row.get("translations") or {}).get(language) or "").strip())
        db.upsert_announcement_task_language(task_id, project_id, language, status="terms_ready", current_step=ANNOUNCEMENT_STEP["lookup"], metadata={"terms": len(rows), "missing_terms": missing})
    db.update_run(run["id"], status="passed", metadata={**run.get("metadata", {}), "summary": summary, "task_id": task_id})
    from .announcement import _hydrate_announcement_task

    return {"task": _hydrate_announcement_task(task), "run": db.get_run(run["id"]), "summary": summary, "artifacts": artifacts, "manifest": manifest}


def _normalize_announcement_terms_payload(raw_terms: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(raw_terms, start=1):
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or item.get("cn") or item.get("term") or "").strip()
        if not source:
            continue
        translations: dict[str, str] = {}
        raw_translations = item.get("translations") if isinstance(item.get("translations"), dict) else {}
        for key, value in {**raw_translations, **item}.items():
            try:
                language = require_supported_language(key)
            except ValueError:
                continue
            text = str(value or "").strip()
            if text:
                translations[language] = text
        rows.append({
            "id": str(item.get("id") or item.get("term_key") or item.get("key") or index).strip(),
            "source": source,
            "translations": translations,
            "hit_count": int(item.get("hit_count") or 0),
            "first_position": int(item.get("first_position") or 0),
        })
    return rows


def _announcement_terms_languages(rows: list[dict[str, Any]]) -> list[str]:
    found: set[str] = set()
    for row in rows:
        for language, value in (row.get("translations") or {}).items():
            try:
                code = require_supported_language(language)
            except ValueError:
                continue
            if str(value or "").strip():
                found.add(code)
    return [code for code in ANNOUNCEMENT_LANGUAGE_ORDER if code in found]


def _filter_announcement_terms_languages(rows: list[dict[str, Any]], languages: list[str]) -> list[dict[str, Any]]:
    selected = set(languages)
    output: list[dict[str, Any]] = []
    for row in rows:
        translations = {language: value for language, value in (row.get("translations") or {}).items() if language in selected}
        output.append({**row, "translations": translations})
    return output


def _write_announcement_terms_workbook(path: Path, rows: list[dict[str, Any]], languages: list[str]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Glossary"
    headers = ["ID", "CN", *[_visible_language_code(language) for language in languages], "命中次数", "来源", "备注"]
    ws.append(headers)
    for row in rows:
        translations = row.get("translations") or {}
        sources = row.get("sources") if isinstance(row.get("sources"), list) else []
        source_label = row.get("source_type") or "/".join(sorted({str(item.get("type") or "") for item in sources if isinstance(item, dict) and item.get("type")}))
        ws.append([
            row.get("id", ""),
            row.get("source", ""),
            *[translations.get(language, "") for language in languages],
            row.get("hit_count", ""),
            source_label,
            row.get("note", ""),
        ])
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    wb.close()


def _announcement_terms_validation(summary: dict[str, Any], rows: list[dict[str, Any]], languages: list[str]) -> str:
    missing = {language: sum(1 for row in rows if not (row.get("translations") or {}).get(language)) for language in languages}
    return "\n".join(
        [
            "# Announcement terms validation",
            "",
            "status: ok",
            f"terms: {summary.get('terms', 0)}",
            f"languages: {', '.join(_visible_language_code(language) for language in languages)}",
            *[f"missing_{_visible_language_code(language)}: {count}" for language, count in missing.items()],
            "",
        ]
    )

__all__ = [name for name in globals() if not name.startswith("__")]
