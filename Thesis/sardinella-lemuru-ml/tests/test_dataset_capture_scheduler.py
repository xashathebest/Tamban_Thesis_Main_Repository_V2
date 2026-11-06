"""Scheduling timing is verified without sleeping or opening a webcam."""
import pytest

from src.api.dataset_capture.errors import CaptureError
from test_dataset_capture_service import rig


@pytest.mark.parametrize("countdown", [0, 5, 10])
@pytest.mark.parametrize("target", [3, 25])
def test_countdown_then_fresh_once_per_second_and_target_completion(rig, countdown, target):
    service, clock, store, _ = rig
    began = clock()
    service.start_run(countdown=countdown, target_count=target)
    if countdown:
        clock.advance(countdown - .01)
        service.tick()
        assert store.photos == []
        clock.advance(.01)
    for index in range(target):
        service.tick()
        if index < target - 1:
            clock.advance(1)
    assert [p["metadata"]["captured_monotonic"] for p in store.photos] == pytest.approx([began + countdown + i for i in range(target)])
    assert all(p["capture_mode"] == "automatic" for p in store.photos)
    assert service.status()["run"]["stop_reason"] == "target_count"


@pytest.mark.parametrize("duration", [5, 10])
def test_burst_duration_is_distinct_from_countdown(rig, duration):
    service, clock, store, _ = rig
    service.start_run(countdown=5, duration=duration)
    clock.advance(5)
    for _ in range(duration):
        service.tick()
        clock.advance(1)
    service.tick()
    assert len(store.photos) == duration
    assert service.status()["run"]["state"] == "completed"
    assert service.status()["run"]["stop_reason"] == "duration"


def test_missed_deadlines_save_only_current_slot_without_backfill(rig):
    service, clock, store, _ = rig
    service.start_run()
    service.tick()
    clock.advance(3.2)
    service.tick()
    run = service.status()["run"]
    assert len(store.photos) == 2
    assert run["scheduled"] == 4 and run["skipped"] == 2
    assert run["next_due"] == 104.
    assert run["late"] == 1
    assert store.photos[-1]["scheduled_monotonic"] == 103.


def test_manual_during_auto_preserves_due_shot_and_fresh_distinct_ids(rig):
    service, clock, store, sources = rig
    service.start_run(target_count=3)
    service.snapshot()
    clock.advance(1)
    service.tick()
    clock.advance(1)
    service.tick()
    assert [p["capture_mode"] for p in store.photos] == ["automatic", "manual", "automatic", "automatic"]
    assert len({p["metadata"]["frame_id"] for p in store.photos}) == 4
    assert len(sources) == 1
    assert service.status()["run"]["captured"] == 3
    assert service.status()["manual_count"] == 1


def test_pause_resume_preserves_remaining_countdown_and_duration(rig):
    service, clock, store, _ = rig
    service.start_run(countdown=5, duration=5)
    clock.advance(2)
    service.pause()
    clock.advance(100)
    service.tick()
    assert store.photos == []
    assert service.status()["run"]["countdown_remaining"] == 3.
    service.resume()
    clock.advance(3)
    service.tick()
    assert len(store.photos) == 1
    assert service.status()["run"]["duration_remaining"] == 5.
    service.stop_run()
    clock.advance(10)
    service.tick()
    assert len(store.photos) == 1


def test_manual_shot_during_pause_does_not_advance_automatic_target(rig):
    service, clock, store, _ = rig
    service.start_run(target_count=2)
    service.tick()
    service.pause()
    clock.advance(10)
    service.snapshot()
    assert [p["capture_mode"] for p in store.photos] == ["automatic", "manual"]
    assert service.status()["run"]["captured"] == 1
    service.resume()
    clock.advance(1)
    service.tick()
    assert service.status()["run"]["stop_reason"] == "target_count"


def test_automatic_save_failure_stops_run_and_counts_failed_slot(rig):
    service, _, store, _ = rig
    service.start_run()
    store.fail_save = True
    with pytest.raises(CaptureError):
        service.tick()
    run = service.status()["run"]
    assert run["state"] == "error" and run["skipped"] == 1
    assert run["captured"] == 0
    assert store.photos == []


def test_session_switch_is_refused_until_run_stops(rig):
    service, _, _, _ = rig
    service.start_run()
    with pytest.raises(CaptureError) as raised:
        service.create_session({})
    assert raised.value.status_code == 409
    service.stop_run()
    assert service.create_session({})["id"] == "session-2"


def test_run_ending_while_scheduler_was_unavailable_records_skips(rig):
    service, clock, store, _ = rig
    service.start_run(duration=5)
    clock.advance(10)
    service.tick()
    assert store.photos == []
    run = service.status()["run"]
    assert run["scheduled"] == run["skipped"] == 5
    assert run["state"] == "completed"


@pytest.mark.parametrize("kwargs", [{"interval": 0}, {"interval": 3}, {"countdown": 3}, {"duration": -1}, {"duration": float("nan")}, {"target_count": True}, {"target_count": 10001}])
def test_invalid_run_parameters_do_not_start_a_timer(rig, kwargs):
    service, _, _, _ = rig
    with pytest.raises(CaptureError) as raised:
        service.start_run(**kwargs)
    assert raised.value.status_code == 422
    assert service.status()["run"]["state"] == "idle"

