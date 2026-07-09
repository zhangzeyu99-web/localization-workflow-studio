from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


RUNNER_RE = re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}) (?P<event>START|DONE) (?P<phase>[a-zA-Z0-9_-]+)")
LONG_TASK_REVIEW_SECONDS = 3600


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_optional_json(path_value: str | None) -> dict[str, Any]:
    if not path_value:
        return {"exists": False}
    path = Path(path_value)
    data = read_json(path)
    if not data:
        return {"exists": False, "path": str(path)}
    data.setdefault("exists", True)
    data.setdefault("path", str(path))
    return data


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def seconds_to_hms(seconds: float | int | None) -> str:
    if seconds is None:
        return "n/a"
    seconds = int(seconds)
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def parse_runner_log(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"phases": [], "total_seconds": None, "total_duration": "n/a"}
    starts: dict[str, datetime] = {}
    phases: list[dict[str, Any]] = []
    first_ts: datetime | None = None
    last_ts: datetime | None = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = RUNNER_RE.search(line.strip())
        if not match:
            if " COMPLETE" in line:
                ts = parse_time(line.split(" ", 1)[0])
                last_ts = ts
            continue
        ts = parse_time(match.group("ts"))
        first_ts = first_ts or ts
        last_ts = ts
        phase = match.group("phase")
        event = match.group("event")
        if event == "START":
            starts[phase] = ts
        elif phase in starts:
            duration = (ts - starts[phase]).total_seconds()
            phases.append({"phase": phase, "start": starts[phase].isoformat(), "end": ts.isoformat(), "seconds": duration, "duration": seconds_to_hms(duration)})
    total_seconds = (last_ts - first_ts).total_seconds() if first_ts and last_ts else None
    return {"phases": phases, "total_seconds": total_seconds, "total_duration": seconds_to_hms(total_seconds)}


def classify_reason(reason: str) -> str:
    lower = reason.lower()
    if any(token in lower for token in ["missing", "omitted", "lost", "not preserved"]):
        return "omission_or_missing_meaning"
    if any(token in lower for token in ["glossary", "term", "inconsistent", "series"]):
        return "terminology"
    if any(token in lower for token in ["placeholder", "number", "value", "percent", "format", "token"]):
        return "structure_or_numeric"
    if any(token in lower for token in ["malformed", "grammar", "unnatural", "awkward"]):
        return "fluency_or_grammar"
    if any(token in lower for token in ["mistranslat", "wrong", "instead of", "means"]):
        return "mistranslation"
    if any(token in lower for token in ["english residue", "residue", "latin script"]):
        return "residue_or_script"
    return "context_or_style"


def aggregate_proof_issues(proof: dict[str, Any]) -> dict[str, Any]:
    issues = proof.get("issues") or []
    by_lang = Counter(str(row.get("lang", "")) for row in issues if row.get("lang"))
    by_category = Counter(classify_reason(str(row.get("reason", ""))) for row in issues)
    return {
        "issue_rows_sampled": len(issues),
        "by_language": dict(sorted(by_lang.items())),
        "by_reason_category": dict(sorted(by_category.items())),
    }


def aggregate_qa(qa: dict[str, Any]) -> dict[str, Any]:
    issues = qa.get("issues") or []
    hard = [row for row in issues if row.get("severity") == "hard"]
    warn = [row for row in issues if row.get("severity") == "warn"]
    return {
        "summary": qa.get("summary", {}),
        "hard_by_type": dict(Counter(str(row.get("type", "")) for row in hard)),
        "warn_by_type": dict(Counter(str(row.get("type", "")) for row in warn)),
        "hard_count": len(hard),
        "warning_count": len(warn),
        "file_stats": qa.get("files", []),
    }


def infer_gate_status(gate: dict[str, Any], *, verified_key: str | None = None) -> str:
    explicit = str(gate.get("status") or "").strip().lower()
    if explicit in {"passed", "skipped", "waived", "failed"}:
        return explicit
    if not gate.get("exists"):
        return "skipped"
    hard = gate.get("hard_blockers")
    verified = gate.get(verified_key) if verified_key else gate.get("ok_to_apply")
    if hard == 0 and verified is not False:
        return "passed"
    if isinstance(hard, int) and hard > 0:
        return "failed"
    if verified is False:
        return "failed"
    return "skipped"


def gate_skip_suffix(gate: dict[str, Any], status: str) -> str:
    if status not in {"skipped", "waived"}:
        return ""
    reason = gate.get("reason") or gate.get("skip_reason") or "not provided"
    alternative = gate.get("alternative_check") or "not provided"
    return f", reason={reason}, alternative_check={alternative}"


def render_long_task_review(
    timing: dict[str, Any],
    top_phase: dict[str, Any],
    *,
    cache_lint_status: str,
    readback_gate_status: str,
) -> str:
    total_seconds = timing.get("total_seconds")
    if not isinstance(total_seconds, (int, float)):
        return "- status=not_measured, threshold=3600s, action=补齐 runner 耗时后再判断是否触发长任务复盘。"
    if total_seconds < LONG_TASK_REVIEW_SECONDS:
        return (
            f"- status=not_triggered, threshold=3600s, total={seconds_to_hms(total_seconds)}，"
            "未超过一小时，不需要额外长任务复盘。"
        )
    return (
        f"- status=triggered, threshold=3600s, total={seconds_to_hms(total_seconds)}, "
        f"largest_phase={top_phase.get('phase', 'n/a')}:{top_phase.get('duration', 'n/a')}, "
        f"cache_lint={cache_lint_status}, readback_gate={readback_gate_status}。\n"
        "- review_focus=判断耗时是否只是任务规模导致；检查失败/重试/跳过门禁/意外修复；重复出现或可机器检查的问题沉淀为测试、gate 或文档，偶发问题只记录。"
    )


def inspect_delivery(delivery_dir: Path) -> dict[str, Any]:
    if not delivery_dir.exists():
        return {"exists": False, "files": []}
    files = []
    for path in sorted(p for p in delivery_dir.iterdir() if p.is_file()):
        files.append({"name": path.name, "bytes": path.stat().st_size, "last_write": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")})
    return {"exists": True, "file_count": len(files), "files": files}


def inspect_log(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False}
    raw = path.read_bytes()
    null_bytes = raw.count(b"\x00")
    return {
        "exists": True,
        "bytes": len(raw),
        "null_bytes": null_bytes,
        "likely_utf16_or_binary_stdout": null_bytes > max(100, len(raw) // 20),
        "line_count": raw.count(b"\n") + 1,
    }


def inspect_feishu(path: Path) -> dict[str, Any]:
    raw = read_json(path)
    if not raw:
        return {"exists": False}
    try:
        payload = json.loads(raw.get("stdout") or "{}")
        messages = payload.get("data", {}).get("messages") or []
        message = messages[0] if messages else {}
        content = str(message.get("content", ""))
        required = ["QA hard blocker=0"]
        return {
            "exists": True,
            "returncode": raw.get("returncode"),
            "message_id": message.get("message_id"),
            "msg_type": message.get("msg_type"),
            "content_len": len(content),
            "required_missing": [token for token in required if token not in content],
        }
    except Exception as exc:  # noqa: BLE001
        return {"exists": True, "parse_error": str(exc), "returncode": raw.get("returncode")}


def build_metrics(args: argparse.Namespace) -> dict[str, Any]:
    work_dir = Path(args.work_dir)
    proof_dir = Path(args.proof_dir) if args.proof_dir else work_dir / "deep_proofread"
    qa = read_json(work_dir / "qa_summary.json")
    proof = read_json(proof_dir / "proofread_apply_summary.json")
    runner = read_json(proof_dir / "runner_status.json")
    runner_log = parse_runner_log(proof_dir / "runner.log")
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "task": args.task_name,
        "work_dir": str(work_dir),
        "proof_dir": str(proof_dir),
        "delivery_dir": args.delivery_dir,
        "runner_status": runner,
        "runner_timing": runner_log,
        "qa": aggregate_qa(qa),
        "proofread": {
            "changed_rows": proof.get("changed_rows", 0),
            "changed_cells": proof.get("changed_cells", 0),
            "issue_aggregates": aggregate_proof_issues(proof),
        },
        "delivery": inspect_delivery(Path(args.delivery_dir)) if args.delivery_dir else {"exists": False, "files": []},
        "deliver_log": inspect_log(Path(args.deliver_log)) if args.deliver_log else {"exists": False},
        "feishu_readback": inspect_feishu(Path(args.feishu_readback)) if args.feishu_readback else {"exists": False},
        "preflight": read_optional_json(args.preflight_metrics),
        "cache_lint": read_optional_json(args.cache_lint),
        "readback_gate": read_optional_json(args.readback_gate),
    }


def render_report(metrics: dict[str, Any]) -> str:
    qa_summary = metrics.get("qa", {}).get("summary") or {}
    timing = metrics.get("runner_timing") or {}
    phases = timing.get("phases") or []
    top_phase = max(phases, key=lambda row: row.get("seconds", 0), default={})
    delivery = metrics.get("delivery") or {}
    proof = metrics.get("proofread") or {}
    feishu = metrics.get("feishu_readback") or {}
    preflight = metrics.get("preflight") or {"exists": False}
    cache_lint = metrics.get("cache_lint") or {"exists": False}
    readback_gate = metrics.get("readback_gate") or {"exists": False}
    preflight_status = infer_gate_status(preflight)
    cache_lint_status = infer_gate_status(cache_lint)
    readback_gate_status = infer_gate_status(readback_gate, verified_key="readback_verified")
    long_task_review = render_long_task_review(
        timing,
        top_phase,
        cache_lint_status=cache_lint_status,
        readback_gate_status=readback_gate_status,
    )
    phase_lines = "\n".join(f"- {row['phase']}: {row['duration']}" for row in phases) or "- n/a"
    file_lines = "\n".join(f"- {row['name']}: {row['bytes']} bytes" for row in delivery.get("files", [])) or "- n/a"
    category_lines = "\n".join(
        f"- {name}: {count}" for name, count in proof.get("issue_aggregates", {}).get("by_reason_category", {}).items()
    ) or "- n/a"
    gate_lines = [
        (
            "- preflight: "
            f"unique={preflight.get('unique_items', 'n/a')}, "
            f"estimated_cells={preflight.get('estimated_target_cells', 'n/a')}, "
            f"large_pack={preflight.get('large_pack', 'n/a')}, "
            f"recommended_shards={preflight.get('recommended_translation_shards', 'n/a')}, "
            f"status={preflight_status}{gate_skip_suffix(preflight, preflight_status)}"
            if preflight.get("exists")
            else f"- preflight: status={preflight_status}{gate_skip_suffix(preflight, preflight_status)}"
        ),
        (
            "- cache-lint: "
            f"hard={cache_lint.get('hard_blockers', 'n/a')}, "
            f"ok_to_apply={cache_lint.get('ok_to_apply', 'n/a')}, "
            f"status={cache_lint_status}{gate_skip_suffix(cache_lint, cache_lint_status)}"
            if cache_lint.get("exists")
            else f"- cache-lint: status={cache_lint_status}{gate_skip_suffix(cache_lint, cache_lint_status)}"
        ),
        (
            "- readback-gate: "
            f"hard={readback_gate.get('hard_blockers', 'n/a')}, "
            f"verified={readback_gate.get('readback_verified', 'n/a')}, "
            f"status={readback_gate_status}{gate_skip_suffix(readback_gate, readback_gate_status)}"
            if readback_gate.get("exists")
            else f"- readback-gate: status={readback_gate_status}{gate_skip_suffix(readback_gate, readback_gate_status)}"
        ),
    ]
    gate_section = "\n".join(gate_lines)
    task = metrics.get("task", "多语言任务")
    return f"""# {task}大语言包流程复盘
## 结论

本次流程复盘聚焦耗时、门禁和交付闭环。真实项目中，语义翻译由 API 或明确触发的深度校对 agent 承担；本地脚本只负责拆分计划、确定性 QA、写入前阻断、交付读回和复盘证据，不再使用 Google 或其他外部机翻做初译。

## 关键证据

- 唯一内容数: {qa_summary.get('unique_items', 'n/a')}
- 已翻译内容数: {qa_summary.get('translated_items', 'n/a')}
- hard blocker: {qa_summary.get('hard_blockers', 'n/a')}
- warning: {qa_summary.get('warnings', 'n/a')}
- 深度校对修改: {proof.get('changed_rows', 0)} 行 / {proof.get('changed_cells', 0)} 单元格
- 额外结构修复: {qa_summary.get('structural_hotfix_rows_after_deep_proofread', 0)} 行 / {qa_summary.get('structural_hotfix_cells_after_deep_proofread', 0)} 单元格
- 最终修改合计: {qa_summary.get('final_changed_cells_including_structural_hotfix', proof.get('changed_cells', 0))} 单元格
- runner 总耗时: {timing.get('total_duration', 'n/a')}
- 最大耗时阶段: {top_phase.get('phase', 'n/a')}: {top_phase.get('duration', 'n/a')}

## 阶段耗时

{phase_lines}

## 长任务复盘触发

{long_task_review}

## 校对问题结构

{category_lines}

## 交付验证

- 交付目录存在: {delivery.get('exists')}
- 交付文件数: {delivery.get('file_count', 0)}
{file_lines}

## 流程问题

- 写入 workbook/docx 前必须先跑 cache-lint，否则会在大文件保存后才暴露空译文、中文残留、占位符丢失和数字丢失。
- 深度校对不能直接改交付文件；subagent 只能输出 JSONL 建议，由主控合并、跑结构 QA 后再写回。
- 交付目录必须只保留最终文件和 QA 摘要，不允许混入 manifest、workpack、response、jsonl、log 等过程文件。
- 飞书或外部汇报必须区分“本地写入成功”和“远端读回成功”。

## 执行门禁结果

{gate_section}

## 固化优化

- 新增 preflight: 识别大语言包、目标语言数、长文本和推荐分片。
- 新增 API 策略 manifest: 只记录 host/path/model，不写入 API key。
- 新增 cache-lint: 翻译缓存进入 workbook/docx 前先拦截 hard blocker。
- 新增 readback-gate: 最终交付目录读回检查，阻断过程文件和空目标列。
- 新增 retro: 汇总耗时、修改量、QA、交付和远端读回证据。

## 飞书读回

- message_id: {feishu.get('message_id', 'n/a')}
- msg_type: {feishu.get('msg_type', 'n/a')}
- content_len: {feishu.get('content_len', 'n/a')}
- required_missing: {feishu.get('required_missing', [])}
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a large text multilingual workflow retrospective from task artifacts.")
    parser.add_argument("--task-name", required=True)
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--proof-dir")
    parser.add_argument("--delivery-dir", default="")
    parser.add_argument("--deliver-log", default="")
    parser.add_argument("--feishu-readback", default="")
    parser.add_argument("--preflight-metrics", default="")
    parser.add_argument("--cache-lint", default="")
    parser.add_argument("--readback-gate", default="")
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    metrics = build_metrics(args)
    metrics_path = out_dir / "large_text_multilingual_retro_metrics.json"
    report_path = out_dir / "large_text_multilingual_retro_report.md"
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(render_report(metrics), encoding="utf-8")
    print(json.dumps({"metrics": str(metrics_path), "report": str(report_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
