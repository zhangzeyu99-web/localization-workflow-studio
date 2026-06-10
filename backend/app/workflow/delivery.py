from __future__ import annotations

# ruff: noqa: F403,F405

from .common import *

def list_project_deliverables(project_id: str) -> list[dict[str, Any]]:
    project = db.get_project(project_id)
    deliverables: list[dict[str, Any]] = []
    for run in db.list_runs(project_id):
        if run["kind"] not in {"translation", "qa"} or run["status"] != "passed":
            continue
        final_artifact = _deliverable_final_artifact(run)
        if not final_artifact or not Path(final_artifact["path"]).exists():
            continue
        deliverables.append(_deliverable_summary(project, run, final_artifact))
    deliverables.extend(_announcement_deliverable_summaries(project))
    return deliverables


def _announcement_deliverable_summaries(project: dict[str, Any]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for task in db.list_announcement_tasks(project["id"]):
        if task.get("status") != "delivered":
            continue
        metadata = task.get("metadata") or {}
        delivery_artifact_id = str(metadata.get("delivery_artifact_id") or "")
        if not delivery_artifact_id:
            continue
        try:
            package_artifact = db.get_artifact(delivery_artifact_id)
        except KeyError:
            continue
        if (package_artifact.get("metadata") or {}).get("superseded"):
            continue
        if not Path(package_artifact["path"]).exists():
            continue
        languages = _normalize_announcement_languages(task.get("selected_languages") or [], fallback=metadata.get("languages") or [])
        output_files = []
        output_artifact_ids = metadata.get("output_artifact_ids") if isinstance(metadata.get("output_artifact_ids"), dict) else {}
        for language in languages:
            artifact_id = str(output_artifact_ids.get(language) or "")
            if not artifact_id:
                continue
            try:
                artifact = db.get_artifact(artifact_id)
            except KeyError:
                continue
            if Path(artifact["path"]).exists():
                output_files.append(_artifact_delivery_file(f"output_{_visible_language_code(language)}", artifact))
        qa_file = None
        qa_artifact_id = str(metadata.get("qa_summary_artifact_id") or "")
        if qa_artifact_id:
            try:
                qa_artifact = db.get_artifact(qa_artifact_id)
                if Path(qa_artifact["path"]).exists():
                    qa_file = _artifact_delivery_file("qa_summary", qa_artifact)
            except KeyError:
                qa_file = None
        package_file = _artifact_delivery_file("package", package_artifact)
        language_label = " / ".join(_visible_language_code(language) for language in languages) or "-"
        source_rows = int(metadata.get("segment_count") or metadata.get("terms_count") or metadata.get("term_count") or 0)
        return_label = task.get("title") or _announcement_task_source_stem(task)
        summaries.append(
            {
                "run_id": package_artifact.get("run_id") or task["id"],
                "task_code": "ANN",
                "task_id": _short_run_id(task["id"]),
                "task_label": f"ANN-{_short_run_id(task['id'])}",
                "task_type": "公告任务",
                "language": language_label,
                "created_at": task.get("created_at", ""),
                "updated_at": task.get("updated_at", ""),
                "status": "delivered",
                "processed_rows": source_rows,
                "source_rows": source_rows,
                "translated_rows": source_rows,
                "provider": "-",
                "model": "-",
                "input_label": return_label,
                "qa_status": "passed",
                "qa_hard_errors": int(metadata.get("hard_blockers") or 0),
                "qa_soft_warnings": 0,
                "files": {
                    "package": package_file,
                    "qa_summary": qa_file,
                    "outputs": output_files,
                },
                "source_artifacts": {
                    "announcement_delivery_package": package_artifact["id"],
                    "announcement_outputs": [item.get("artifact_id") for item in output_files if item.get("artifact_id")],
                    "announcement_qa_summary": qa_artifact_id,
                },
            }
        )
    return summaries


def build_delivery_package(project_id: str, run_id: str | None = None) -> dict[str, Any]:
    project = db.get_project(project_id)
    deliverables = list_project_deliverables(project_id)
    if not deliverables:
        raise ValueError("QA 未通过，暂无最终交付 workbook")
    selected = deliverables[0]
    if run_id:
        selected = next((item for item in deliverables if item["run_id"] == run_id), None)
        if not selected:
            raise ValueError("指定任务未通过 QA，暂无最终交付")
    run = db.get_run(selected["run_id"])
    final_source = _deliverable_final_artifact(run)
    if not final_source or not Path(final_source["path"]).exists():
        raise ValueError("暂无最终交付文件")
    changes_source = _run_artifact(run["id"], "qa_changes")

    output_dir = project_dir(project_id) / "delivery"
    output_dir.mkdir(parents=True, exist_ok=True)
    if final_source["kind"] == "final_text":
        final_path = _delivery_final_output_path(project, run, final_source)
        shutil.copy2(final_source["path"], final_path)
        summary = _deliverable_summary(project, run, final_source)
        summary["files"] = {"final": _delivery_file("final", final_path)}
        return {"project_id": project_id, "project_name": project["name"], "deliverable": summary, "files": list(summary["files"].values())}

    final_path, changes_path = _delivery_output_paths(project, run)
    shutil.copy2(final_source["path"], final_path)
    _normalize_delivery_workbook_headers(final_path, run.get("language") or "en")
    if changes_source and Path(changes_source["path"]).exists():
        shutil.copy2(changes_source["path"], changes_path)
    else:
        empty_changes = write_qa_changes_report(output_dir, [])
        empty_changes.replace(changes_path)

    summary = _deliverable_summary(project, run, final_source)
    summary["files"] = {
        "final": _delivery_file("final", final_path),
        "changes": _delivery_file("changes", changes_path),
    }
    return {"project_id": project_id, "project_name": project["name"], "deliverable": summary, "files": list(summary["files"].values())}


def _deliverable_summary(project: dict[str, Any], run: dict[str, Any], final_artifact: dict[str, Any]) -> dict[str, Any]:
    changes_artifact = _run_artifact(run["id"], "qa_changes")
    final_path, changes_path = _delivery_output_paths(project, run)
    if final_artifact["kind"] == "final_text":
        final_path = _delivery_final_output_path(project, run, final_artifact)
    task_code, task_run_id = _effective_task_identity(run)
    metadata = run.get("metadata", {})
    quality_summary = metadata.get("quality_summary") or {}
    provider, model = _deliverable_provider_model(metadata, quality_summary)
    input_label = _input_artifact_label(run, run["project_id"])
    processed = (
        {"processed_rows": int(metadata.get("translated_rows") or metadata.get("source_rows") or 0), "source_rows": int(metadata.get("source_rows") or 0), "translated_rows": int(metadata.get("translated_rows") or 0)}
        if final_artifact["kind"] == "final_text"
        else _workbook_processed_rows(Path(final_artifact["path"]))
    )
    files = {"final": _delivery_file("final", final_path) if final_path.exists() else _expected_delivery_file("final", final_path)}
    if final_artifact["kind"] != "final_text":
        files["changes"] = _delivery_file("changes", changes_path) if changes_path.exists() else _expected_delivery_file("changes", changes_path)
    return {
        "run_id": run["id"],
        "task_code": task_code,
        "task_id": _short_run_id(task_run_id),
        "task_label": f"{task_code}-{_short_run_id(task_run_id)}",
        "task_type": _task_type_label(task_code),
        "language": _visible_language_code(run.get("language") or "en"),
        "created_at": run.get("created_at", ""),
        "updated_at": run.get("updated_at", ""),
        "status": run.get("status", ""),
        "processed_rows": processed["processed_rows"] or int(metadata.get("translated_rows") or 0),
        "source_rows": processed["source_rows"],
        "translated_rows": processed["translated_rows"],
        "provider": provider,
        "model": model,
        "input_label": input_label,
        "qa_status": "passed" if quality_summary.get("passed", run.get("status") == "passed") else "failed",
        "qa_hard_errors": int(quality_summary.get("hard_errors") or 0),
        "qa_soft_warnings": _soft_warning_count(quality_summary),
        "files": files,
        "source_artifacts": {
            "qa_final_workbook": final_artifact["id"] if final_artifact["kind"] == "qa_final_workbook" else "",
            "final_text": final_artifact["id"] if final_artifact["kind"] == "final_text" else "",
            "qa_changes": changes_artifact["id"] if changes_artifact else "",
        },
    }


def _deliverable_final_artifact(run: dict[str, Any]) -> dict[str, Any] | None:
    return _run_artifact(run["id"], "qa_final_workbook") or _run_artifact(run["id"], "final_text")


def _effective_task_identity(run: dict[str, Any], seen: set[str] | None = None) -> tuple[str, str]:
    seen = seen or set()
    if run["id"] in seen:
        return _fallback_task_code(run), run["id"]
    seen.add(run["id"])
    metadata = run.get("metadata", {})
    source_run_id = metadata.get("manual_fix_source_run_id") or metadata.get("model_fix_source_run_id") or metadata.get("source_run_id")
    if source_run_id:
        try:
            source_run = db.get_run(str(source_run_id))
            if source_run["project_id"] == run["project_id"]:
                source_code, source_id = _effective_task_identity(source_run, seen)
                if run["kind"] == "qa" and source_run["kind"] in {"translation", "qa"}:
                    return source_code, source_id
        except KeyError:
            pass
    task_code = str(metadata.get("task_code") or "").upper()
    if task_code not in {"A", "T", "QA"}:
        task_code = _fallback_task_code(run)
    return task_code, run["id"]


def _fallback_task_code(run: dict[str, Any]) -> str:
    if run["kind"] == "translation":
        return "T"
    if run["kind"] == "qa":
        return "QA"
    return str(run["kind"] or "TASK").upper()


def _task_type_label(task_code: str) -> str:
    return {"A": "完整工作流", "T": "翻译任务", "QA": "校对任务"}.get(task_code, task_code)


def _short_run_id(run_id: str) -> str:
    return str(run_id).removeprefix("run_")[:6]


def _delivery_output_paths(project: dict[str, Any], run: dict[str, Any]) -> tuple[Path, Path]:
    output_dir = project_dir(project["id"]) / "delivery"
    output_dir.mkdir(parents=True, exist_ok=True)
    task_code, task_run_id = _effective_task_identity(run)
    timestamp = _delivery_timestamp(run.get("created_at", ""))
    language = _visible_language_code(run.get("language") or "en")
    prefix = f"{_safe_delivery_name(project['name'])}_{language}_{timestamp}_{task_code}-{_short_run_id(task_run_id)}"
    return output_dir / f"{prefix}_final.xlsx", output_dir / f"{prefix}_changes.xlsx"


def _delivery_final_output_path(project: dict[str, Any], run: dict[str, Any], source_artifact: dict[str, Any]) -> Path:
    output_dir = project_dir(project["id"]) / "delivery"
    output_dir.mkdir(parents=True, exist_ok=True)
    task_code, task_run_id = _effective_task_identity(run)
    timestamp = _delivery_timestamp(run.get("created_at", ""))
    language = _visible_language_code(run.get("language") or "en")
    suffix = Path(str(source_artifact.get("path") or "")).suffix.lower() or ".txt"
    prefix = f"{_safe_delivery_name(project['name'])}_{language}_{timestamp}_{task_code}-{_short_run_id(task_run_id)}"
    return output_dir / f"{prefix}_final{suffix}"


def _normalize_delivery_workbook_headers(path: Path, language: Any) -> None:
    code = require_supported_language(language or "en")
    target = _visible_language_code(code)
    aliases = {alias.strip().lower() for alias in target_aliases(code)}
    if not aliases:
        return
    wb = load_workbook(path)
    changed = False
    try:
        for ws in wb.worksheets:
            for cell in ws[1]:
                value = str(cell.value or "").strip()
                if value and value.lower() in aliases and value != target:
                    cell.value = target
                    changed = True
        if changed:
            wb.save(path)
    finally:
        wb.close()


def _delivery_timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.strftime("%Y%m%d%H%M")
        return parsed.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d%H%M")
    except Exception:
        return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d%H%M")


def _run_artifact(run_id: str, kind: str) -> dict[str, Any] | None:
    artifacts = [artifact for artifact in db.list_artifacts(run_id=run_id) if artifact["kind"] == kind]
    return artifacts[0] if artifacts else None


def _input_artifact_label(run: dict[str, Any], project_id: str, seen: set[str] | None = None) -> str:
    seen = seen or set()
    run_id = str(run.get("id") or "")
    if run_id:
        if run_id in seen:
            return "-"
        seen.add(run_id)
    metadata = run.get("metadata") or {}
    source_run_id = metadata.get("manual_fix_source_run_id") or metadata.get("model_fix_source_run_id") or metadata.get("source_run_id")
    if source_run_id:
        try:
            source_run = db.get_run(str(source_run_id))
            if source_run.get("project_id") == project_id:
                source_label = _input_artifact_label(source_run, project_id, seen)
                if source_label and source_label != "-":
                    return source_label
        except KeyError:
            pass
    input_artifacts = metadata.get("input_artifacts") if isinstance(metadata.get("input_artifacts"), dict) else {}
    candidates = [
        input_artifacts.get("source_workbook"),
        metadata.get("input_artifact_id"),
        input_artifacts.get("translation_workbook"),
    ]
    for artifact_id in candidates:
        if not artifact_id:
            continue
        try:
            artifact = db.get_artifact(str(artifact_id))
            if artifact["project_id"] == project_id:
                return _artifact_display_label(artifact)
        except KeyError:
            continue
    return "-"


def _workbook_processed_rows(path: Path) -> dict[str, int]:
    stats = {"source_rows": 0, "translated_rows": 0, "processed_rows": 0}
    try:
        wb = load_workbook(path, read_only=True, data_only=True)
        try:
            for ws in wb.worksheets:
                header_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ())
                headers = {
                    str(value).strip().lower(): index
                    for index, value in enumerate(header_row, start=1)
                    if value is not None and str(value).strip()
                }
                source_col = _first_col(headers, ["cn", "source", "original", "原文", "中文"])
                target_col = _first_col(headers, ["en", "target", "translation", "译文", "英文"])
                if source_col is None or target_col is None:
                    continue
                for row in ws.iter_rows(min_row=2, values_only=True):
                    has_source = bool(_row_cell(row, source_col))
                    has_target = bool(_row_cell(row, target_col))
                    if has_source:
                        stats["source_rows"] += 1
                    if has_target:
                        stats["translated_rows"] += 1
                    if has_source and has_target:
                        stats["processed_rows"] += 1
        finally:
            wb.close()
    except Exception:
        return stats
    return stats


def _soft_warning_count(summary: dict[str, Any]) -> int:
    total = 0
    for key in ("global_harness_quality", "project_harness_quality", "semantic_qa"):
        payload = summary.get(key) if isinstance(summary.get(key), dict) else {}
        total += int(payload.get("soft_warnings") or payload.get("warnings") or 0)
    return total


def _deliverable_provider_model(metadata: dict[str, Any], quality_summary: dict[str, Any]) -> tuple[str, str]:
    model_info = metadata.get("model") if isinstance(metadata.get("model"), dict) else {}
    if model_info.get("provider"):
        return str(model_info.get("provider") or "-"), str(model_info.get("model") or "-")
    semantic_qa = metadata.get("semantic_qa") if isinstance(metadata.get("semantic_qa"), dict) else quality_summary.get("semantic_qa", {})
    if not isinstance(semantic_qa, dict):
        return "-", "-"
    status = str(semantic_qa.get("status") or "")
    if status == "skipped_no_key":
        return "rules-only", "-"
    return str(semantic_qa.get("provider") or "-"), str(semantic_qa.get("model") or "-")


def _safe_delivery_name(name: str) -> str:
    return safe_delivery_name(name)


def _delivery_file(kind: str, path: Path) -> dict[str, str]:
    return {"kind": kind, "filename": path.name, "path": str(path)}


def _artifact_delivery_file(kind: str, artifact: dict[str, Any]) -> dict[str, str]:
    path = Path(str(artifact.get("path") or ""))
    return {
        "kind": kind,
        "filename": path.name,
        "path": str(path),
        "artifact_id": str(artifact.get("id") or ""),
        "download_url": f"/api/artifacts/{artifact['id']}/download",
    }


def _expected_delivery_file(kind: str, path: Path) -> dict[str, str]:
    return {"kind": kind, "filename": path.name, "path": ""}


def _write_empty_workbook(path: Path, headers: list[str], note: str) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Delivery"
    ws.append(headers)
    ws.append(["", note, ""])
    wb.save(path)
    wb.close()


def _latest_artifact(project_id: str, role: str | None = None, kind: str | None = None) -> dict[str, Any] | None:
    artifacts = db.list_artifacts(project_id=project_id, role=role)
    if kind:
        artifacts = [artifact for artifact in artifacts if artifact["kind"] == kind]
    return artifacts[0] if artifacts else None


def _read_glossary_rows(
    path: Path,
    sheet: str | None = None,
    term_key_column: str | None = None,
    source_column: str | None = None,
    target_column: str | None = None,
    target_alt_column: str | None = None,
    category_column: str | None = None,
    note_column: str | None = None,
    language: str = "en",
    limit: int | None = 100,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    language = require_supported_language(language)
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb[sheet] if sheet else wb[wb.sheetnames[0]]
        headers = [str(cell.value or "").strip() for cell in next(ws.iter_rows(min_row=1, max_row=1))]
        normalized = {header.lower(): index for index, header in enumerate(headers) if header}
        term_key_idx = _column_index(normalized, term_key_column, ["id", "key", "编号", "序号"], required=False)
        source_idx = _column_index(normalized, source_column, ["source", "original", "cn", "zh", "chinese", "term", "原文", "中文", "术语"])
        target_idx = _column_index(normalized, target_column, target_aliases(language))
        target_alt_idx = _column_index(normalized, target_alt_column, alt_aliases(language), required=False)
        category_idx = _column_index(normalized, category_column, ["category", "type", "分类", "类别", "类型"], required=False)
        note_idx = _column_index(normalized, note_column, ["note", "notes", "comment", "备注"], required=False)
        rows = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            if limit is not None and len(rows) >= limit:
                break
            source = _value_at(row, source_idx)
            target = _value_at(row, target_idx)
            if not source and not target:
                continue
            rows.append(
                {
                    "term_key": _value_at(row, term_key_idx) if term_key_idx is not None else "",
                    "source": source,
                    "target": target,
                    "target_alt": _value_at(row, target_alt_idx) if target_alt_idx is not None else "",
                    "category": _value_at(row, category_idx) if category_idx is not None else "",
                    "note": _value_at(row, note_idx) if note_idx is not None else "",
                }
            )
        return rows, {
            "term_key": headers[term_key_idx] if term_key_idx is not None else "",
            "source": headers[source_idx],
            "target": headers[target_idx],
            "target_alt": headers[target_alt_idx] if target_alt_idx is not None else "",
            "category": headers[category_idx] if category_idx is not None else "",
            "note": headers[note_idx] if note_idx is not None else "",
        }
    finally:
        wb.close()


def _column_index(normalized_headers: dict[str, int], explicit: str | None, candidates: list[str], required: bool = True) -> int | None:
    if explicit:
        hit = normalized_headers.get(explicit.strip().lower())
        if hit is not None:
            return hit
        if required:
            raise KeyError(f"column not found: {explicit}")
    for candidate in candidates:
        hit = normalized_headers.get(candidate.lower())
        if hit is not None:
            return hit
    if required:
        raise KeyError(f"none of columns found: {', '.join(candidates)}")
    return None


def _value_at(row: tuple[Any, ...], index: int | None) -> str:
    if index is None or index < 0 or index >= len(row):
        return ""
    value = row[index]
    return "" if value is None else str(value).strip()

__all__ = [name for name in globals() if not name.startswith("__")]
