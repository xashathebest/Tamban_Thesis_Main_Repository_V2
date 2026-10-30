"""Unit tests for the ordered non-blocking persistence hand-off."""

from __future__ import annotations

from threading import Event, Thread
from time import monotonic

from src.api.event_persistence import OrderedPersistenceDispatcher


def test_dispatcher_preserves_fifo_and_snapshots_input() -> None:
    persisted: list[dict[str, object]] = []
    dispatcher = OrderedPersistenceDispatcher(persisted.append, capacity=4)
    first = {"action": "created", "event": {"track_id": 7, "quality": "Ungraded"}}

    assert dispatcher.submit_nowait(first)
    first["event"]["quality"] = "mutated"
    assert dispatcher.submit_nowait({"action": "updated", "event": {"track_id": 7, "quality": "Class A"}})
    assert dispatcher.drain(timeout=2)

    assert persisted == [
        {"action": "created", "event": {"track_id": 7, "quality": "Ungraded"}},
        {"action": "updated", "event": {"track_id": 7, "quality": "Class A"}},
    ]
    snapshot = dispatcher.snapshot()
    assert snapshot["completed"] == 2
    assert snapshot["pending"] == 0
    assert dispatcher.shutdown(timeout=2)


def test_submit_nowait_reports_bounded_backpressure_without_waiting() -> None:
    entered = Event()
    release = Event()

    def persist(_record: object) -> None:
        entered.set()
        assert release.wait(2)

    dispatcher = OrderedPersistenceDispatcher(persist, capacity=1)
    assert dispatcher.submit_nowait({"track_id": 1})
    assert entered.wait(2)

    started = monotonic()
    assert dispatcher.submit_nowait({"track_id": 2}) is False
    assert monotonic() - started < .2
    assert dispatcher.snapshot()["rejected_full"] == 1

    release.set()
    assert dispatcher.drain(timeout=2)
    assert dispatcher.shutdown(timeout=2)


def test_submit_applies_ordered_backpressure_without_bypassing_the_head() -> None:
    entered = Event()
    release = Event()
    submitted = Event()
    persisted: list[int] = []

    def persist(record: dict[str, int]) -> None:
        persisted.append(record["track_id"])
        if record["track_id"] == 1:
            entered.set()
            assert release.wait(2)

    dispatcher = OrderedPersistenceDispatcher(persist, capacity=1)
    assert dispatcher.submit({"track_id": 1})
    assert entered.wait(2)

    def submit_second() -> None:
        assert dispatcher.submit({"track_id": 2})
        submitted.set()

    producer = Thread(target=submit_second)
    producer.start()
    try:
        assert not submitted.wait(.1)
        assert dispatcher.snapshot()["backpressure_waits"] == 1
    finally:
        release.set()
    producer.join(2)

    assert not producer.is_alive() and submitted.is_set()
    assert dispatcher.drain(timeout=2)
    assert persisted == [1, 2]
    snapshot = dispatcher.snapshot()
    assert snapshot["rejected_full"] == 0
    assert snapshot["backpressure_wait_ms"] > 0
    assert dispatcher.shutdown(timeout=2)


def test_failure_retains_head_stops_fifo_and_reports_recovery_record() -> None:
    attempted: list[int] = []

    def persist(record: dict[str, int]) -> None:
        attempted.append(record["track_id"])
        raise OSError("database temporarily unavailable")

    dispatcher = OrderedPersistenceDispatcher(persist, capacity=3)
    original = {"track_id": 1}
    assert dispatcher.submit_nowait(original)
    assert dispatcher.submit_nowait({"track_id": 2})
    original["track_id"] = 99

    assert dispatcher.drain(timeout=2) is False
    snapshot = dispatcher.snapshot()
    assert attempted == [1]
    assert snapshot["failed"] is True
    assert snapshot["pending"] == 2
    assert snapshot["failure"] == {
        "exception_type": "OSError",
        "message": "database temporarily unavailable",
    }
    assert dispatcher.failed_record() == {"track_id": 1}
    assert dispatcher.submit_nowait({"track_id": 3}) is False
    assert snapshot["completed"] == 0
    assert dispatcher.shutdown(timeout=2) is False


def test_shutdown_flushes_accepted_work_in_order() -> None:
    persisted: list[int] = []
    dispatcher = OrderedPersistenceDispatcher(lambda record: persisted.append(record["track_id"]), capacity=4)

    assert dispatcher.submit_nowait({"track_id": 1})
    assert dispatcher.submit_nowait({"track_id": 2})
    assert dispatcher.shutdown(timeout=2)
    assert persisted == [1, 2]
    snapshot = dispatcher.snapshot()
    assert snapshot["accepting"] is False
    assert snapshot["worker_alive"] is False
