"""Bound upload bodies and retained results without changing video analysis."""

from __future__ import annotations

import asyncio
import importlib
from pathlib import Path
from threading import RLock
from types import SimpleNamespace

from fastapi import HTTPException
import pytest

from src.api.image_analysis import VideoUploadError


@pytest.fixture
def jobs(monkeypatch):
    app = importlib.import_module("src.api.app")
    pending = []
    analyzed_paths = []
    result = {"fish": [{"id": 7, "quality": "Class B"}], "annotated_frames": [f"full-frame-{i}" for i in range(90)]}

    class HeldThread:
        def __init__(self, *, target, args, daemon):
            assert daemon is True
            self.target, self.args = target, args

        def start(self):
            pending.append(self)

    class Analyzer:
        def __init__(self, image_analyzer):
            assert image_analyzer is app.image_analyzer

        def analyze(self, path, callback):
            analyzed_paths.append(Path(path))
            callback(10, 90)
            assert any(job["status"] == "running" and job["processed_frames"] == 10 for job in app.video_jobs.values())
            return result

    monkeypatch.setattr(app, "video_jobs", {})
    monkeypatch.setattr(app, "video_jobs_lock", RLock())
    monkeypatch.setattr(app, "VIDEO_JOB_MAX_ACTIVE", 2)
    monkeypatch.setattr(app, "VIDEO_JOB_MAX_COMPLETED", 2)
    monkeypatch.setattr(app, "VIDEO_JOB_TTL_SECONDS", 1800)
    monkeypatch.setattr(app, "Thread", HeldThread)
    monkeypatch.setattr(app, "VideoUploadAnalyzer", Analyzer)
    monkeypatch.setattr(app, "image_analyzer", object())
    monkeypatch.setattr(app, "model", SimpleNamespace(model=object(), error=None))
    monkeypatch.setattr(app, "service", SimpleNamespace(_processing_lock=RLock()))
    return SimpleNamespace(app=app, pending=pending, result=result, analyzed_paths=analyzed_paths)


def request(body=b"video", *, received=None, filename="fish.mp4", declared_length=None):
    async def stream():
        if received is not None:
            received.append(True)
        yield body

    headers = {"x-filename": filename}
    if declared_length is not None:
        headers["content-length"] = str(declared_length)
    return SimpleNamespace(headers=headers, stream=stream)


def accept(jobs, **kwargs):
    return asyncio.run(jobs.app.analyze_video(request(**kwargs)))["job_id"]


def run_next(jobs):
    worker = jobs.pending.pop(0)
    worker.target(*worker.args)


def test_backpressure_rejects_before_reading_or_spawning_another_thread(jobs):
    first, second = accept(jobs), accept(jobs)
    received = []
    with pytest.raises(HTTPException) as error:
        accept(jobs, received=received)
    assert error.value.status_code == 429
    assert received == []
    assert len(jobs.pending) == 2
    assert set(jobs.app.video_jobs) == {first, second}
    assert all(job["status"] == "queued" for job in jobs.app.video_jobs.values())


def test_completed_slot_is_reusable_and_all_existing_analysis_frames_are_preserved(jobs):
    first, second = accept(jobs), accept(jobs)
    run_next(jobs)
    completed = jobs.app.analyze_video_status(first)
    assert completed["status"] == "complete"
    assert completed["result"] is jobs.result
    assert len(completed["result"]["annotated_frames"]) == 90
    assert completed["progress"] == 100
    assert all(field in completed for field in ("created_at", "updated_at", "started_at", "finished_at", "expires_at"))
    assert not any(key.startswith("_") for key in completed)
    assert jobs.analyzed_paths and all(not path.exists() for path in jobs.analyzed_paths)
    third = accept(jobs)
    assert jobs.app.video_jobs[second]["status"] == jobs.app.video_jobs[third]["status"] == "queued"


@pytest.mark.parametrize("failure", [RuntimeError("model unavailable"), VideoUploadError("invalid video"), ValueError("unexpected decoder error")])
def test_worker_errors_release_active_capacity_and_remove_temporary_video(jobs, monkeypatch, failure):
    monkeypatch.setattr(jobs.app, "VIDEO_JOB_MAX_ACTIVE", 1)
    paths = []

    class BrokenAnalyzer:
        def __init__(self, _analyzer):
            pass

        def analyze(self, path, _callback):
            paths.append(Path(path))
            raise failure

    monkeypatch.setattr(jobs.app, "VideoUploadAnalyzer", BrokenAnalyzer)
    job_id = accept(jobs)
    run_next(jobs)
    status = jobs.app.analyze_video_status(job_id)
    assert status["status"] == "error"
    assert status["finished_at"]
    assert status["error"] == ("Video analysis failed unexpectedly (ValueError)." if isinstance(failure, ValueError) and not isinstance(failure, VideoUploadError) else str(failure))
    assert all(not path.exists() for path in paths)
    assert accept(jobs) in jobs.app.video_jobs


def test_receiving_upload_reserves_capacity_and_cancellation_releases_it(jobs, monkeypatch):
    monkeypatch.setattr(jobs.app, "VIDEO_JOB_MAX_ACTIVE", 1)

    async def exercise():
        entered, release = asyncio.Event(), asyncio.Event()
        closed = []

        async def stream():
            try:
                entered.set()
                await release.wait()
                yield b"video"
            finally:
                closed.append(True)

        receiving = asyncio.create_task(jobs.app.analyze_video(SimpleNamespace(headers={"x-filename": "fish.mp4"}, stream=stream)))
        await entered.wait()
        assert [job["status"] for job in jobs.app.video_jobs.values()] == ["receiving"]
        read = []
        with pytest.raises(HTTPException) as error:
            await jobs.app.analyze_video(request(received=read))
        assert error.value.status_code == 429
        assert read == []
        receiving.cancel()
        with pytest.raises(asyncio.CancelledError):
            await receiving
        assert closed == [True]
        assert jobs.app.video_jobs == {}
        assert await jobs.app.analyze_video(request())

    asyncio.run(exercise())


@pytest.mark.parametrize("kind", ["empty", "too_large", "disconnect"])
def test_invalid_or_interrupted_body_frees_its_reservation(jobs, monkeypatch, kind):
    monkeypatch.setattr(jobs.app, "VIDEO_JOB_MAX_ACTIVE", 1)
    monkeypatch.setattr(jobs.app, "FISH_VIDEO_MAX_BYTES", 5)

    async def stream():
        if kind == "disconnect":
            raise OSError("client disconnected")
        yield b"123456" if kind == "too_large" else b""

    with pytest.raises(OSError if kind == "disconnect" else HTTPException):
        asyncio.run(jobs.app.analyze_video(SimpleNamespace(headers={"x-filename": "fish.mp4"}, stream=stream)))
    assert jobs.app.video_jobs == {}
    assert jobs.pending == []
    assert accept(jobs) in jobs.app.video_jobs


@pytest.mark.parametrize("kwargs,status", [({"filename": "fish.txt"}, 400), ({"declared_length": 999}, 413)])
def test_invalid_headers_do_not_read_or_reserve(jobs, monkeypatch, kwargs, status):
    monkeypatch.setattr(jobs.app, "FISH_VIDEO_MAX_BYTES", 5)
    received = []
    with pytest.raises(HTTPException) as error:
        accept(jobs, received=received, **kwargs)
    assert error.value.status_code == status
    assert received == []
    assert jobs.app.video_jobs == {}


def test_worker_start_failure_frees_reservation(jobs, monkeypatch):
    class BrokenThread:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            raise RuntimeError("worker could not start")

    monkeypatch.setattr(jobs.app, "Thread", BrokenThread)
    with pytest.raises(RuntimeError, match="could not start"):
        accept(jobs)
    assert jobs.app.video_jobs == {}


def test_video_analysis_keeps_model_mutation_and_frame_processing_locks_in_order(jobs, monkeypatch):
    entered = []

    class Guard:
        def __init__(self, name):
            self.name = name

        def __enter__(self):
            entered.append(f"enter {self.name}")

        def __exit__(self, *_args):
            entered.append(f"exit {self.name}")

    class LockedAnalyzer:
        def __init__(self, _analyzer):
            pass

        def analyze(self, _path, _callback):
            assert entered == ["enter model", "enter processing"]
            return jobs.result

    monkeypatch.setattr(jobs.app, "_model_change_lock", Guard("model"))
    monkeypatch.setattr(jobs.app, "service", SimpleNamespace(_processing_lock=Guard("processing")))
    monkeypatch.setattr(jobs.app, "VideoUploadAnalyzer", LockedAnalyzer)
    job_id = accept(jobs)
    run_next(jobs)
    assert jobs.app.analyze_video_status(job_id)["status"] == "complete"
    assert entered == ["enter model", "enter processing", "exit processing", "exit model"]


def test_completed_retention_never_evicts_inflight_jobs(jobs):
    active = accept(jobs)
    held = jobs.pending.pop(0)
    terminal_ids = []
    for _ in range(6):
        terminal_ids.append(accept(jobs))
        run_next(jobs)
        assert jobs.app.video_jobs[active]["status"] == "queued"
        assert sum(job["status"] == "complete" for job in jobs.app.video_jobs.values()) <= 2
    assert set(jobs.app.video_jobs) == {active, *terminal_ids[-2:]}
    with pytest.raises(HTTPException) as error:
        jobs.app.analyze_video_status(terminal_ids[0])
    assert error.value.status_code == 404
    held.target(*held.args)
    assert jobs.app.analyze_video_status(active)["status"] == "complete"
    assert len(jobs.app.video_jobs) == 2


def test_terminal_ttl_expires_on_poll_without_expiring_queued_or_running(jobs, monkeypatch):
    complete, queued = accept(jobs), accept(jobs)
    run_next(jobs)
    finished = jobs.app.video_jobs[complete]["_finished_monotonic"]
    jobs.app.video_jobs["running"] = {"status": "running", "created_at": "very old"}
    monkeypatch.setattr(jobs.app, "monotonic", lambda: finished + 1801)
    with pytest.raises(HTTPException) as error:
        jobs.app.analyze_video_status(complete)
    assert error.value.status_code == 404
    assert set(jobs.app.video_jobs) == {queued, "running"}
