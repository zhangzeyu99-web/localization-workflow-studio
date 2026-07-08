"""Multi-project concurrency smoke test for the M2/M3 per-project job lease model.

Exercises the model described in docs/superpowers/plans/2026-07-08-multiuser-concurrency.md:

- two temporary projects translate in parallel under independent
  ``long_text:{project_id}`` leases and both reach a usable, delivered state;
- ``GET /api/system/active-jobs`` reports both jobs running at the same time;
- no SQLite ``database is locked`` error surfaces in either run's events or in
  the backend's own log (when this script manages the backend process);
- a third project is rejected with the "capacity" 409 once the global
  ``max_concurrent_ai_jobs`` cap (default 2) is already saturated.

Output mirrors scripts/deployment_check.py's quiet style: one JSON line per
step on stdout, plus a final summary line, and a process exit code of 0/1.

Usage:

    # Self-start an isolated backend on 127.0.0.1:18800 and run the smoke test.
    python scripts/concurrency_smoke.py

    # Point at an already-running (isolated!) backend instead.
    python scripts/concurrency_smoke.py --base-url http://127.0.0.1:18800

Never point this at a production backend: it patches global settings
(provider/preset/max_concurrent_ai_jobs) and creates + deletes temporary
projects.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx
from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]


def _now_stamp() -> str:
    return time.strftime("%Y%m%d%H%M%S")


class ManagedBackend:
    """Self-starts an isolated uvicorn instance for the duration of the smoke test."""

    def __init__(self, port: int, data_root: Path, log_path: Path) -> None:
        self.port = port
        self.data_root = data_root
        self.log_path = log_path
        self.base_url = f"http://127.0.0.1:{port}"
        self.process: subprocess.Popen | None = None
        self._log_fh = None

    def start(self) -> None:
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        env.update(
            {
                "LWS_DATA_ROOT": str(self.data_root),
                "LWS_ENABLE_TEST_PROVIDER": "1",
                "LWS_DEPLOYMENT_MODE": "local",
                "PYTHONUTF8": "1",
                "PYTHONIOENCODING": "utf-8",
            }
        )
        self._log_fh = self.log_path.open("w", encoding="utf-8")
        self.process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", str(self.port)],
            cwd=str(ROOT),
            env=env,
            stdout=self._log_fh,
            stderr=subprocess.STDOUT,
        )

    def wait_healthy(self, timeout: float = 30.0) -> None:
        deadline = time.time() + timeout
        last_exc: Exception | None = None
        with httpx.Client(timeout=5) as client:
            while time.time() < deadline:
                if self.process is not None and self.process.poll() is not None:
                    raise RuntimeError(
                        f"backend process exited early with code {self.process.returncode}; see {self.log_path}"
                    )
                try:
                    resp = client.get(f"{self.base_url}/api/health")
                    if resp.status_code == 200:
                        return
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                time.sleep(0.3)
        raise RuntimeError(f"backend did not become healthy within {timeout}s: {last_exc}; see {self.log_path}")

    def stop(self) -> None:
        if self.process is None:
            return
        try:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)
        finally:
            if self._log_fh:
                self._log_fh.close()

    def log_text(self) -> str:
        try:
            return self.log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""


class ConcurrencySmoke:
    def __init__(
        self,
        base_url: str,
        *,
        rows: int,
        batch_size: int,
        poll_timeout: int,
        keep_projects: bool,
        managed_backend: ManagedBackend | None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.rows = rows
        self.batch_size = batch_size
        self.poll_timeout = poll_timeout
        self.keep_projects = keep_projects
        self.managed_backend = managed_backend
        self.client = httpx.Client(timeout=60, follow_redirects=True)
        self.steps: list[dict[str, Any]] = []
        self.project_ids: list[str] = []
        self.stamp = _now_stamp()
        self.tmp_dir = Path(tempfile.mkdtemp(prefix=f"concurrency-smoke-{self.stamp}-"))

    def _step(self, name: str, ok: bool, result: Any) -> dict[str, Any]:
        entry = {"step": name, "ok": bool(ok), "result": result}
        self.steps.append(entry)
        print(json.dumps(entry, ensure_ascii=False))
        return entry

    def _get(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.client.get(f"{self.base_url}{path}", **kwargs)

    def _post(self, path: str, payload: Any = None, **kwargs: Any) -> httpx.Response:
        return self.client.post(f"{self.base_url}{path}", json=payload if payload is not None else {}, **kwargs)

    def _patch(self, path: str, payload: Any, **kwargs: Any) -> httpx.Response:
        return self.client.patch(f"{self.base_url}{path}", json=payload, **kwargs)

    def _delete(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.client.delete(f"{self.base_url}{path}", **kwargs)

    def make_language_table(self, name: str) -> Path:
        path = self.tmp_dir / f"{name}.xlsx"
        wb = Workbook()
        ws = wb.active
        ws.title = "Language"
        ws.append(["ID", "cn", "en"])
        for index in range(1, self.rows + 1):
            ws.append([index, f"\u6309\u94ae {index}", ""])
        wb.save(path)
        wb.close()
        return path

    def upload_language_table(self, project_id: str, path: Path) -> dict[str, Any]:
        with path.open("rb") as fh:
            resp = self.client.post(
                f"{self.base_url}/api/projects/{project_id}/files?kind=language_table",
                files={"file": (path.name, fh, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                timeout=60,
            )
        resp.raise_for_status()
        return resp.json()

    def create_project(self, name: str) -> dict[str, Any]:
        resp = self._post(
            "/api/projects",
            {
                "name": name,
                "type": "Concurrency Smoke",
                "icon": "game",
                "description": "scripts/concurrency_smoke.py temporary project, safe to delete.",
            },
        )
        resp.raise_for_status()
        project = resp.json()
        self.project_ids.append(project["id"])
        return project

    def create_translation_run(self, project_id: str, artifact_id: str) -> dict[str, Any]:
        resp = self._post(
            "/api/runs",
            {
                "project_id": project_id,
                "kind": "translation",
                "language": "en",
                "input_artifact_id": artifact_id,
                "batch_size": self.batch_size,
                "task_origin": "concurrency_smoke",
            },
        )
        resp.raise_for_status()
        return resp.json()

    def start_translation(self, run_id: str) -> httpx.Response:
        return self._post(
            f"/api/runs/{run_id}/translate/start",
            {"provider": "test-fake", "preset": "fast", "batch_size": self.batch_size},
            timeout=30,
        )

    def poll_runs(self, run_ids: list[str]) -> dict[str, dict[str, Any]]:
        deadline = time.time() + self.poll_timeout
        results = {rid: self._get(f"/api/runs/{rid}").json() for rid in run_ids}
        while any(r.get("status") in {"queued", "running"} for r in results.values()) and time.time() < deadline:
            time.sleep(0.3)
            results = {rid: self._get(f"/api/runs/{rid}").json() for rid in run_ids}
        return results

    def poll_active_jobs_concurrent(self, project_ids: set[str], timeout: float = 5.0) -> tuple[bool, list[dict[str, Any]]]:
        deadline = time.time() + timeout
        last_snapshot: list[dict[str, Any]] = []
        while time.time() < deadline:
            resp = self._get("/api/system/active-jobs")
            if resp.status_code == 200:
                active = resp.json()
                last_snapshot = active
                seen_ids = {item.get("project_id") for item in active}
                if project_ids.issubset(seen_ids):
                    return True, active
            time.sleep(0.05)
        return False, last_snapshot

    def run_events_text(self, run_id: str) -> str:
        resp = self._get(f"/api/runs/{run_id}/events")
        if resp.status_code != 200:
            return ""
        try:
            events = resp.json()
        except Exception:  # noqa: BLE001
            return ""
        return "\n".join(str(event.get("message") or "") for event in events)

    def cleanup_projects(self) -> dict[str, Any]:
        results: dict[str, Any] = {}
        for project_id in self.project_ids:
            if self.keep_projects:
                results[project_id] = "kept"
                continue
            try:
                resp = self._delete(f"/api/projects/{project_id}")
                results[project_id] = resp.status_code
            except Exception as exc:  # noqa: BLE001
                results[project_id] = f"error: {exc}"
        return results

    def execute(self) -> int:
        failed = False
        db_locked_hits: list[str] = []

        health_resp = self._get("/api/health")
        health = health_resp.json() if health_resp.status_code == 200 else {}
        entry = self._step("00_health", health_resp.status_code == 200 and bool(health.get("ok")), {
            "status_code": health_resp.status_code,
            "deployment_mode": health.get("deployment_mode"),
        })
        if not entry["ok"]:
            failed = True
            return self._finish(failed, db_locked_hits)

        settings_payload = {"provider": "test-fake", "preset": "fast", "max_concurrent_ai_jobs": 2}
        patch_resp = self._patch("/api/settings", settings_payload)
        settings_after = patch_resp.json() if patch_resp.status_code == 200 else {}
        settings_ok = (
            patch_resp.status_code == 200
            and settings_after.get("provider") == "test-fake"
            and int(settings_after.get("max_concurrent_ai_jobs") or 0) == 2
        )
        self._step("01_settings_test_fake", settings_ok, {
            "status_code": patch_resp.status_code,
            "provider": settings_after.get("provider"),
            "max_concurrent_ai_jobs": settings_after.get("max_concurrent_ai_jobs"),
        })
        if not settings_ok:
            failed = True
            self._step(
                "01b_diagnosis",
                False,
                "provider did not normalize to test-fake; is LWS_ENABLE_TEST_PROVIDER=1 set on the backend process?",
            )
            return self._finish(failed, db_locked_hits)

        try:
            project_a = self.create_project(f"ConcurrencySmoke-A-{self.stamp}")
            project_b = self.create_project(f"ConcurrencySmoke-B-{self.stamp}")
            project_c = self.create_project(f"ConcurrencySmoke-C-{self.stamp}")
            self._step("02_create_projects", True, {
                "project_a": project_a["id"],
                "project_b": project_b["id"],
                "project_c": project_c["id"],
            })

            artifact_a = self.upload_language_table(project_a["id"], self.make_language_table("table-a"))
            artifact_b = self.upload_language_table(project_b["id"], self.make_language_table("table-b"))
            artifact_c = self.upload_language_table(project_c["id"], self.make_language_table("table-c"))
            self._step("03_upload_language_tables", True, {
                "artifact_a": artifact_a["id"],
                "artifact_b": artifact_b["id"],
                "artifact_c": artifact_c["id"],
            })

            run_a = self.create_translation_run(project_a["id"], artifact_a["id"])
            run_b = self.create_translation_run(project_b["id"], artifact_b["id"])
            run_c = self.create_translation_run(project_c["id"], artifact_c["id"])
            self._step("04_create_runs", True, {"run_a": run_a["id"], "run_b": run_b["id"], "run_c": run_c["id"]})

            started_a = self.start_translation(run_a["id"])
            started_b = self.start_translation(run_b["id"])
            start_ab_ok = started_a.status_code == 200 and started_b.status_code == 200
            self._step("05_start_two_projects_in_parallel", start_ab_ok, {
                "run_a_status": started_a.status_code,
                "run_b_status": started_b.status_code,
            })
            if not start_ab_ok:
                failed = True

            # Fired immediately after A/B are admitted, while their per-project
            # leases should still be held: this is the "capacity" rejection check
            # (default max_concurrent_ai_jobs=2, so a third concurrent project
            # must be rejected).
            started_c = self.start_translation(run_c["id"])
            detail_c = ""
            if started_c.status_code == 409:
                try:
                    detail_c = str(started_c.json().get("detail") or "")
                except Exception:  # noqa: BLE001
                    detail_c = started_c.text
            capacity_ok = (
                started_c.status_code == 409
                and "\u5de5\u4f5c\u53f0\u5df2\u6709" in detail_c
                and "\u4e0a\u9650 2" in detail_c
            )
            self._step("06_third_project_rejected_capacity", capacity_ok, {
                "status_code": started_c.status_code,
                "detail": detail_c or (started_c.text if started_c.status_code != 200 else "(started unexpectedly)"),
            })
            if not capacity_ok:
                failed = True

            concurrent_ok, active_snapshot = self.poll_active_jobs_concurrent({project_a["id"], project_b["id"]}, timeout=8.0)
            self._step("07_active_jobs_shows_both_projects_concurrently", concurrent_ok, {
                "observed": concurrent_ok,
                "last_snapshot": active_snapshot,
            })
            if not concurrent_ok:
                failed = True

            terminal = self.poll_runs([run_a["id"], run_b["id"]])
            terminal_a = terminal[run_a["id"]]
            terminal_b = terminal[run_b["id"]]
            progress_a = (terminal_a.get("metadata") or {}).get("translation_progress") or {}
            progress_b = (terminal_b.get("metadata") or {}).get("translation_progress") or {}
            both_passed = terminal_a.get("status") == "passed" and terminal_b.get("status") == "passed"
            rows_delivered_ok = (
                int(progress_a.get("completed_rows") or 0) == self.rows
                and int(progress_b.get("completed_rows") or 0) == self.rows
            )
            self._step("08_both_runs_passed_and_deliverable", both_passed and rows_delivered_ok, {
                "run_a_status": terminal_a.get("status"),
                "run_b_status": terminal_b.get("status"),
                "run_a_completed_rows": progress_a.get("completed_rows"),
                "run_b_completed_rows": progress_b.get("completed_rows"),
                "expected_rows": self.rows,
            })
            if not (both_passed and rows_delivered_ok):
                failed = True

            events_text = "\n".join(
                [
                    self.run_events_text(run_a["id"]),
                    self.run_events_text(run_b["id"]),
                    self.run_events_text(run_c["id"]),
                ]
            )
            if "database is locked" in events_text.lower():
                db_locked_hits.append("run_events")
            if self.managed_backend is not None and "database is locked" in self.managed_backend.log_text().lower():
                db_locked_hits.append("backend_log")
            self._step("09_no_database_is_locked", not db_locked_hits, {"hits": db_locked_hits})
            if db_locked_hits:
                failed = True

            cleanup_results = self.cleanup_projects()
            cleanup_ok = self.keep_projects or all(str(v) in {"200"} for v in cleanup_results.values())
            self._step("10_cleanup_temporary_projects", cleanup_ok, cleanup_results)
            if not cleanup_ok:
                failed = True

        except Exception as exc:  # noqa: BLE001
            failed = True
            self._step("99_exception", False, str(exc))
            try:
                self.cleanup_projects()
            except Exception:  # noqa: BLE001
                pass

        return self._finish(failed, db_locked_hits)

    def _finish(self, failed: bool, db_locked_hits: list[str]) -> int:
        summary = {
            "step": "99_summary",
            "ok": not failed,
            "result": {
                "base_url": self.base_url,
                "rows": self.rows,
                "batch_size": self.batch_size,
                "project_ids": self.project_ids,
                "database_locked_hits": db_locked_hits,
                "step_count": len(self.steps),
                "failed_steps": [s["step"] for s in self.steps if not s["ok"]],
            },
        }
        print(json.dumps(summary, ensure_ascii=False))
        return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Multi-project concurrency smoke test.")
    parser.add_argument("--base-url", default=None, help="Existing isolated backend URL. Omit to self-start one.")
    parser.add_argument("--port", type=int, default=18800, help="Port to self-start the backend on (default 18800).")
    parser.add_argument("--data-root", default=None, help="LWS_DATA_ROOT for the self-started backend.")
    parser.add_argument("--rows", type=int, default=12, help="Rows per language table (default 12).")
    parser.add_argument("--batch-size", type=int, default=2, help="Translation batch size (default 2).")
    parser.add_argument("--poll-timeout", type=int, default=120, help="Seconds to wait for runs to reach a terminal state.")
    parser.add_argument("--keep-projects", action="store_true", help="Do not delete the temporary projects (debugging).")
    parser.add_argument("--keep-server", action="store_true", help="Do not stop the self-started backend on exit (debugging).")
    parser.add_argument("--report", default=None, help="Path to write the full JSON report. Defaults under .tmp/concurrency-smoke/.")
    args = parser.parse_args()

    stamp = _now_stamp()
    report_path = Path(args.report) if args.report else ROOT / ".tmp" / "concurrency-smoke" / stamp / "report.json"

    managed_backend: ManagedBackend | None = None
    base_url = args.base_url
    if base_url is None:
        temp_root = Path(args.data_root) if args.data_root else Path(tempfile.mkdtemp(prefix=f"lws-concurrency-smoke-data-{stamp}-"))
        log_path = ROOT / ".tmp" / "concurrency-smoke" / stamp / "backend.log"
        managed_backend = ManagedBackend(port=args.port, data_root=temp_root, log_path=log_path)
        print(json.dumps({"step": "start_backend", "ok": True, "result": {"port": args.port, "data_root": str(temp_root), "log": str(log_path)}}, ensure_ascii=False))
        managed_backend.start()
        try:
            managed_backend.wait_healthy()
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"step": "start_backend", "ok": False, "result": str(exc)}, ensure_ascii=False))
            managed_backend.stop()
            return 1
        base_url = managed_backend.base_url

    smoke = ConcurrencySmoke(
        base_url,
        rows=args.rows,
        batch_size=args.batch_size,
        poll_timeout=args.poll_timeout,
        keep_projects=args.keep_projects,
        managed_backend=managed_backend,
    )
    try:
        exit_code = smoke.execute()
    finally:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps({"base_url": base_url, "steps": smoke.steps}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"report={report_path}")
        if managed_backend is not None and not args.keep_server:
            managed_backend.stop()

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
