from __future__ import annotations

# ruff: noqa: F403,F405

from .common import *

class UserFacingWorkflowError(RuntimeError):
    pass


def _friendly_unsupported_language_file_message(suffix: str) -> str:
    ext = (suffix or "").lower() or "unknown"
    return (
        f"\u5f53\u524d\u5165\u53e3\u4e0d\u652f\u6301 {ext} \u6587\u4ef6\u3002"
        "\u8bed\u8a00\u5305\u7ffb\u8bd1\u8bf7\u4e0a\u4f20 XLSX/XLS/CSV \u8bed\u8a00\u8868\uff1b"
        "TXT/DOCX \u957f\u6587\u672c\u8bf7\u4f7f\u7528\u516c\u544a\u7ffb\u8bd1/\u5916\u6587\u672c\u6d41\u7a0b\u3002"
    )


def user_facing_error(exc: BaseException | str) -> str:
    text = str(exc).strip()
    lower = text.lower()
    if not text:
        return "\u64cd\u4f5c\u5931\u8d25\uff0c\u8bf7\u91cd\u8bd5\u3002"
    if isinstance(exc, UserFacingWorkflowError):
        return text
    unsupported = re.search(r"unsupported file format:\s*(\.\w+)", text, re.I)
    if unsupported:
        return _friendly_unsupported_language_file_message(unsupported.group(1))
    if "another long-text ai job is active" in lower:
        return "\u5df2\u6709\u4e00\u4e2a\u957f\u6587\u672c AI \u4efb\u52a1\u6b63\u5728\u8fd0\u884c\uff0c\u8bf7\u7b49\u5f85\u5b8c\u6210\u6216\u5148\u53d6\u6d88\u540e\u518d\u7ee7\u7eed\u3002"
    if "api_key" in lower or "api key" in lower:
        return text
    if any(marker in text for marker in ["Traceback", "File \", line", "command failed", "python.exe", "run_translation_harness.py"]):
        return "\u672c\u5730 workflow \u6267\u884c\u5931\u8d25\uff0c\u8bf7\u68c0\u67e5\u8f93\u5165\u6587\u4ef6\u683c\u5f0f\u548c\u5f53\u524d\u6b65\u9aa4\u662f\u5426\u5339\u914d\u3002"
    if re.search(r"[A-Za-z]:[\\/]", text):
        return "\u64cd\u4f5c\u5931\u8d25\uff0c\u8bf7\u68c0\u67e5\u6587\u4ef6\u683c\u5f0f\u548c\u6d41\u7a0b\u6b65\u9aa4\u662f\u5426\u5339\u914d\u3002"
    return text if len(text) <= 240 else text[:237] + "..."


def _append_subprocess_log(run_id: str, args: list[str], proc: subprocess.CompletedProcess[str]) -> None:
    log_dir = run_dir(run_id) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "subprocess.log"
    payload = [
        f"[{db.now_iso()}] {' '.join(args)}",
        f"returncode={proc.returncode}",
    ]
    if proc.stdout:
        payload.append("[stdout]")
        payload.append(proc.stdout.strip())
    if proc.stderr:
        payload.append("[stderr]")
        payload.append(proc.stderr.strip())
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(payload).strip() + "\n\n")


def _safe_subprocess_event_output(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return ""
    if any(marker in stripped for marker in ["Traceback", "File \", line", "command failed", "python.exe", "run_translation_harness.py"]):
        return "\u672c\u5730 workflow \u8fd4\u56de\u4e86\u9519\u8bef\u8be6\u60c5\uff0c\u5df2\u5199\u5165\u8fd0\u884c\u65e5\u5fd7\u3002"
    return stripped if len(stripped) <= 1000 else stripped[:997] + "..."

def copy_upload(project_id: str, source_path: Path, label: str, kind: str) -> dict[str, Any]:
    destination_dir = project_dir(project_id) / "uploads"
    destination = destination_dir / source_path.name
    shutil.copy2(source_path, destination)
    return db.add_artifact(project_id, label=label, path=destination, kind=kind)


def run_subprocess(args: list[str], cwd: Path, run_id: str) -> subprocess.CompletedProcess[str]:
    db.add_event(run_id, "running local workflow step")
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    proc = subprocess.run(
        args,
        cwd=str(cwd),
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    _append_subprocess_log(run_id, args, proc)
    if proc.stdout:
        safe_stdout = _safe_subprocess_event_output(proc.stdout)
        if safe_stdout:
            db.add_event(run_id, safe_stdout)
    if proc.stderr:
        db.add_event(run_id, "local workflow emitted warnings; details were written to the run log", level="warn")
    if proc.returncode != 0:
        raise UserFacingWorkflowError(user_facing_error(proc.stderr or proc.stdout or f"command failed ({proc.returncode})"))
    return proc


def run_subprocess_allow_failure(args: list[str], cwd: Path, run_id: str) -> subprocess.CompletedProcess[str]:
    db.add_event(run_id, "running local workflow step")
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    proc = subprocess.run(
        args,
        cwd=str(cwd),
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    _append_subprocess_log(run_id, args, proc)
    if proc.stdout:
        safe_stdout = _safe_subprocess_event_output(proc.stdout)
        if safe_stdout:
            db.add_event(run_id, safe_stdout)
    if proc.stderr:
        db.add_event(run_id, "local workflow emitted warnings; details were written to the run log", level="warn")
    return proc


def parse_key_output(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in text.splitlines():
        if "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        result[key.strip()] = value.strip()
    return result

__all__ = [name for name in globals() if not name.startswith("__")]
