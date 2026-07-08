from __future__ import annotations

import asyncio
import os
import tempfile
import threading
import time
from pathlib import Path

os.environ["LWS_DATA_ROOT"] = str(Path(tempfile.gettempdir()) / "lws-test-data")

import pytest

import app.db as db
import app.workflow as workflow
from app.config import DEFAULT_SETTINGS, save_settings
from app.providers import TranslationItem
from app.translation_batches import (
    SharedRateLimiter,
    get_shared_rate_limiter,
    reset_shared_rate_limiter_registry,
    shared_rate_limiter_bucket_key,
)
from conftest import reset_data_root, wait_for_background_jobs


@pytest.fixture(autouse=True)
def reset_test_state() -> None:
    data_root = Path(os.environ["LWS_DATA_ROOT"])
    reset_data_root(data_root)
    db.init_db()
    save_settings(DEFAULT_SETTINGS)
    reset_shared_rate_limiter_registry()
    yield
    wait_for_background_jobs()
    save_settings(DEFAULT_SETTINGS)
    reset_shared_rate_limiter_registry()


def test_shared_rate_limiter_single_run_matches_existing_behavior() -> None:
    """A single run against a fresh bucket must behave like the old
    per-run ``AsyncTokenRateLimiter``: requests within budget are granted
    immediately, and a single oversized request is clamped instead of
    deadlocking.
    """
    limiter = SharedRateLimiter(requests_per_minute=5, tokens_per_minute=1000)

    async def go() -> list[float]:
        return [await limiter.acquire(50) for _ in range(5)]

    waited = asyncio.run(go())
    assert waited == [0.0, 0.0, 0.0, 0.0, 0.0]

    # A single request larger than the whole per-minute token budget must be
    # clamped rather than waiting forever for room that can never exist.
    oversized_waited = asyncio.run(SharedRateLimiter(requests_per_minute=1, tokens_per_minute=1000).acquire(5000))
    assert oversized_waited == 0


def test_get_shared_rate_limiter_reuses_bucket_for_same_provider_and_key() -> None:
    first = get_shared_rate_limiter("openai", "sk-shared-key", 10, 100000)
    second = get_shared_rate_limiter("openai", "sk-shared-key", 999, 999999)
    assert first is second
    # Bucket config is fixed at first creation; a later call with different
    # RPM/TPM for the *same* bucket does not silently change its budget.
    assert first.requests_per_minute == 10
    assert first.tokens_per_minute == 100000


def test_get_shared_rate_limiter_separates_buckets_by_provider_and_key() -> None:
    same_provider_diff_key_a = get_shared_rate_limiter("openai", "sk-aaa", 10, 100000)
    same_provider_diff_key_b = get_shared_rate_limiter("openai", "sk-bbb", 10, 100000)
    diff_provider_same_key = get_shared_rate_limiter("anthropic", "sk-aaa", 10, 100000)
    assert same_provider_diff_key_a is not same_provider_diff_key_b
    assert same_provider_diff_key_a is not diff_provider_same_key
    assert shared_rate_limiter_bucket_key("openai", "sk-aaa") != shared_rate_limiter_bucket_key("openai", "sk-bbb")


def test_shared_rate_limiter_caps_combined_rate_across_threads_and_event_loops() -> None:
    """Two threads, each with its own asyncio event loop (mirroring two
    background job threads), share one ``SharedRateLimiter`` bucket. The
    combined grant rate must respect the configured limit rather than each
    thread getting its own independent quota (which was the pre-M3 bug:
    each run created its own ``AsyncTokenRateLimiter``, so two concurrent
    runs would together draw 2x the configured provider budget).
    """
    requests_per_minute = 4
    window_seconds = 0.6
    limiter = SharedRateLimiter(requests_per_minute=requests_per_minute, tokens_per_minute=1_000_000, window_seconds=window_seconds)
    granted_at: list[tuple[str, float]] = []
    results_lock = threading.Lock()
    start_barrier = threading.Barrier(2)

    def worker(name: str) -> None:
        async def go() -> None:
            for _ in range(6):
                await limiter.acquire(10)
                with results_lock:
                    granted_at.append((name, time.monotonic()))

        start_barrier.wait(timeout=5)
        asyncio.run(go())

    threads = [threading.Thread(target=worker, args=(f"thread-{i}",), daemon=True) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert all(not thread.is_alive() for thread in threads)

    assert len(granted_at) == 12
    names_seen = {name for name, _ in granted_at}
    assert names_seen == {"thread-0", "thread-1"}, granted_at

    timestamps = sorted(t for _, t in granted_at)
    max_in_any_window = 0
    for anchor in timestamps:
        count = sum(1 for other in timestamps if anchor - window_seconds < other <= anchor)
        max_in_any_window = max(max_in_any_window, count)
    # The combined grant rate across BOTH threads must respect the single
    # shared budget. Two independent (unshared) limiters would have allowed
    # up to 2x requests_per_minute within one window -- this is exactly the
    # regression this test guards against.
    assert max_in_any_window <= requests_per_minute, (max_in_any_window, granted_at)
    # Sanity check contention actually happened (12 requests can't all fit
    # in one 0.6s window at a budget of 4), proving the limiter genuinely
    # throttled rather than trivially passing because nothing overlapped.
    assert timestamps[-1] - timestamps[0] > window_seconds


def test_orchestrator_shares_rate_limit_budget_across_two_concurrent_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Two concurrent ``_translate_rows_with_orchestration`` calls (simulating
    two projects' background job threads) for the same provider/api_key must
    draw from one combined rate budget, per M3 batch 1.
    """
    provider = "test-fake"
    api_key = ""
    window_seconds = 1.0
    requests_per_minute = 2
    # Pre-seed the process-wide bucket the orchestrator will look up (keyed
    # only by provider + api_key) with a short window so the test finishes
    # quickly while still exercising the real orchestrator -> registry path.
    limiter = get_shared_rate_limiter(provider, api_key, requests_per_minute, 1_000_000, window_seconds=window_seconds)

    # Record the exact moment each reservation is granted (not when the
    # provider call eventually happens, which is offset by real I/O -- JSONL
    # writes, manifest persistence, event logging -- done between acquiring
    # the slot and calling the provider; that offset would make a post-hoc
    # window check on provider-call timestamps flaky).
    acquire_times: list[float] = []
    acquire_times_lock = threading.Lock()
    original_acquire = limiter.acquire

    async def recording_acquire(tokens: int) -> float:
        waited = await original_acquire(tokens)
        with acquire_times_lock:
            acquire_times.append(time.monotonic())
        return waited

    limiter.acquire = recording_acquire

    project_a = db.insert_project("Shared Limiter A", "QA", "", "🎮")
    project_b = db.insert_project("Shared Limiter B", "QA", "", "🎮")
    run_a = db.insert_run(project_a["id"], "translation", "en", metadata={})
    run_b = db.insert_run(project_b["id"], "translation", "en", metadata={})
    rows_a = [{"id": index, "source": f"按钮A {index}"} for index in range(4)]
    rows_b = [{"id": index, "source": f"按钮B {index}"} for index in range(4)]
    settings = {
        **DEFAULT_SETTINGS,
        "provider": provider,
        "api_key": api_key,
        "batch_size": 1,
        "max_concurrent_batches": 1,
        "max_requests_per_minute": requests_per_minute,
        "max_estimated_tokens_per_minute": 1_000_000,
        "api_budget_warning_tokens": 20_000_000,
        "max_batch_attempts": 2,
    }

    call_times: list[float] = []
    call_times_lock = threading.Lock()

    async def recording_translate_batch(batch, provider_settings, project_prompt):
        _ = provider_settings, project_prompt
        with call_times_lock:
            call_times.append(time.monotonic())
        return [TranslationItem(id=row["id"], translation=f"Translated {row['id']}") for row in batch]

    monkeypatch.setattr(workflow, "translate_batch", recording_translate_batch)

    results: dict[str, list[dict]] = {}
    errors: list[BaseException] = []

    def run_orchestration(key: str, run_id: str, rows: list[dict], work_dir: Path) -> None:
        try:
            results[key] = asyncio.run(
                workflow._translate_rows_with_orchestration(
                    run_id=run_id,
                    rows=rows,
                    settings=settings,
                    project_prompt="Translate.",
                    work_dir=work_dir,
                    batch_size=1,
                    language="en",
                    confirm_api_budget=True,
                )
            )
        except BaseException as exc:  # pragma: no cover - failure path
            errors.append(exc)

    thread_a = threading.Thread(target=run_orchestration, args=("a", run_a["id"], rows_a, tmp_path / "a"))
    thread_b = threading.Thread(target=run_orchestration, args=("b", run_b["id"], rows_b, tmp_path / "b"))
    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=30)
    thread_b.join(timeout=30)

    assert not errors, errors
    assert not thread_a.is_alive() and not thread_b.is_alive()
    assert len(results.get("a", [])) == 4
    assert len(results.get("b", [])) == 4

    assert len(call_times) == 8
    assert len(acquire_times) == 8

    timestamps = sorted(acquire_times)
    max_in_any_window = 0
    for anchor in timestamps:
        # Backward-looking window ending at (and including) ``anchor``, which
        # matches the sliding-window invariant SharedRateLimiter enforces at
        # the moment each reservation is granted.
        count = sum(1 for other in timestamps if anchor - window_seconds < other <= anchor)
        max_in_any_window = max(max_in_any_window, count)
    assert max_in_any_window <= requests_per_minute, (
        f"combined request rate exceeded configured budget: max_in_window={max_in_any_window}, "
        f"limit={requests_per_minute}, timestamps={timestamps}"
    )
    # Sanity check contention actually happened across the two concurrent
    # runs (8 requests can't all fit in one 1s window at a budget of 2).
    assert timestamps[-1] - timestamps[0] > window_seconds
