from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from . import db
from .workflow.common import run_dir
from .workflow.jsonl_helpers import read_jsonl


def _compact(value: Any, limit: int = 240) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_text_preview(path: Path, limit: int = 600) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:limit]
    except Exception:
        return ""


def _artifact_readability(artifact_id: Any) -> dict[str, Any]:
    if not artifact_id:
        return {"readable": False, "reason": "缺少文件记录"}
    try:
        artifact = db.get_artifact(str(artifact_id))
    except KeyError:
        return {"readable": False, "reason": "文件记录不存在"}
    path = Path(artifact["path"])
    if not path.exists():
        return {"readable": False, "reason": "文件不存在"}
    try:
        with path.open("rb") as fh:
            fh.read(1)
    except OSError as exc:
        return {"readable": False, "reason": f"文件不可读：{exc}"}
    return {"readable": True, "size": artifact.get("size", 0), "path": str(path)}


def _included_in_ai(material: dict[str, Any]) -> bool:
    status = str(material.get("status") or "")
    if not str(material.get("excerpt") or "").strip():
        return False
    return status.startswith(("parsed", "vision_analyzed"))


def _workpack_summary(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {"available": False, "rows": 0, "term_hit_rows": 0, "estimated_batches": 0, "samples": []}
    rows = read_jsonl(path)
    samples: list[dict[str, Any]] = []
    term_hit_rows = 0
    for row in rows:
        term_hits = row.get("term_hits") or []
        if term_hits:
            term_hit_rows += 1
        if len(samples) < 3:
            samples.append(
                {
                    "id": row.get("id"),
                    "source": _compact(row.get("source")),
                    "term_hits_count": len(term_hits) if isinstance(term_hits, list) else 0,
                }
            )
    return {"available": True, "rows": len(rows), "term_hit_rows": term_hit_rows, "estimated_batches": 0, "samples": samples}


def project_ai_input_summary(project_id: str) -> dict[str, Any]:
    project = db.get_project(project_id)
    artifacts = db.list_artifacts(project_id=project_id, include_superseded=True)
    packet_artifact = next((item for item in artifacts if item["kind"] == "project_material_packet"), None)
    packet = _read_json(Path(packet_artifact["path"])) if packet_artifact else {}
    materials: list[dict[str, Any]] = []
    for material in packet.get("materials") or []:
        if not isinstance(material, dict):
            continue
        readability = _artifact_readability(material.get("artifact_id"))
        materials.append(
            {
                "artifact_id": material.get("artifact_id"),
                "filename": material.get("filename") or material.get("label") or material.get("name") or "",
                "material_type": material.get("material_type") or material.get("type") or "",
                "status": material.get("status") or "",
                "included_in_ai": _included_in_ai(material),
                "readable": bool(readability.get("readable")),
                "readable_reason": readability.get("reason") or "",
                "chars": material.get("chars"),
                "rows": material.get("rows"),
                "pages": material.get("pages"),
                "truncated": bool(material.get("truncated")),
                "warning": material.get("warning") or "",
                "excerpt": _compact(material.get("excerpt") or material.get("note") or material.get("text") or material.get("summary") or "", 500),
            }
        )
    return {
        "project_id": project_id,
        "project_name": project.get("name"),
        "analysis": {
            "summary": packet.get("summary") or {"total": len(materials), "parsed": len(materials)},
            "materials": materials,
        },
    }


def run_ai_input_summary(run_id: str) -> dict[str, Any]:
    run = db.get_run(run_id)
    artifacts = db.list_artifacts(run_id=run_id, include_superseded=True)
    workpack_artifact = next((item for item in artifacts if item["kind"] == "translation_workpack"), None)
    workpack_path = Path(workpack_artifact["path"]) if workpack_artifact else run_dir(run_id) / "translation" / "translation_workpack.jsonl"
    prompt_artifact = next((item for item in artifacts if item["kind"] == "prompt_snapshot"), None)
    prompt_path = Path(prompt_artifact["path"]) if prompt_artifact else run_dir(run_id) / "translation" / "snapshots" / "compiled_project_harness_prompt.txt"
    prompt_preview = _read_text_preview(prompt_path)
    workpack = _workpack_summary(workpack_path)
    batch_size = int((run.get("metadata") or {}).get("batch_size") or 90)
    if workpack["rows"]:
        workpack["estimated_batches"] = max(1, math.ceil(int(workpack["rows"]) / max(1, batch_size)))
    return {
        "run_id": run_id,
        "project_id": run["project_id"],
        "language": run.get("language"),
        "workpack": workpack,
        "prompt": {"available": bool(prompt_preview), "preview": prompt_preview, "chars": len(prompt_preview)},
    }


def announcement_ai_input_summary(task_id: str) -> dict[str, Any]:
    task = db.get_announcement_task(task_id)
    metadata = task.get("metadata") or {}
    languages: list[dict[str, Any]] = []
    warnings: list[str] = []
    workpack_ids = metadata.get("workpack_artifact_ids") or {}
    prompt_ids = metadata.get("prompt_artifact_ids") or {}
    if not isinstance(workpack_ids, dict):
        workpack_ids = {}
    if not isinstance(prompt_ids, dict):
        prompt_ids = {}

    for language, artifact_id in sorted(workpack_ids.items()):
        try:
            workpack_artifact = db.get_artifact(str(artifact_id))
        except KeyError:
            warnings.append(f"{language}: 翻译准备包已失效，请在 STEP 6 重新生成")
            continue
        prompt_artifact = None
        prompt_artifact_id = prompt_ids.get(language)
        if prompt_artifact_id:
            try:
                prompt_artifact = db.get_artifact(str(prompt_artifact_id))
            except KeyError:
                warnings.append(f"{language}: 提示词快照已失效，请在 STEP 6 重新生成")
        workpack = _workpack_summary(Path(workpack_artifact["path"]))
        prompt_preview = _read_text_preview(Path(prompt_artifact["path"])) if prompt_artifact else ""
        languages.append(
            {
                "language": language,
                "workpack_rows": workpack["rows"],
                "term_hits": workpack["term_hit_rows"],
                "samples": workpack["samples"],
                "prompt_preview": prompt_preview,
                "prompt_chars": len(prompt_preview),
            }
        )

    status = "ready" if languages else "not_prepared"
    message = "已生成翻译准备包，可查看将发送给 AI 的内容" if languages else "尚未生成翻译准备包；请先在 STEP 6 点击生成翻译准备包"
    return {
        "task_id": task_id,
        "project_id": task["project_id"],
        "status": status,
        "message": message,
        "warnings": warnings,
        "segments": metadata.get("segments") or 0,
        "lookup": metadata.get("lookup_summary") or {},
        "languages": languages,
    }
