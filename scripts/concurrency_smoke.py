"""Persistent dual-lane queue smoke test.

Exercises the current global queue contract:

- formal language-table jobs are accepted into one FIFO lane, including a
  third job that would previously have received a capacity 409;
- quick tasks and announcements share a second FIFO lane;
- one formal job and one quick/announcement job can run in parallel;
- a queued job can be canceled without blocking the next FIFO item;
- when this script manages the backend, a restart interrupts the running job
  and resumes the queued job from persistent storage;
- no SQLite ``database is locked`` error surfaces in run events or the managed
  backend log.

Output mirrors scripts/deployment_check.py's quiet style: one JSON line per
step on stdout, plus a final summary line, and a process exit code of 0/1.

Usage:

    # Self-start an isolated backend on 127.0.0.1:18800 and run the smoke test.
    python scripts/concurrency_smoke.py

    # Point at an already-running (isolated!) backend instead. This mode skips
    # the process-restart check because the script does not own that process.
    python scripts/concurrency_smoke.py --base-url http://127.0.0.1:18800

Never point this at a production backend: it patches global settings
(provider/preset) and creates + deletes temporary projects.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
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

    def _port_is_open(self) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.2)
            return probe.connect_ex(("127.0.0.1", self.port)) == 0

    def start(self, *, append_log: bool = False) -> None:
        if self._port_is_open():
            raise RuntimeError(f"port {self.port} is already in use; choose an isolated port")
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        env.update(
            {
                "LWS_DATA_ROOT": str(self.data_root),
                "LWS_ENABLE_TEST_PROVIDER": "1",
                "LWS_DEPLOYMENT_MODE": "local",
                "LWS_AUTH_MODE": "off",
                "PYTHONUTF8": "1",
                "PYTHONIOENCODING": "utf-8",
            }
        )
        self._log_fh = self.log_path.open("a" if append_log else "w", encoding="utf-8")
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
                        payload = resp.json()
                        reported_root = Path(str(payload.get("data_root") or "")).resolve(strict=False)
                        expected_root = self.data_root.resolve(strict=False)
                        if (
                            self.process is not None
                            and self.process.poll() is None
                            and reported_root == expected_root
                        ):
                            return
                        last_exc = RuntimeError(
                            f"health endpoint belongs to data_root={reported_root}, expected {expected_root}"
                        )
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

    def restart(self) -> None:
        self.stop()
        deadline = time.time() + 5.0
        while self._port_is_open() and time.time() < deadline:
            time.sleep(0.05)
        self.start(append_log=True)
        self.wait_healthy()

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
        self.batch_size = max(1, batch_size)
        # The queue assertions need enough batches to observe running/queued
        # states reliably even on a fast local machine.
        self.rows = max(24, rows, self.batch_size * 8)
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

    def make_language_table(self, name: str, *, rows: int | None = None) -> Path:
        path = self.tmp_dir / f"{name}.xlsx"
        wb = Workbook()
        ws = wb.active
        ws.title = "Language"
        ws.append(["ID", "cn", "en"])
        for index in range(1, (rows or self.rows) + 1):
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

    def create_translation_run(
        self,
        project_id: str,
        artifact_id: str,
        *,
        task_origin: str = "translation_run",
        translation_task_id: str | None = None,
    ) -> dict[str, Any]:
        resp = self._post(
            "/api/runs",
            {
                "project_id": project_id,
                "kind": "translation",
                "language": "en",
                "input_artifact_id": artifact_id,
                "batch_size": self.batch_size,
                "task_origin": task_origin,
                "translation_task_id": translation_task_id,
            },
        )
        resp.raise_for_status()
        return resp.json()

    def prepare_announcement_task(self, project_id: str) -> dict[str, Any]:
        created = self._post(
            f"/api/projects/{project_id}/announcement-tasks",
            {
                "title": f"QueueSmoke-{self.stamp}",
                "text": "\u6d3b\u52a8\u5c06\u4e8e 10:00 \u5f00\u542f\uff0c\u8bf7\u53ca\u65f6\u9886\u53d6\u5956\u52b1\u3002",
                "languages": ["en"],
                "include_project_archive": False,
            },
        )
        created.raise_for_status()
        task = created.json()
        task_id = task["id"]
        actions = [
            (
                "extract-terms",
                {
                    "languages": ["en"],
                    "include_project_archive": False,
                    "ai_supplement": False,
                },
            ),
            (
                "lookup-translations",
                {
                    "languages": ["en"],
                    "include_project_archive": False,
                },
            ),
            ("prepare", {"languages": ["en"]}),
        ]
        for action, payload in actions:
            response = self._post(f"/api/announcement-tasks/{task_id}/{action}", payload, timeout=180)
            response.raise_for_status()
        prepared = self._get(f"/api/announcement-tasks/{task_id}")
        prepared.raise_for_status()
        return prepared.json()

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

    def poll_announcement_task(self, task_id: str) -> dict[str, Any]:
        deadline = time.time() + self.poll_timeout
        task = self._get(f"/api/announcement-tasks/{task_id}").json()
        while task.get("status") in {"queued", "running"} and time.time() < deadline:
            time.sleep(0.3)
            task = self._get(f"/api/announcement-tasks/{task_id}").json()
        return task

    def poll_queue_layout(
        self,
        *,
        expected_running: dict[str, str],
        expected_queued: dict[str, list[str]],
        timeout: float = 8.0,
    ) -> tuple[bool, dict[str, Any]]:
        deadline = time.time() + timeout
        last_snapshot: dict[str, Any] = {}
        while time.time() < deadline:
            resp = self._get("/api/system/job-queues")
            if resp.status_code == 200:
                last_snapshot = resp.json()
                lanes = {item.get("lane"): item for item in last_snapshot.get("lanes") or []}
                matches = True
                for lane, job_id in expected_running.items():
                    running = (lanes.get(lane) or {}).get("running") or {}
                    matches = matches and running.get("job_id") == job_id
                for lane, job_ids in expected_queued.items():
                    queued = (lanes.get(lane) or {}).get("queued") or []
                    matches = matches and [item.get("job_id") for item in queued] == job_ids
                if matches:
                    return True, last_snapshot
            time.sleep(0.05)
        return False, last_snapshot

    def poll_active_jobs(self, expected_job_ids: set[str], timeout: float = 8.0) -> tuple[bool, list[dict[str, Any]]]:
        deadline = time.time() + timeout
        last_snapshot: list[dict[str, Any]] = []
        while time.time() < deadline:
            resp = self._get("/api/system/active-jobs")
            if resp.status_code == 200:
                last_snapshot = resp.json()
                if {item.get("job_id") for item in last_snapshot} == expected_job_ids:
                    return True, last_snapshot
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
        observed_run_ids: list[str] = []

        health_resp = self._get("/api/health")
        health = health_resp.json() if health_resp.status_code == 200 else {}
        entry = self._step("00_health", health_resp.status_code == 200 and bool(health.get("ok")), {
            "status_code": health_resp.status_code,
            "deployment_mode": health.get("deployment_mode"),
        })
        if not entry["ok"]:
            failed = True
            return self._finish(failed, db_locked_hits)

        settings_payload = {"provider": "test-fake", "preset": "fast"}
        patch_resp = self._patch("/api/settings", settings_payload)
        settings_after = patch_resp.json() if patch_resp.status_code == 200 else {}
        settings_ok = (
            patch_resp.status_code == 200
            and settings_after.get("provider") == "test-fake"
            and settings_after.get("preset") == "fast"
        )
        self._step("01_settings_test_fake", settings_ok, {
            "status_code": patch_resp.status_code,
            "provider": settings_after.get("provider"),
            "preset": settings_after.get("preset"),
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
            projects = {
                name: self.create_project(f"QueueSmoke-{name}-{self.stamp}")
                for name in ("formal-a", "formal-b", "formal-c", "quick", "announcement")
            }
            self._step("02_create_projects", True, {name: project["id"] for name, project in projects.items()})

            artifacts = {
                name: self.upload_language_table(
                    projects[name]["id"],
                    self.make_language_table(f"table-{name}"),
                )
                for name in ("formal-a", "formal-b", "formal-c", "quick")
            }
            announcement_task = self.prepare_announcement_task(projects["announcement"]["id"])
            self._step(
                "03_prepare_inputs",
                announcement_task.get("status") == "prepared",
                {
                    "artifacts": {name: artifact["id"] for name, artifact in artifacts.items()},
                    "announcement_task": announcement_task["id"],
                    "announcement_status": announcement_task.get("status"),
                },
            )
            if announcement_task.get("status") != "prepared":
                failed = True

            formal_runs = {
                name: self.create_translation_run(
                    projects[name]["id"],
                    artifacts[name]["id"],
                    translation_task_id=f"formal-smoke-{self.stamp}-{name}",
                )
                for name in ("formal-a", "formal-b", "formal-c")
            }
            quick_run = self.create_translation_run(
                projects["quick"]["id"],
                artifacts["quick"]["id"],
                task_origin="quick_task",
                translation_task_id=f"quick-task-smoke-{self.stamp}",
            )
            observed_run_ids.extend([run["id"] for run in formal_runs.values()])
            observed_run_ids.append(quick_run["id"])
            self._step(
                "04_create_runs",
                True,
                {
                    "formal": {name: run["id"] for name, run in formal_runs.items()},
                    "quick": quick_run["id"],
                },
            )

            formal_starts = {
                name: self.start_translation(formal_runs[name]["id"])
                for name in ("formal-a", "formal-b", "formal-c")
            }
            formal_job_ids = {
                name: f"run:{formal_runs[name]['id']}"
                for name in ("formal-a", "formal-b", "formal-c")
            }
            formal_fifo_observed, formal_snapshot = self.poll_queue_layout(
                expected_running={"language_table": formal_job_ids["formal-a"]},
                expected_queued={
                    "language_table": [
                        formal_job_ids["formal-b"],
                        formal_job_ids["formal-c"],
                    ],
                    "quick_announcement": [],
                },
            )
            formal_fifo_ok = (
                all(response.status_code == 200 for response in formal_starts.values())
                and formal_fifo_observed
            )
            self._step(
                "05_formal_lane_accepts_third_and_is_fifo",
                formal_fifo_ok,
                {
                    "start_statuses": {
                        name: response.status_code
                        for name, response in formal_starts.items()
                    },
                    "queue_snapshot": formal_snapshot,
                },
            )
            if not formal_fifo_ok:
                failed = True

            canceled_response = self._post(
                f"/api/system/job-queues/{formal_job_ids['formal-b']}/cancel"
            )
            canceled_payload = (
                canceled_response.json()
                if canceled_response.headers.get("content-type", "").startswith("application/json")
                else {}
            )
            canceled_job = canceled_payload.get("queue_job") or {}
            canceled_run = canceled_payload.get("business_target") or {}
            cancel_ok = (
                canceled_response.status_code == 200
                and canceled_job.get("status") == "canceled"
                and canceled_run.get("status") == "canceled"
            )
            self._step(
                "06_cancel_queued_formal_job",
                cancel_ok,
                {
                    "status_code": canceled_response.status_code,
                    "queue_status": canceled_job.get("status"),
                    "run_status": canceled_run.get("status"),
                },
            )
            if not cancel_ok:
                failed = True

            quick_started = self.start_translation(quick_run["id"])
            announcement_started = self._post(
                f"/api/announcement-tasks/{announcement_task['id']}/translate/start",
                {"languages": ["en"], "provider": "test-fake", "batch_size": self.batch_size},
                timeout=30,
            )
            quick_job_id = f"run:{quick_run['id']}"
            announcement_job_id = f"announcement:{announcement_task['id']}"
            dual_layout_ok, dual_snapshot = self.poll_queue_layout(
                expected_running={
                    "language_table": formal_job_ids["formal-a"],
                    "quick_announcement": quick_job_id,
                },
                expected_queued={
                    "language_table": [formal_job_ids["formal-c"]],
                    "quick_announcement": [announcement_job_id],
                },
            )
            active_ok, active_snapshot = self.poll_active_jobs(
                {formal_job_ids["formal-a"], quick_job_id}
            )
            dual_lane_ok = (
                quick_started.status_code == 200
                and announcement_started.status_code == 200
                and dual_layout_ok
                and active_ok
            )
            self._step(
                "07_two_lanes_run_in_parallel_and_short_lane_is_fifo",
                dual_lane_ok,
                {
                    "quick_start_status": quick_started.status_code,
                    "announcement_start_status": announcement_started.status_code,
                    "queue_snapshot": dual_snapshot,
                    "active_jobs": active_snapshot,
                },
            )
            if not dual_lane_ok:
                failed = True

            running_cancel_responses = {
                "formal": self._post(
                    f"/api/system/job-queues/{formal_job_ids['formal-a']}/cancel"
                ),
                "quick": self._post(
                    f"/api/system/job-queues/{quick_job_id}/cancel"
                ),
            }
            running_cancel_payloads = {
                name: (
                    response.json()
                    if response.headers.get("content-type", "").startswith("application/json")
                    else {}
                )
                for name, response in running_cancel_responses.items()
            }
            running_cancel_ok = all(
                response.status_code == 200
                and bool((running_cancel_payloads[name].get("queue_job") or {}).get("cancel_requested"))
                for name, response in running_cancel_responses.items()
            )
            self._step(
                "08_cancel_running_lane_heads",
                running_cancel_ok,
                {
                    name: {
                        "status_code": response.status_code,
                        "queue_status": (
                            running_cancel_payloads[name].get("queue_job") or {}
                        ).get("status"),
                        "cancel_requested": (
                            running_cancel_payloads[name].get("queue_job") or {}
                        ).get("cancel_requested"),
                    }
                    for name, response in running_cancel_responses.items()
                },
            )
            if not running_cancel_ok:
                failed = True

            terminal_runs = self.poll_runs(observed_run_ids)
            terminal_announcement = self.poll_announcement_task(announcement_task["id"])
            expected_statuses = {
                formal_runs["formal-a"]["id"]: "canceled",
                formal_runs["formal-b"]["id"]: "canceled",
                formal_runs["formal-c"]["id"]: "passed",
                quick_run["id"]: "canceled",
            }
            statuses_ok = all(
                terminal_runs[run_id].get("status") == expected
                for run_id, expected in expected_statuses.items()
            )
            completed_rows = {
                run_id: ((terminal_runs[run_id].get("metadata") or {}).get("translation_progress") or {}).get("completed_rows")
                for run_id, expected in expected_statuses.items()
                if expected == "passed"
            }
            rows_ok = all(int(value or 0) == self.rows for value in completed_rows.values())
            announcement_ok = terminal_announcement.get("status") == "translated"
            terminal_ok = statuses_ok and rows_ok and announcement_ok
            self._step(
                "09_fifo_jobs_reach_expected_terminal_states",
                terminal_ok,
                {
                    "run_statuses": {
                        run_id: terminal_runs[run_id].get("status")
                        for run_id in expected_statuses
                    },
                    "completed_rows": completed_rows,
                    "expected_rows": self.rows,
                    "announcement_status": terminal_announcement.get("status"),
                },
            )
            if not terminal_ok:
                failed = True

            if self.managed_backend is not None:
                restart_rows = max(80, self.batch_size * 20)
                restart_row_counts = {"running": restart_rows, "queued": 1}
                restart_projects = {
                    name: self.create_project(f"QueueSmoke-restart-{name}-{self.stamp}")
                    for name in ("running", "queued")
                }
                restart_artifacts = {
                    name: self.upload_language_table(
                        restart_projects[name]["id"],
                        self.make_language_table(
                            f"restart-{name}",
                            rows=restart_row_counts[name],
                        ),
                    )
                    for name in ("running", "queued")
                }
                restart_runs = {
                    name: self.create_translation_run(
                        restart_projects[name]["id"],
                        restart_artifacts[name]["id"],
                        translation_task_id=f"formal-smoke-restart-{self.stamp}-{name}",
                    )
                    for name in ("running", "queued")
                }
                observed_run_ids.extend(run["id"] for run in restart_runs.values())
                restart_job_ids = {
                    name: f"run:{restart_runs[name]['id']}"
                    for name in ("running", "queued")
                }
                restart_start_responses = {
                    name: self.start_translation(restart_runs[name]["id"])
                    for name in ("running", "queued")
                }
                restart_layout_ok, restart_snapshot = self.poll_queue_layout(
                    expected_running={"language_table": restart_job_ids["running"]},
                    expected_queued={
                        "language_table": [restart_job_ids["queued"]],
                        "quick_announcement": [],
                    },
                )
                recovery_result: dict[str, dict[str, Any]] = {}
                if restart_layout_ok:
                    self.managed_backend.restart()
                    recovery_result = self.poll_runs(
                        [restart_runs["running"]["id"], restart_runs["queued"]["id"]]
                    )
                recovery_ok = (
                    all(response.status_code == 200 for response in restart_start_responses.values())
                    and restart_layout_ok
                    and recovery_result.get(restart_runs["running"]["id"], {}).get("status") == "needs_input"
                    and recovery_result.get(restart_runs["queued"]["id"], {}).get("status") == "passed"
                    and int(
                        (
                            recovery_result.get(restart_runs["queued"]["id"], {}).get("metadata") or {}
                        ).get("translation_progress", {}).get("completed_rows") or 0
                    )
                    == restart_row_counts["queued"]
                )
                self._step(
                    "10_restart_interrupts_running_and_resumes_queued",
                    recovery_ok,
                    {
                        "start_statuses": {
                            name: response.status_code
                            for name, response in restart_start_responses.items()
                        },
                        "before_restart": restart_snapshot,
                        "after_restart": {
                            name: recovery_result.get(run["id"], {}).get("status")
                            for name, run in restart_runs.items()
                        },
                        "restart_rows": restart_row_counts,
                    },
                )
                if not recovery_ok:
                    failed = True
            else:
                self._step(
                    "10_restart_recovery_skipped",
                    True,
                    "external --base-url mode does not own the backend process; run without --base-url to exercise restart recovery",
                )

            events_text = "\n".join(self.run_events_text(run_id) for run_id in observed_run_ids)
            if "database is locked" in events_text.lower():
                db_locked_hits.append("run_events")
            if self.managed_backend is not None and "database is locked" in self.managed_backend.log_text().lower():
                db_locked_hits.append("backend_log")
            self._step("11_no_database_is_locked", not db_locked_hits, {"hits": db_locked_hits})
            if db_locked_hits:
                failed = True

            cleanup_results = self.cleanup_projects()
            cleanup_ok = self.keep_projects or all(str(v) in {"200"} for v in cleanup_results.values())
            self._step("12_cleanup_temporary_projects", cleanup_ok, cleanup_results)
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
    parser = argparse.ArgumentParser(description="Persistent dual-lane queue smoke test.")
    parser.add_argument("--base-url", default=None, help="Existing isolated backend URL. Omit to self-start one.")
    parser.add_argument("--port", type=int, default=18800, help="Port to self-start the backend on (default 18800).")
    parser.add_argument("--data-root", default=None, help="LWS_DATA_ROOT for the self-started backend.")
    parser.add_argument(
        "--rows",
        type=int,
        default=24,
        help="Rows per language table; raised to at least 24 and eight batches so queue states remain observable.",
    )
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
        startup_result = {"port": args.port, "data_root": str(temp_root), "log": str(log_path)}
        try:
            managed_backend.start()
            managed_backend.wait_healthy()
        except Exception as exc:  # noqa: BLE001
            startup_entry = {
                "step": "start_backend",
                "ok": False,
                "result": {**startup_result, "error": str(exc)},
            }
            print(json.dumps(startup_entry, ensure_ascii=False))
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(
                    {"base_url": managed_backend.base_url, "steps": [startup_entry]},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            print(f"report={report_path}")
            managed_backend.stop()
            return 1
        print(json.dumps({"step": "start_backend", "ok": True, "result": startup_result}, ensure_ascii=False))
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
