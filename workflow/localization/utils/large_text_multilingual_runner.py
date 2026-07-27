from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from utils.large_text_multilingual_gate import parse_langs, preflight
from utils.source_reference import normalize_source_mode


WORKFLOW_VERSION = "large_text_multilingual_v1"
MANIFEST_NAME = "large_text_multilingual_manifest.json"
DEFAULT_CHAT_SUFFIXES = ["/v1/chat/completions", "/chat/completions"]
RISK_FLAGS = [
    "long_text",
    "placeholder_dense",
    "term_dense",
    "tm_conflict",
    "qa_failed_once",
    "model_uncertain",
]


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _flatten_settings(data: dict[str, Any]) -> dict[str, Any]:
    for key in ("lws_settings", "openai", "provider", "translation_provider"):
        nested = data.get(key)
        if isinstance(nested, dict):
            merged = dict(nested)
            for override in ("base_url", "model", "provider", "protocol"):
                if data.get(override) not in (None, ""):
                    merged[override] = data[override]
            return merged
    return data


def load_sanitized_relay_config(path: Path | None) -> dict[str, Any]:
    if not path:
        return {
            "source": "",
            "configured": False,
            "base_url_host": "",
            "base_url_path": "",
            "model": "",
        }
    data = _flatten_settings(read_json(path))
    base_url = str(data.get("base_url") or "").strip()
    parsed = urlparse(base_url)
    return {
        "source": str(path),
        "configured": bool(base_url and data.get("model")),
        "provider": str(data.get("provider") or "openai-chat"),
        "protocol": str(data.get("protocol") or "chat.completions"),
        "base_url_host": parsed.netloc,
        "base_url_path": parsed.path.rstrip("/"),
        "model": str(data.get("model") or ""),
    }


def build_api_strategy(relay: dict[str, Any], preflight_result: dict[str, Any]) -> dict[str, Any]:
    return {
        "mode": "relay_openai_compatible" if relay.get("configured") else "unconfigured_openai_compatible",
        "provider": relay.get("provider") or "openai-chat",
        "model": relay.get("model") or "",
        "base_url_host": relay.get("base_url_host") or "",
        "base_url_path": relay.get("base_url_path") or "",
        "smoke_required": True,
        "smoke_rows": 20,
        "chat_endpoint_suffixes": DEFAULT_CHAT_SUFFIXES,
        "translation_owner": "api",
        "semantic_only": True,
        "deterministic_qa_owner": "local_scripts",
        "shards": preflight_result.get("recommended_translation_shards", 1),
        "bucket_policy": {
            "short_ui_max_rows": 120,
            "normal_max_rows": 60,
            "long_text_max_rows": 5,
            "long_text_starts_with_main_translation": True,
        },
        "retry_policy": {
            "max_attempts_per_batch": 3,
            "on_provider_500": "halve_batch_then_retry",
            "on_timeout": "halve_batch_then_retry",
            "on_json_error": "retry_once_then_split",
            "cache_successful_keys": True,
        },
    }


def build_subagent_strategy(proofread_mode: str, preflight_result: dict[str, Any]) -> dict[str, Any]:
    mode = proofread_mode.lower()
    if mode not in {"basic", "sampled", "full"}:
        raise ValueError("proofread_mode must be one of: basic, sampled, full")
    if mode == "basic":
        return {
            "enabled": False,
            "mode": "not_triggered",
            "trigger": "explicit_deep_proofread_not_requested",
            "write_permission": "forbidden",
            "output_contract": "jsonl_review_suggestions_only",
            "owner": "none",
            "risk_flags": RISK_FLAGS,
        }

    shards = int(preflight_result.get("recommended_deep_proofread_shards") or preflight_result.get("recommended_translation_shards") or 2)
    parallel_agents = max(2, min(4, shards))
    scope = "all_rows" if mode == "full" else "high_risk_rows_plus_10_percent_low_risk_sample"
    return {
        "enabled": True,
        "mode": mode,
        "trigger": "explicit_deep_proofread_requested",
        "scope": scope,
        "parallel_agents": parallel_agents,
        "fresh_agent_per_batch": True,
        "fork_context": False,
        "write_permission": "forbidden",
        "output_contract": "jsonl_review_suggestions_only",
        "controller_merge_required": True,
        "risk_flags": RISK_FLAGS,
        "batch_policy": {
            "short_ui_rows": "30-80",
            "long_text_rows": "1-5",
            "no_overlapping_ids": True,
        },
    }


def critical_path_for(proofread_mode: str) -> list[str]:
    phases = [
        "preflight",
        "api_smoke",
        "api_translate",
        "incremental_cache_lint",
    ]
    if proofread_mode in {"sampled", "full"}:
        phases.extend(["subagent_review", "controller_merge", "final_cache_lint"])
    phases.extend(["apply_dry_run", "write_outputs", "readback_gate", "retro_metrics"])
    return phases


def build_manifest(
    *,
    work_dir: Path,
    items_jsonl: Path,
    source_rows_jsonl: Path | None,
    target_langs: list[str],
    workbook_count: int,
    relay_config: Path | None,
    proofread_mode: str,
    source_mode: str = "cn",
) -> dict[str, Any]:
    work_dir.mkdir(parents=True, exist_ok=True)
    source_mode = normalize_source_mode(source_mode)
    detected_modes = {
        normalize_source_mode(json.loads(line).get("source_mode", "cn"))
        for line in items_jsonl.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    }
    if len(detected_modes) > 1:
        raise ValueError(f"items_jsonl contains mixed source modes: {sorted(detected_modes)}")
    detected_source_mode = next(iter(detected_modes), "cn")
    if detected_source_mode != source_mode:
        raise ValueError(
            f"manifest source_mode {source_mode} does not match items_jsonl mode "
            f"{detected_source_mode}"
        )
    preflight_result = preflight(
        items_jsonl,
        target_langs=target_langs,
        source_rows_jsonl=source_rows_jsonl,
        workbook_count=workbook_count,
        full_proofread=proofread_mode == "full",
    )
    preflight_path = work_dir / "preflight.json"
    write_json(preflight_path, preflight_result)
    relay = load_sanitized_relay_config(relay_config)
    manifest_path = work_dir / MANIFEST_NAME
    manifest = {
        "workflow": WORKFLOW_VERSION,
        "status": "prepared",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "manifest_path": str(manifest_path),
        "work_dir": str(work_dir),
        "inputs": {
            "items_jsonl": str(items_jsonl),
            "source_rows_jsonl": str(source_rows_jsonl) if source_rows_jsonl else "",
            "target_languages": target_langs,
            "workbook_count": workbook_count,
            "proofread_mode": proofread_mode,
            "source_mode": source_mode,
        },
        "artifacts": {
            "preflight": str(preflight_path),
            "cache_lint": str(work_dir / "cache_lint.json"),
            "apply_dry_run": str(work_dir / "apply_dry_run.json"),
            "readback_gate": str(work_dir / "readback_gate.json"),
            "retro_dir": str(work_dir / "retro"),
        },
        "preflight": preflight_result,
        "api_strategy": build_api_strategy(relay, preflight_result),
        "subagent_strategy": build_subagent_strategy(proofread_mode, preflight_result),
        "critical_path": critical_path_for(proofread_mode),
        "phase_status": {
            "preflight": "done",
            "api_smoke": "pending",
            "api_translate": "pending",
            "incremental_cache_lint": "pending",
            "subagent_review": "pending" if proofread_mode in {"sampled", "full"} else "skipped",
            "controller_merge": "pending" if proofread_mode in {"sampled", "full"} else "skipped",
            "final_cache_lint": "pending" if proofread_mode in {"sampled", "full"} else "skipped",
            "apply_dry_run": "pending",
            "write_outputs": "pending",
            "readback_gate": "pending",
            "retro_metrics": "pending",
        },
    }
    write_json(manifest_path, manifest)
    return manifest


def load_manifest(path: Path) -> dict[str, Any]:
    manifest = read_json(path)
    if not manifest:
        raise FileNotFoundError(path)
    return manifest


def save_manifest(manifest: dict[str, Any]) -> None:
    manifest["updated_at"] = datetime.now().isoformat(timespec="seconds")
    write_json(Path(manifest["manifest_path"]), manifest)


def record_api_smoke(
    manifest_path: Path,
    *,
    ok: bool,
    latency_ms: int,
    schema_ok: bool,
    model_returned: str,
    endpoint_suffix: str,
    error: str,
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    manifest["api_smoke"] = {
        "ok": ok,
        "latency_ms": latency_ms,
        "schema_ok": schema_ok,
        "model_returned": model_returned,
        "endpoint_suffix": endpoint_suffix,
        "error": error,
        "recorded_at": datetime.now().isoformat(timespec="seconds"),
    }
    manifest["phase_status"]["api_smoke"] = "done" if ok and schema_ok else "failed"
    manifest["status"] = "api_smoke_passed" if ok and schema_ok else "api_smoke_failed"
    save_manifest(manifest)
    return manifest


def workflow_status(manifest: dict[str, Any]) -> dict[str, Any]:
    phase_status = manifest.get("phase_status") or {}
    next_phase = "complete"
    for phase in manifest.get("critical_path") or []:
        if phase_status.get(phase) == "pending":
            next_phase = phase
            break
    return {
        "workflow": manifest.get("workflow"),
        "status": manifest.get("status"),
        "next_phase": next_phase,
        "api_model": (manifest.get("api_strategy") or {}).get("model", ""),
        "subagent_mode": (manifest.get("subagent_strategy") or {}).get("mode", "not_triggered"),
        "subagent_enabled": (manifest.get("subagent_strategy") or {}).get("enabled", False),
    }


def write_or_print(payload: dict[str, Any], out: Path | None = None) -> None:
    if out:
        write_json(out, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Unified runner manifest for large text multilingual localization packs.")
    sub = parser.add_subparsers(dest="command", required=True)

    pack = sub.add_parser("prepare-pack", help="Extract source workbooks into a deduplicated translation pack.")
    pack.add_argument("--input", action="append", required=True, type=Path)
    pack.add_argument("--term-base", type=Path)
    pack.add_argument("--history-dir", action="append", default=[], type=Path)
    pack.add_argument("--target-langs", required=True)
    pack.add_argument("--work-dir", required=True, type=Path)
    pack.add_argument("--source-mode", choices=["cn", "cn+en", "en"], default="cn")
    pack.add_argument("--out", type=Path)

    prepare = sub.add_parser("prepare", help="Create workflow manifest and lightweight preflight artifacts.")
    prepare.add_argument("--work-dir", required=True, type=Path)
    prepare.add_argument("--items-jsonl", required=True, type=Path)
    prepare.add_argument("--source-rows-jsonl", type=Path)
    prepare.add_argument("--target-langs", required=True)
    prepare.add_argument("--workbook-count", type=int, default=1)
    prepare.add_argument("--relay-config", type=Path)
    prepare.add_argument("--proofread-mode", choices=["basic", "sampled", "full"], default="basic")
    prepare.add_argument("--source-mode", choices=["cn", "cn+en", "en"], default="cn")
    prepare.add_argument("--out", type=Path)

    smoke = sub.add_parser("record-smoke", help="Record API smoke result after a small schema/latency test.")
    smoke.add_argument("--manifest", required=True, type=Path)
    smoke.add_argument("--ok", action="store_true")
    smoke.add_argument("--latency-ms", required=True, type=int)
    smoke.add_argument("--schema-ok", action="store_true")
    smoke.add_argument("--model-returned", default="")
    smoke.add_argument("--endpoint-suffix", default="/v1/chat/completions")
    smoke.add_argument("--error", default="")
    smoke.add_argument("--out", type=Path)

    status = sub.add_parser("status", help="Print next required workflow phase.")
    status.add_argument("--manifest", required=True, type=Path)
    status.add_argument("--out", type=Path)

    run = sub.add_parser("run", help="Run extract, translate, QA, optional deep proofread, writeback, and readback.")
    run.add_argument("--input", action="append", required=True, type=Path)
    run.add_argument("--term-base", type=Path)
    run.add_argument("--history-dir", action="append", default=[], type=Path)
    run.add_argument("--target-langs", required=True)
    run.add_argument("--task-dir", required=True, type=Path)
    run.add_argument("--relay-config", required=True, type=Path)
    run.add_argument("--proofread-mode", choices=["basic", "sampled", "full"], default="basic")
    run.add_argument("--delivery-dir", type=Path)
    run.add_argument("--batch-size", type=int, default=60)
    run.add_argument("--workers", type=int, default=4)
    run.add_argument("--source-mode", choices=["cn", "cn+en", "en"], default="cn")
    run.add_argument("--out", type=Path)

    args = parser.parse_args(argv)
    if args.command == "prepare-pack":
        from dataclasses import asdict

        from utils.large_text_multilingual_pack import prepare_pack

        result = prepare_pack(
            inputs=args.input,
            term_base=args.term_base,
            history_dirs=args.history_dir,
            target_langs=parse_langs(args.target_langs),
            work_dir=args.work_dir,
            source_mode=args.source_mode,
        )
        payload = asdict(result)
        write_or_print({key: str(value) if isinstance(value, Path) else value for key, value in payload.items()}, args.out)
        return 0
    if args.command == "prepare":
        manifest = build_manifest(
            work_dir=args.work_dir,
            items_jsonl=args.items_jsonl,
            source_rows_jsonl=args.source_rows_jsonl,
            target_langs=parse_langs(args.target_langs),
            workbook_count=args.workbook_count,
            relay_config=args.relay_config,
            proofread_mode=args.proofread_mode,
            source_mode=args.source_mode,
        )
        payload = {"manifest": manifest["manifest_path"], "status": workflow_status(manifest)}
        write_or_print(payload, args.out)
        return 0
    if args.command == "record-smoke":
        manifest = record_api_smoke(
            args.manifest,
            ok=args.ok,
            latency_ms=args.latency_ms,
            schema_ok=args.schema_ok,
            model_returned=args.model_returned,
            endpoint_suffix=args.endpoint_suffix,
            error=args.error,
        )
        payload = {"manifest": manifest["manifest_path"], "status": workflow_status(manifest)}
        write_or_print(payload, args.out)
        return 0 if manifest["status"] == "api_smoke_passed" else 1
    if args.command == "status":
        write_or_print(workflow_status(load_manifest(args.manifest)), args.out)
        return 0
    if args.command == "run":
        from dataclasses import asdict

        from utils.large_text_multilingual_pipeline import run_pipeline

        result = run_pipeline(
            inputs=args.input,
            term_base=args.term_base,
            history_dirs=args.history_dir,
            target_langs=parse_langs(args.target_langs),
            task_dir=args.task_dir,
            relay_config=args.relay_config,
            proofread_mode=args.proofread_mode,
            delivery_dir=args.delivery_dir,
            batch_size=args.batch_size,
            workers=args.workers,
            source_mode=args.source_mode,
        )
        payload = asdict(result)
        write_or_print({key: str(value) if isinstance(value, Path) else value for key, value in payload.items()}, args.out)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
