"""Ordered, bounded hand-off for durable inspection-event writes.

The dispatcher deliberately owns exactly one worker.  It is suitable for a
camera pipeline that must hand an immutable event snapshot to slower durable
storage without changing the order in which a create, update, and review reach
that store.  It never silently drops a failed item: the failed head stays
retained, subsequent items are not processed out of order, and callers can
inspect the failure before deciding how to recover.
"""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from threading import Condition, Lock, Thread
from time import monotonic
from typing import Callable, Generic, TypeVar


T = TypeVar("T")


@dataclass(frozen=True)
class PersistenceFailure(Generic[T]):
    """A retained worker failure and the record that was not acknowledged."""

    record: T
    exception_type: str
    message: str


class OrderedPersistenceDispatcher(Generic[T]):
    """Run one FIFO persistence callback outside latency-sensitive callers.

    ``submit_nowait`` is intentionally non-blocking and returns ``False`` when
    the bounded hand-off cannot safely accept another record.  ``submit``
    applies ordered producer backpressure instead: it waits for capacity rather
    than letting a newer record bypass an older queued record.  ``drain`` and
    ``shutdown`` wait for work already accepted by the dispatcher.
    """

    def __init__(
        self,
        persist: Callable[[T], None],
        *,
        capacity: int = 256,
        thread_name: str = "inspection-event-persistence",
    ) -> None:
        if not callable(persist):
            raise TypeError("persist must be callable")
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity <= 0:
            raise ValueError("capacity must be a positive integer")

        self._persist = persist
        self._capacity = capacity
        self._condition = Condition(Lock())
        # A producer that found the bounded queue full must retain its place in
        # line.  Without this gate, two waiting producers can race after a
        # condition wake-up and reverse their submission order.
        self._submit_lock = Lock()
        self._pending: deque[T] = deque()
        self._in_flight = False
        self._accepting = True
        self._stopping = False
        self._failure: PersistenceFailure[T] | None = None
        self._accepted = 0
        self._completed = 0
        self._rejected_full = 0
        self._backpressure_waits = 0
        self._backpressure_wait_seconds = 0.0
        self._rejected_timeout = 0
        self._rejected_stopped = 0
        self._rejected_failed = 0
        self._worker = Thread(target=self._run, name=thread_name, daemon=True)
        self._worker.start()

    def submit_nowait(self, record: T) -> bool:
        """Copy and queue one record, returning ``False`` rather than waiting.

        The copy makes later mutation by the camera/domain path harmless.  A
        failed copy is a programming/input error rather than a capacity state,
        so it is reported directly to the caller.
        """

        # A blocking producer owns its place in FIFO order while it waits for
        # capacity.  A nonblocking caller must not wait behind it *or* sneak
        # past it, so report backpressure immediately in that narrow case.
        if not self._submit_lock.acquire(blocking=False):
            with self._condition:
                self._rejected_full += 1
            return False
        try:
            copied = self._copy_record(record)
            with self._condition:
                if self._failure is not None:
                    self._rejected_failed += 1
                    return False
                if not self._accepting:
                    self._rejected_stopped += 1
                    return False
                # The in-flight head deliberately remains in ``_pending`` until it
                # succeeds, so this capacity also includes active work.
                if len(self._pending) >= self._capacity:
                    self._rejected_full += 1
                    return False
                self._pending.append(copied)
                self._accepted += 1
                self._condition.notify_all()
                return True
        finally:
            self._submit_lock.release()

    def submit(self, record: T, *, timeout: float | None = None) -> bool:
        """Copy and submit a record in FIFO order, applying bounded backpressure.

        A successful call means the dispatcher owns an immutable copy.  When
        the queue is full, this method waits for the oldest item to complete
        instead of performing an out-of-order direct write.  ``timeout=None``
        is the lossless conveyor-safe mode.  A finite timeout is available for
        callers that need to surface a failed operation without closing or
        rotating its durable session.
        """

        deadline = None if timeout is None else monotonic() + max(0.0, timeout)
        with self._submit_lock:
            copied = self._copy_record(record)
            with self._condition:
                if self._failure is not None:
                    self._rejected_failed += 1
                    return False
                if not self._accepting:
                    self._rejected_stopped += 1
                    return False
                waited_from: float | None = None
                while len(self._pending) >= self._capacity:
                    if waited_from is None:
                        waited_from = monotonic()
                        self._backpressure_waits += 1
                    if self._failure is not None:
                        self._rejected_failed += 1
                        self._record_backpressure_wait_locked(waited_from)
                        return False
                    if not self._accepting:
                        self._rejected_stopped += 1
                        self._record_backpressure_wait_locked(waited_from)
                        return False
                    if deadline is None:
                        self._condition.wait()
                        continue
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        self._rejected_timeout += 1
                        self._record_backpressure_wait_locked(waited_from)
                        return False
                    self._condition.wait(remaining)
                self._record_backpressure_wait_locked(waited_from)
                if self._failure is not None:
                    self._rejected_failed += 1
                    return False
                if not self._accepting:
                    self._rejected_stopped += 1
                    return False
                self._pending.append(copied)
                self._accepted += 1
                self._condition.notify_all()
                return True

    def drain(self, timeout: float | None = None) -> bool:
        """Wait for every accepted item to persist, or return ``False``.

        ``False`` means either the timeout elapsed or a worker failure retained
        a record.  In both cases no queued item is discarded.
        """

        deadline = None if timeout is None else monotonic() + max(0.0, timeout)
        with self._condition:
            while self._pending or self._in_flight:
                if self._failure is not None:
                    return False
                if deadline is None:
                    self._condition.wait()
                    continue
                remaining = deadline - monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return self._failure is None

    def shutdown(self, timeout: float | None = None) -> bool:
        """Stop accepting work, flush accepted work when possible, and join.

        A timeout or retained worker failure returns ``False`` without clearing
        the queue.  The caller therefore remains responsible for a visible
        recovery/fallback path instead of losing an inspection record.
        """

        with self._condition:
            self._accepting = False
            self._stopping = True
            self._condition.notify_all()
        self._worker.join(timeout=max(0.0, timeout) if timeout is not None else None)
        with self._condition:
            return (
                not self._worker.is_alive()
                and not self._pending
                and not self._in_flight
                and self._failure is None
            )

    def failed_record(self) -> T | None:
        """Return a copy of the retained failed head for explicit recovery."""

        with self._condition:
            return deepcopy(self._failure.record) if self._failure is not None else None

    def snapshot(self) -> dict[str, object]:
        """Return bounded operational state without exposing record contents."""

        with self._condition:
            failure = self._failure
            return {
                "capacity": self._capacity,
                "pending": len(self._pending),
                "in_flight": self._in_flight,
                "accepting": self._accepting,
                "stopping": self._stopping,
                "worker_alive": self._worker.is_alive(),
                "accepted": self._accepted,
                "completed": self._completed,
                "rejected_full": self._rejected_full,
                "backpressure_waits": self._backpressure_waits,
                "backpressure_wait_ms": round(self._backpressure_wait_seconds * 1000.0, 3),
                "rejected_timeout": self._rejected_timeout,
                "rejected_stopped": self._rejected_stopped,
                "rejected_failed": self._rejected_failed,
                "failed": failure is not None,
                "failure": (
                    {"exception_type": failure.exception_type, "message": failure.message}
                    if failure is not None
                    else None
                ),
            }

    @staticmethod
    def _copy_record(record: T) -> T:
        try:
            return deepcopy(record)
        except Exception as exc:  # pragma: no cover - depends on arbitrary T
            raise TypeError("Persistence records must support deepcopy.") from exc

    def _record_backpressure_wait_locked(self, started: float | None) -> None:
        if started is not None:
            self._backpressure_wait_seconds += max(0.0, monotonic() - started)

    def _run(self) -> None:
        """Persist only the current head, retaining it if the callback fails."""

        while True:
            with self._condition:
                while not self._pending and not self._stopping:
                    self._condition.wait()
                if not self._pending:
                    return
                record = self._pending[0]
                self._in_flight = True
            try:
                self._persist(deepcopy(record))
            except Exception as exc:  # pragma: no cover - exact exception is callback-owned
                with self._condition:
                    self._in_flight = False
                    self._failure = PersistenceFailure(
                        record=record,
                        exception_type=type(exc).__name__,
                        message=" ".join(str(exc).split())[:500],
                    )
                    # Reject new work rather than accepting records that cannot
                    # safely pass the retained failed head in FIFO order.
                    self._accepting = False
                    self._condition.notify_all()
                return
            with self._condition:
                # The worker is the only consumer and retains the current head
                # while invoking the callback, so this always removes exactly
                # the record that just succeeded.
                self._pending.popleft()
                self._completed += 1
                self._in_flight = False
                self._condition.notify_all()
