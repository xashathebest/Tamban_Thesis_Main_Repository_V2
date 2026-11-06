"""Durable SQLite storage for inspection sessions and completed fish events.

The live tracker intentionally remains in memory for low-latency overlays.  This
module is its durable counterpart: it stores a session policy snapshot
and upserts the latest evidence for each ``(session_id, track_id)`` inspection
event.  Keeping the original JSON event alongside indexed columns makes history
and exports both convenient and reproducible without coupling persistence to a
particular grading-engine revision.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
from hashlib import sha256
import json
import math
from pathlib import Path
import sqlite3
from threading import RLock
from time import monotonic
from typing import Iterator, Mapping
from uuid import uuid4


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _json(value: object) -> str:
    """Serialize metadata predictably while retaining diagnostic values safely."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _decoded(value: object, default: object) -> object:
    if not isinstance(value, str):
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _finite(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def grading_config_hash(config: Mapping[str, object] | None) -> str | None:
    """Return a stable policy fingerprint, or ``None`` when no policy is known."""

    if not config:
        return None
    return sha256(_json(dict(config)).encode("utf-8")).hexdigest()


class InspectionDatabase:
    """Thread-safe, standard-library SQLite store for the canonical web app."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._lock = RLock()
        self._initialized = False

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        self.initialize()
        connection = sqlite3.connect(str(self.path), timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.create_function("event_local_date", 2, _event_local_date, deterministic=True)
        connection.create_function("history_matches", 8, _history_matches, deterministic=True)
        connection.create_function("history_verdict", 2, _history_verdict, deterministic=True)
        connection.create_function("history_has_reason", 3, _history_has_reason, deterministic=True)
        connection.create_function("history_region_present", 3, _history_region_present, deterministic=True)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 10000")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        """Create the small durable schema lazily, so import-time has no writes."""

        with self._lock:
            if self._initialized:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(str(self.path), timeout=10.0)
            try:
                connection.execute("PRAGMA foreign_keys = ON")
                # WAL lets the camera worker insert an event while a dashboard
                # request is reading history, without requiring a second service.
                connection.execute("PRAGMA journal_mode = WAL")
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS inspection_sessions (
                        session_id TEXT PRIMARY KEY,
                        started_at TEXT NOT NULL,
                        ended_at TEXT,
                        git_commit TEXT,
                        model1_path TEXT,
                        model1_sha256 TEXT,
                        model2_path TEXT,
                        model2_sha256 TEXT,
                        tracker_backend TEXT,
                        grading_config_json TEXT NOT NULL DEFAULT '{}',
                        grading_config_hash TEXT,
                        camera_settings_json TEXT NOT NULL DEFAULT '{}',
                        runtime_settings_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS fish_inspections (
                        session_id TEXT NOT NULL,
                        track_id INTEGER NOT NULL,
                        timestamp TEXT NOT NULL,
                        final_grade TEXT NOT NULL,
                        final_support REAL,
                        second_grade TEXT,
                        second_support REAL,
                        grade_margin REAL,
                        evidence_coverage REAL,
                        observed_regions_json TEXT NOT NULL DEFAULT '[]',
                        reason_codes_json TEXT NOT NULL DEFAULT '[]',
                        model1_confidence REAL,
                        weighted_scores_json TEXT NOT NULL DEFAULT '{}',
                        part_results_json TEXT NOT NULL DEFAULT '{}',
                        color_measurements_json TEXT NOT NULL DEFAULT '{}',
                        analysis_json TEXT NOT NULL DEFAULT '{}',
                        processing_time_ms REAL,
                        event_json TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (session_id, track_id),
                        FOREIGN KEY (session_id) REFERENCES inspection_sessions(session_id)
                            ON DELETE RESTRICT
                    );

                    CREATE INDEX IF NOT EXISTS idx_fish_inspections_timestamp
                        ON fish_inspections(timestamp DESC);
                    CREATE INDEX IF NOT EXISTS idx_fish_inspections_session_timestamp
                        ON fish_inspections(session_id, timestamp DESC);
                    CREATE INDEX IF NOT EXISTS idx_fish_inspections_grade
                        ON fish_inspections(final_grade);
                    CREATE INDEX IF NOT EXISTS idx_fish_history_order
                        ON fish_inspections(timestamp DESC, updated_at DESC, track_id DESC, session_id DESC);
                    CREATE INDEX IF NOT EXISTS idx_fish_session_history_order
                        ON fish_inspections(session_id, timestamp DESC, updated_at DESC, track_id DESC);

                    CREATE TABLE IF NOT EXISTS inspection_event_revisions (
                        session_id TEXT PRIMARY KEY,
                        revision INTEGER NOT NULL DEFAULT 0
                    );
                    CREATE TABLE IF NOT EXISTS inspection_event_changes (
                        change_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        track_id INTEGER NOT NULL,
                        kind TEXT NOT NULL,
                        UNIQUE(session_id, track_id)
                    );
                    CREATE INDEX IF NOT EXISTS idx_inspection_changes_session_id
                        ON inspection_event_changes(session_id, change_id);
                    CREATE TABLE IF NOT EXISTS inspection_previous_events (
                        session_id TEXT NOT NULL,
                        track_id INTEGER NOT NULL,
                        event_json TEXT NOT NULL,
                        PRIMARY KEY(session_id, track_id)
                    );
                    CREATE TABLE IF NOT EXISTS inspection_review_audit (
                        audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        track_id INTEGER NOT NULL,
                        previous_grade TEXT,
                        manual_grade TEXT,
                        reviewer TEXT,
                        reviewed_at TEXT NOT NULL,
                        source TEXT NOT NULL,
                        FOREIGN KEY(session_id, track_id) REFERENCES fish_inspections(session_id, track_id)
                    );
                    CREATE INDEX IF NOT EXISTS idx_inspection_review_audit_fish
                        ON inspection_review_audit(session_id, track_id, audit_id);
                    CREATE TRIGGER IF NOT EXISTS fish_previous_update AFTER UPDATE ON fish_inspections
                    BEGIN
                        INSERT INTO inspection_previous_events(session_id, track_id, event_json) VALUES (OLD.session_id, OLD.track_id, OLD.event_json)
                        ON CONFLICT(session_id, track_id) DO UPDATE SET event_json = excluded.event_json;
                    END;
                    CREATE TRIGGER IF NOT EXISTS fish_change_insert AFTER INSERT ON fish_inspections
                    BEGIN
                        INSERT INTO inspection_event_changes(session_id, track_id, kind) VALUES (NEW.session_id, NEW.track_id, 'insert')
                        ON CONFLICT(session_id, track_id) DO UPDATE SET change_id = excluded.change_id, kind = 'update';
                    END;
                    CREATE TRIGGER IF NOT EXISTS fish_change_update AFTER UPDATE ON fish_inspections
                    BEGIN
                        INSERT INTO inspection_event_changes(session_id, track_id, kind) VALUES (NEW.session_id, NEW.track_id, 'update')
                        ON CONFLICT(session_id, track_id) DO UPDATE SET change_id = excluded.change_id, kind = 'update';
                    END;
                    CREATE TRIGGER IF NOT EXISTS fish_change_delete AFTER DELETE ON fish_inspections
                    BEGIN
                        INSERT INTO inspection_event_changes(session_id, track_id, kind) VALUES (OLD.session_id, OLD.track_id, 'delete')
                        ON CONFLICT(session_id, track_id) DO UPDATE SET change_id = excluded.change_id, kind = 'delete';
                    END;
                    CREATE TRIGGER IF NOT EXISTS fish_revision_insert AFTER INSERT ON fish_inspections
                    BEGIN
                        INSERT INTO inspection_event_revisions(session_id, revision) VALUES (NEW.session_id, 1)
                        ON CONFLICT(session_id) DO UPDATE SET revision = revision + 1;
                    END;
                    CREATE TRIGGER IF NOT EXISTS fish_revision_update AFTER UPDATE ON fish_inspections
                    BEGIN
                        INSERT INTO inspection_event_revisions(session_id, revision) VALUES (NEW.session_id, 1)
                        ON CONFLICT(session_id) DO UPDATE SET revision = revision + 1;
                        INSERT INTO inspection_event_revisions(session_id, revision)
                            SELECT OLD.session_id, 1 WHERE OLD.session_id != NEW.session_id
                        ON CONFLICT(session_id) DO UPDATE SET revision = revision + 1;
                    END;
                    CREATE TRIGGER IF NOT EXISTS fish_revision_delete AFTER DELETE ON fish_inspections
                    BEGIN
                        INSERT INTO inspection_event_revisions(session_id, revision) VALUES (OLD.session_id, 1)
                        ON CONFLICT(session_id) DO UPDATE SET revision = revision + 1;
                    END;
                    """
                )
                # Additive migration: historical sessions/evidence are retained
                # even when their active capture duration was never measured.
                columns = {row[1] for row in connection.execute("PRAGMA table_info(inspection_sessions)")}
                for name, declaration in {
                    "active_seconds": "REAL", "activity_status": "TEXT NOT NULL DEFAULT 'legacy'",
                    "heartbeat_at": "TEXT", "autosaved_at": "TEXT",
                }.items():
                    if name not in columns:
                        connection.execute(f"ALTER TABLE inspection_sessions ADD COLUMN {name} {declaration}")
                connection.commit()
            finally:
                connection.close()
            self._initialized = True

    def event_revision(self, session_id: str | None) -> int | None:
        """Return the transactionally updated revision for one durable session."""

        if session_id is None:
            return None
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT revision FROM inspection_event_revisions WHERE session_id = ?", (session_id,)
            ).fetchone()
        return int(row["revision"]) if row else 0

    @staticmethod
    def _session_columns(metadata: Mapping[str, object]) -> dict[str, object]:
        grading = _mapping(metadata.get("grading_config"))
        return {
            "started_at": str(metadata.get("started_at") or _now()),
            "ended_at": metadata.get("ended_at"),
            "git_commit": metadata.get("git_commit"),
            "model1_path": metadata.get("model1_path"),
            "model1_sha256": metadata.get("model1_sha256"),
            "model2_path": metadata.get("model2_path"),
            "model2_sha256": metadata.get("model2_sha256"),
            "tracker_backend": metadata.get("tracker_backend"),
            "grading_config_json": _json(grading),
            "grading_config_hash": metadata.get("grading_config_hash") or grading_config_hash(grading),
            "camera_settings_json": _json(_mapping(metadata.get("camera_settings"))),
            "runtime_settings_json": _json(_mapping(metadata.get("runtime_settings"))),
        }

    def create_session(self, metadata: Mapping[str, object] | None = None, *, session_id: str | None = None) -> str:
        """Create one durable configuration snapshot and return its opaque ID."""

        values = self._session_columns(_mapping(metadata))
        identifier = session_id or uuid4().hex
        now = _now()
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO inspection_sessions (
                    session_id, started_at, ended_at, git_commit, model1_path,
                    model1_sha256, model2_path, model2_sha256, tracker_backend,
                    grading_config_json, grading_config_hash, camera_settings_json,
                    runtime_settings_json, created_at, updated_at
                ) VALUES (
                    :session_id, :started_at, :ended_at, :git_commit, :model1_path,
                    :model1_sha256, :model2_path, :model2_sha256, :tracker_backend,
                    :grading_config_json, :grading_config_hash, :camera_settings_json,
                    :runtime_settings_json, :created_at, :updated_at
                )
                """,
                {"session_id": identifier, **values, "created_at": now, "updated_at": now},
            )
            connection.execute(
                "UPDATE inspection_sessions SET active_seconds=0, activity_status=?, heartbeat_at=? WHERE session_id=?",
                ("completed" if values.get("ended_at") else "starting", now, identifier),
            )
        return identifier

    def checkpoint_session_activity(self, session_id: str, active_seconds: float, *, status: str = "active") -> None:
        """Monotonically persist measured active time, including zero-fish runs."""
        seconds = _finite(active_seconds)
        if seconds is None or seconds < 0 or status not in {"active", "paused", "starting"}:
            raise ValueError("Invalid inspection activity checkpoint.")
        now = _now()
        with self._lock, self._connection() as connection:
            connection.execute(
                "UPDATE inspection_sessions SET active_seconds=MAX(COALESCE(active_seconds,0), :seconds), "
                "activity_status=:status, heartbeat_at=:now, updated_at=:now, "
                "autosaved_at=CASE WHEN MAX(COALESCE(active_seconds,0), :seconds)>=60 THEN COALESCE(autosaved_at,:now) ELSE autosaved_at END "
                "WHERE session_id=:session AND ended_at IS NULL",
                {"seconds": seconds, "status": status, "now": now, "session": session_id},
            )

    def recover_interrupted_sessions(self) -> int:
        """Close abandoned runs at their last checkpoint; never count downtime."""
        with self._lock, self._connection() as connection:
            result = connection.execute(
                "UPDATE inspection_sessions SET ended_at=COALESCE(heartbeat_at, updated_at, started_at), "
                "activity_status='interrupted', updated_at=? WHERE ended_at IS NULL", (_now(),),
            )
            return result.rowcount

    def accumulated_active_seconds(self) -> float:
        with self._lock, self._connection() as connection:
            row = connection.execute("SELECT COALESCE(SUM(active_seconds),0) FROM inspection_sessions").fetchone()
        return round(float(row[0]), 3)

    def update_session(self, session_id: str, metadata: Mapping[str, object]) -> None:
        """Refresh known session readbacks without replacing unavailable fields."""

        if not session_id:
            return
        source = _mapping(metadata)
        immutable = {"git_commit", "model1_path", "model1_sha256", "model2_path", "model2_sha256",
                     "tracker_backend", "grading_config", "grading_config_hash", "runtime_settings"}
        if immutable.intersection(source):
            raise ValueError("Session model and grading policy snapshots cannot be changed after creation.")
        # A partial camera readback must not erase a useful snapshot captured at
        # start.  Only explicitly supplied metadata members are updated.
        scalar_columns = ("ended_at",)
        assignments: list[str] = []
        parameters: dict[str, object] = {"session_id": session_id, "updated_at": _now()}
        for key in scalar_columns:
            value = source.get(key)
            if value is None:
                continue
            assignments.append(f"{key} = :{key}")
            parameters[key] = value
        if "camera_settings" in source:
            assignments.append("camera_settings_json = :camera_settings_json")
            parameters["camera_settings_json"] = _json(_mapping(source.get("camera_settings")))
        if not assignments:
            return
        assignments.append("updated_at = :updated_at")
        with self._lock, self._connection() as connection:
            connection.execute(
                f"UPDATE inspection_sessions SET {', '.join(assignments)} WHERE session_id = :session_id",
                parameters,
            )

    def end_session(self, session_id: str, *, ended_at: str | None = None, status: str = "completed") -> None:
        if not session_id:
            return
        if status not in {"completed", "interrupted"}:
            raise ValueError("Invalid closed-session status.")
        with self._lock, self._connection() as connection:
            connection.execute(
                "UPDATE inspection_sessions SET ended_at = COALESCE(ended_at, :ended_at), "
                "activity_status = CASE WHEN activity_status='interrupted' THEN activity_status ELSE :status END, "
                "updated_at = :updated_at WHERE session_id = :session_id",
                {"session_id": session_id, "ended_at": ended_at or _now(), "status": status, "updated_at": _now()},
            )

    @staticmethod
    def _event_columns(event: Mapping[str, object]) -> dict[str, object]:
        analysis = _mapping(event.get("analysis"))
        quality = event.get("quality") or analysis.get("final_grade") or "Ungraded"
        weighted_scores = _mapping(analysis.get("weighted_scores"))
        part_results = _mapping(analysis.get("part_results"))
        colors = _mapping(analysis.get("color"))
        observed = analysis.get("observed_regions")
        observed_regions = list(observed) if isinstance(observed, (list, tuple)) else []
        reason_values = analysis.get("reason_codes")
        if isinstance(reason_values, (list, tuple)):
            reason_codes = [str(value) for value in reason_values if value]
        elif analysis.get("verdict_reason_code"):
            reason_codes = [str(analysis["verdict_reason_code"])]
        else:
            reason_codes = []
        model1 = _mapping(analysis.get("model1_detection"))
        final_support = _finite(analysis.get("final_score"))
        if final_support is None:
            final_support = _finite(event.get("quality_confidence"))
        return {
            "timestamp": str(event.get("timestamp") or _now()),
            "final_grade": str(quality),
            "final_support": final_support,
            "second_grade": analysis.get("second_grade"),
            "second_support": _finite(analysis.get("second_support")),
            "grade_margin": _finite(analysis.get("grade_margin")),
            "evidence_coverage": _finite(analysis.get("original_weight_coverage", analysis.get("evidence_coverage"))),
            "observed_regions_json": _json(observed_regions),
            "reason_codes_json": _json(reason_codes),
            "model1_confidence": _finite(model1.get("confidence", event.get("final_confidence"))),
            "weighted_scores_json": _json(weighted_scores),
            "part_results_json": _json(part_results),
            "color_measurements_json": _json(colors),
            "analysis_json": _json(analysis),
            "processing_time_ms": _finite(event.get("processing_time_ms")),
            "event_json": _json(dict(event)),
        }

    def event_exists(self, session_id: str, track_id: object) -> bool:
        """Check whether a late update belongs to an existing durable event."""

        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT 1 FROM fish_inspections WHERE session_id = ? AND track_id = ?",
                (session_id, track_id),
            ).fetchone()
        return row is not None

    def upsert_event(self, session_id: str, event: Mapping[str, object]) -> None:
        """Persist a completed event or its late grade/review update exactly once."""

        if not session_id:
            raise ValueError("A durable inspection session is required before storing an event.")
        try:
            track_id = int(event["track_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("A persisted inspection event requires an integer track_id.") from exc
        values = self._event_columns(event)
        now = _now()
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO fish_inspections (
                    session_id, track_id, timestamp, final_grade, final_support,
                    second_grade, second_support, grade_margin, evidence_coverage,
                    observed_regions_json, reason_codes_json, model1_confidence,
                    weighted_scores_json, part_results_json, color_measurements_json,
                    analysis_json, processing_time_ms, event_json, updated_at
                ) VALUES (
                    :session_id, :track_id, :timestamp, :final_grade, :final_support,
                    :second_grade, :second_support, :grade_margin, :evidence_coverage,
                    :observed_regions_json, :reason_codes_json, :model1_confidence,
                    :weighted_scores_json, :part_results_json, :color_measurements_json,
                    :analysis_json, :processing_time_ms, :event_json, :updated_at
                ) ON CONFLICT(session_id, track_id) DO UPDATE SET
                    timestamp = excluded.timestamp,
                    final_grade = excluded.final_grade,
                    final_support = excluded.final_support,
                    second_grade = excluded.second_grade,
                    second_support = excluded.second_support,
                    grade_margin = excluded.grade_margin,
                    evidence_coverage = excluded.evidence_coverage,
                    observed_regions_json = excluded.observed_regions_json,
                    reason_codes_json = excluded.reason_codes_json,
                    model1_confidence = excluded.model1_confidence,
                    weighted_scores_json = excluded.weighted_scores_json,
                    part_results_json = excluded.part_results_json,
                    color_measurements_json = excluded.color_measurements_json,
                    analysis_json = excluded.analysis_json,
                    processing_time_ms = excluded.processing_time_ms,
                    event_json = excluded.event_json,
                    updated_at = excluded.updated_at
                """,
                {"session_id": session_id, "track_id": track_id, **values, "updated_at": now},
            )

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> dict[str, object]:
        event = _decoded(row["event_json"], {})
        result = dict(event) if isinstance(event, Mapping) else {}
        result["session_id"] = row["session_id"]
        result.setdefault("track_id", row["track_id"])
        result.setdefault("timestamp", row["timestamp"])
        if not result.get("quality"):
            result["quality"] = row["final_grade"]
        if not isinstance(result.get("analysis"), Mapping):
            result["analysis"] = _decoded(row["analysis_json"], {})
        return result

    @staticmethod
    def _event_query(session_id: str | None, range_name: str, start_date: str | None, end_date: str | None) -> tuple[str, dict[str, object]]:
        if range_name not in {"all", "current_session", "today", "custom"}:
            raise ValueError("Unsupported history range.")
        try:
            lower = date.fromisoformat(start_date) if range_name == "custom" and start_date else None
            upper = date.fromisoformat(end_date) if range_name == "custom" and end_date else None
        except ValueError as exc:
            raise ValueError("Custom history dates must use YYYY-MM-DD.") from exc
        if lower and upper and lower > upper:
            raise ValueError("The start date must not be after the end date.")
        clauses: list[str] = []
        params: dict[str, object] = {}
        if session_id:
            clauses.append("session_id = :session_id")
            params["session_id"] = session_id
        elif range_name == "current_session":
            clauses.append("0")
        if range_name in {"today", "custom"}:
            date_expression = "event_local_date(event_json, timestamp)"
            clauses.append(f"{date_expression} IS NOT NULL")
            if range_name == "today":
                clauses.append(f"{date_expression} = :today")
                params["today"] = date.today().isoformat()
            else:
                if lower:
                    clauses.append(f"{date_expression} >= :lower")
                    params["lower"] = lower.isoformat()
                if upper:
                    clauses.append(f"{date_expression} <= :upper")
                    params["upper"] = upper.isoformat()
        return (f" WHERE {' AND '.join(clauses)}" if clauses else ""), params

    def events_page(self, *, session_id: str | None, range_name: str, start_date: str | None, end_date: str | None,
                    page: int, page_size: int, search: str | None, grade: str | None,
                    feature: str | None, min_confidence: float | None, verdict: str | None = None,
                    track_id: int | None = None, reason_code: str | None = None,
                    evidence_region: str | None = None) -> tuple[list[dict[str, object]], int]:
        """Filter and paginate in SQLite, retaining only the requested page in memory."""
        where, params = self._event_query(session_id, range_name, start_date, end_date)
        if track_id is not None:
            where += (" AND " if where else " WHERE ") + "track_id=:track_id"
            params["track_id"] = track_id
        if verdict and verdict.casefold() != "all":
            where += (" AND " if where else " WHERE ") + "history_verdict(event_json, analysis_json)=:verdict"
            params["verdict"] = verdict.upper()
        if reason_code:
            where += (" AND " if where else " WHERE ") + "history_has_reason(event_json, analysis_json, :reason)"
            params["reason"] = reason_code
        if evidence_region:
            where += (" AND " if where else " WHERE ") + "history_region_present(event_json, analysis_json, :evidence_region)"
            params["evidence_region"] = evidence_region
        if search or (grade and grade.casefold() != "all") or (feature and feature.casefold() != "all") or min_confidence is not None:
            where += (" AND " if where else " WHERE ") + "history_matches(event_json, analysis_json, final_grade, track_id, :search, :grade, :feature, :confidence)"
            params.update(search=search, grade=grade, feature=feature, confidence=min_confidence)
        with self._lock, self._connection() as connection:
            connection.execute("BEGIN")
            total = connection.execute("SELECT count(*) FROM fish_inspections" + where, params).fetchone()[0]
            rows = connection.execute(
                "SELECT session_id, track_id, timestamp, final_grade, event_json, analysis_json FROM fish_inspections"
                + where + " ORDER BY timestamp DESC, updated_at DESC, track_id DESC, session_id DESC LIMIT :limit OFFSET :offset",
                {**params, "limit": page_size, "offset": (page - 1) * page_size},
            ).fetchall()
        return [self._event_from_row(row) for row in rows], total

    def events(
        self,
        *,
        session_id: str | None = None,
        range_name: str = "all",
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict[str, object]]:
        """Read durable events for all, one session, today, or a date range."""

        where, params = self._event_query(session_id, range_name, start_date, end_date)
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT session_id, track_id, timestamp, final_grade, event_json, analysis_json FROM fish_inspections" + where + " ORDER BY timestamp DESC, updated_at DESC, track_id DESC, session_id DESC",
                params,
            ).fetchall()
        return [self._event_from_row(row) for row in rows]

    def iter_events_chronological(self, *, session_id: str | None, range_name: str,
                                  start_date: str | None, end_date: str | None) -> Iterator[dict[str, object]]:
        """Stream a consistent SQLite snapshot in bounded batches for analytics."""
        where, params = self._event_query(session_id, range_name, start_date, end_date)
        with self._connection() as connection:
            connection.execute("BEGIN")
            cursor = connection.execute(
                "SELECT session_id, track_id, timestamp, final_grade, event_json, analysis_json FROM fish_inspections"
                + where + " ORDER BY timestamp ASC, updated_at ASC, track_id ASC, session_id ASC", params,
            )
            while rows := cursor.fetchmany(256):
                for row in rows:
                    yield self._event_from_row(row)

    def analytics_change_marker(self, session_id: str) -> tuple[int, tuple[str, str, int] | None]:
        with self._connection() as connection:
            marker = connection.execute("SELECT COALESCE(MAX(change_id), 0) FROM inspection_event_changes WHERE session_id = ?", (session_id,)).fetchone()[0]
            last = connection.execute("SELECT timestamp, updated_at, track_id FROM fish_inspections WHERE session_id = ? ORDER BY timestamp DESC, updated_at DESC, track_id DESC LIMIT 1", (session_id,)).fetchone()
        return int(marker), (last[0], last[1], last[2]) if last else None

    def analytics_insertions_since(self, session_id: str, marker: int, last_key: tuple[str, str, int] | None) -> list[dict[str, object]] | None:
        """Return a small append-only delta, or None when a full rebuild is needed."""
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT c.kind, f.session_id, f.track_id, f.timestamp, f.updated_at, f.final_grade, f.event_json, f.analysis_json "
                "FROM inspection_event_changes c LEFT JOIN fish_inspections f ON f.session_id=c.session_id AND f.track_id=c.track_id "
                "WHERE c.session_id=? AND c.change_id>? ORDER BY c.change_id LIMIT 101", (session_id, marker),
            ).fetchall()
        if not rows or len(rows) > 100 or any(row["kind"] != "insert" for row in rows):
            return None
        rows = sorted(rows, key=lambda row: (row["timestamp"], row["updated_at"], row["track_id"]))
        keys = [(row["timestamp"], row["updated_at"], row["track_id"]) for row in rows]
        if (last_key is not None and keys[0] <= last_key) or any(a >= b for a, b in zip(keys, keys[1:])):
            return None
        return [self._event_from_row(row) for row in rows]

    def analytics_reviews_since(self, session_id: str, marker: int) -> list[tuple[bool, bool, bool]] | None:
        """Recognize changes limited to manual-review metadata."""
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT c.kind, p.event_json AS previous_json, f.event_json AS current_json "
                "FROM inspection_event_changes c LEFT JOIN inspection_previous_events p "
                "ON p.session_id=c.session_id AND p.track_id=c.track_id "
                "LEFT JOIN fish_inspections f ON f.session_id=c.session_id AND f.track_id=c.track_id "
                "WHERE c.session_id=? AND c.change_id>? ORDER BY c.change_id LIMIT 101", (session_id, marker),
            ).fetchall()
        if not rows or len(rows) > 100:
            return None
        changes = []
        for row in rows:
            old, new = _decoded(row["previous_json"], {}), _decoded(row["current_json"], {})
            if row["kind"] != "update" or not isinstance(old, dict) or not isinstance(new, dict):
                return None
            old_reviewed, new_reviewed = bool(old.get("manual_override")), bool(new.get("manual_override"))
            analysis = old.get("analysis")
            needs_review = isinstance(analysis, dict) and analysis.get("verdict_status") == "NEEDS_REVIEW"
            for key in ("manual_override", "manual_grade", "review_timestamp", "reviewer", "review_source", "session_id"):
                old.pop(key, None)
                new.pop(key, None)
            if old != new:
                return None
            changes.append((old_reviewed, new_reviewed, needs_review))
        return changes

    def sessions(self, *, limit: int = 100) -> list[dict[str, object]]:
        """Return recent session metadata for session-aware history selectors."""
        return self.sessions_page(page_size=max(1, min(int(limit), 1000)))[0]

    def dashboard_analytics(self, *, range_name: str = "all", session_id: str | None = None,
                            start_date: str | None = None, end_date: str | None = None,
                            granularity: str = "day") -> dict[str, object]:
        """Summarize one read-only transaction of persisted sessions and fish."""
        from src.api.saved_analytics import build_dashboard, GRANULARITIES

        if granularity not in GRANULARITIES:
            raise ValueError("Analytics granularity must be hour, day, week, or month.")
        effective_range = "all" if range_name == "latest" else range_name
        # Validate ranges and dates before opening the snapshot.
        self._event_query(session_id, effective_range, start_date, end_date)
        with self._connection() as connection:
            connection.execute("PRAGMA query_only = ON")
            connection.execute("BEGIN")
            if range_name == "latest":
                latest = connection.execute("SELECT session_id FROM inspection_sessions ORDER BY started_at DESC, session_id DESC LIMIT 1").fetchone()
                session_id = latest[0] if latest else None
                if latest is None:
                    effective_range = "current_session"
            where, params = self._event_query(session_id, effective_range, start_date, end_date)
            session_source = "SELECT * FROM inspection_sessions" + (" WHERE session_id = ?" if session_id else "")
            sessions = [self._session_from_row(row) for row in connection.execute(
                self._session_summary_sql(session_source), (session_id,) if session_id else (),
            )]
            if range_name == "latest" and session_id is None:
                sessions = []
            cursor = connection.execute(
                "SELECT session_id, track_id, timestamp, final_grade, event_json, analysis_json FROM fish_inspections"
                + where + " ORDER BY timestamp ASC, session_id ASC, track_id ASC", params,
            )
            def events():
                while rows := cursor.fetchmany(256):
                    for row in rows:
                        yield self._event_from_row(row)
            today = date.today().isoformat() if range_name == "today" else None
            scope = {"range": range_name, "session_id": session_id,
                     "start_date": start_date if range_name == "custom" else today,
                     "end_date": end_date if range_name == "custom" else today,
                     "date_basis": "fish_timestamp_local_date; zero-fish sessions use started_at"}
            return build_dashboard(events(), sessions, scope=scope, granularity=granularity)

    @staticmethod
    def _session_summary_sql(source: str) -> str:
        # Aggregate indexed fish rows only for the selected session page.
        counts = ", ".join(
            f"SUM(CASE WHEN f.final_grade='{grade}' THEN 1 ELSE 0 END) AS grade_{key}"
            for key, grade in (("a", "Class A"), ("b", "Class B"), ("c", "Class C"), ("rejected", "Rejected"))
        )
        return (f"SELECT s.*, COUNT(f.track_id) AS event_count, {counts} FROM ({source}) s "
                "LEFT JOIN fish_inspections f ON f.session_id=s.session_id GROUP BY s.session_id ORDER BY s.started_at DESC, s.session_id DESC")

    def sessions_page(self, *, page: int = 1, page_size: int = 100, search: str | None = None,
                      start_date: str | None = None, end_date: str | None = None,
                      session_id: str | None = None) -> tuple[list[dict[str, object]], int]:
        clauses, params = [], {"limit": page_size, "offset": (page - 1) * page_size}
        lower = date.fromisoformat(start_date) if start_date else None
        upper = date.fromisoformat(end_date) if end_date else None
        if lower and upper and lower > upper:
            raise ValueError("The start date must not be after the end date.")
        if lower:
            clauses.append("substr(started_at,1,10)>=:start")
            params["start"] = lower.isoformat()
        if upper:
            clauses.append("substr(started_at,1,10)<=:end")
            params["end"] = upper.isoformat()
        if search:
            clauses.append("instr(lower(session_id),:search)>0")
            params["search"] = search.casefold().strip()
        if session_id:
            clauses.append("session_id=:session_id")
            params["session_id"] = session_id
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        source = "SELECT * FROM inspection_sessions" + where + " ORDER BY started_at DESC, session_id DESC LIMIT :limit OFFSET :offset"
        with self._lock, self._connection() as connection:
            connection.execute("BEGIN")
            total = connection.execute("SELECT COUNT(*) FROM inspection_sessions" + where, params).fetchone()[0]
            rows = connection.execute(self._session_summary_sql(source), params).fetchall()
        return [self._session_from_row(row) for row in rows], total

    @staticmethod
    def _session_from_row(row: sqlite3.Row) -> dict[str, object]:
        result = {
            "session_id": row["session_id"], "started_at": row["started_at"], "ended_at": row["ended_at"],
            "git_commit": row["git_commit"], "model1_path": row["model1_path"], "model1_sha256": row["model1_sha256"],
            "model2_path": row["model2_path"], "model2_sha256": row["model2_sha256"], "tracker_backend": row["tracker_backend"],
            "grading_config": _decoded(row["grading_config_json"], {}), "grading_config_hash": row["grading_config_hash"],
            "camera_settings": _decoded(row["camera_settings_json"], {}), "runtime_settings": _decoded(row["runtime_settings_json"], {}),
        }
        start = _parse_timestamp(row["started_at"])
        end = _parse_timestamp(row["ended_at"] or _now())
        try:
            duration = max(0.0, (end - start).total_seconds()) if start and end else None
        except TypeError:
            duration = None
        grades = {"Class A": int(row["grade_a"]), "Class B": int(row["grade_b"]), "Class C": int(row["grade_c"]), "Rejected": int(row["grade_rejected"])}
        count = int(row["event_count"])
        grades["Ungraded"] = count - sum(grades.values())
        result.update(
            event_count=count, fish_count=count, grade_distribution=grades,
            duration_seconds=duration, active_seconds=row["active_seconds"],
            active_time_measured=row["active_seconds"] is not None,
            status=(row["activity_status"] if row["activity_status"] != "legacy" else ("completed" if row["ended_at"] else "interrupted")),
            heartbeat_at=row["heartbeat_at"], autosaved_at=row["autosaved_at"],
            auto_save_eligible=bool(row["active_seconds"] is not None and row["active_seconds"] >= 60),
            auto_save_threshold_seconds=60, records_durable=True,
        )
        return result

    def session(self, session_id: str) -> dict[str, object] | None:
        with self._lock, self._connection() as connection:
            row = connection.execute(self._session_summary_sql("SELECT * FROM inspection_sessions WHERE session_id = ?"), (session_id,)).fetchone()
        return self._session_from_row(row) if row is not None else None

    def apply_manual_review(self, session_id: str, track_id: int, manual_grade: str | None,
                            *, reviewer: str | None = None) -> dict[str, object] | None:
        """Persist a review for an event retained after the live process restarts."""

        with self._lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM fish_inspections WHERE session_id = ? AND track_id = ?",
                (session_id, int(track_id)),
            ).fetchone()
            if row is None:
                return None
            event = self._event_from_row(row)
            previous_grade = event.get("manual_grade") if event.get("manual_override") else None
            reviewed_at = _now()
            event["manual_override"] = manual_grade is not None
            event["manual_grade"] = manual_grade
            event["review_timestamp"] = reviewed_at if manual_grade is not None else None
            event["reviewer"] = reviewer if manual_grade is not None else None
            event["review_source"] = "operator" if manual_grade is not None else None
            connection.execute(
                "UPDATE fish_inspections SET event_json = ? WHERE session_id = ? AND track_id = ?",
                (_json(event), session_id, int(track_id)),
            )
            connection.execute(
                "INSERT INTO inspection_review_audit(session_id, track_id, previous_grade, manual_grade, reviewer, reviewed_at, source) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (session_id, int(track_id), previous_grade, manual_grade, reviewer, reviewed_at, "operator"),
            )
            return event

    def review_audit(self, session_id: str, track_id: int) -> list[dict[str, object]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT audit_id, session_id, track_id, previous_grade, manual_grade, reviewer, reviewed_at, source "
                "FROM inspection_review_audit WHERE session_id = ? AND track_id = ? ORDER BY audit_id", (session_id, int(track_id)),
            ).fetchall()
        return [dict(row) for row in rows]


class InspectionSessionContext:
    """Keep the current durable session ID coherent across API and camera threads."""

    def __init__(self, database: InspectionDatabase) -> None:
        self.database = database
        self._lock = RLock()
        self._session_id: str | None = None
        self._active = False
        self._activity_seconds = 0.0
        self._activity_clock: float | None = None
        self._activity_running = False
        self._activity_flushed_at: float | None = None
        self._activity_flushed_seconds = 0.0

    @property
    def session_id(self) -> str | None:
        with self._lock:
            return self._session_id

    @property
    def active(self) -> bool:
        with self._lock:
            return self._active

    def start(self, metadata: Mapping[str, object]) -> str:
        with self._lock:
            if self._active and self._session_id:
                return self._session_id
            self._session_id = self.database.create_session(metadata)
            self._active = True
            self._reset_activity_clock()
            return self._session_id

    def _reset_activity_clock(self) -> None:
        self._activity_seconds = 0.0
        self._activity_clock = None
        self._activity_running = False
        self._activity_flushed_at = None
        self._activity_flushed_seconds = 0.0

    def observe_activity(self, running: bool, *, now: float | None = None, force: bool = False) -> None:
        """Accumulate observed capture time, excluding pauses and host downtime.

        The application samples once a second and writes at most every five
        seconds. A gap over two seconds is not attributed to active capture.
        Endpoints never infer active time from a wall-clock session duration.
        """
        tick = monotonic() if now is None else now
        checkpoint = None
        with self._lock:
            if not self._active or not self._session_id:
                return
            if self._activity_clock is not None and self._activity_running and running:
                delta = tick - self._activity_clock
                if 0 <= delta <= 2:
                    self._activity_seconds += delta
            self._activity_clock = tick
            self._activity_running = running
            milestone = self._activity_seconds >= 60 and self._activity_flushed_seconds < 60
            if force or milestone or self._activity_flushed_at is None or tick - self._activity_flushed_at >= 5:
                checkpoint = (self._session_id, self._activity_seconds, "active" if running else "paused")
        # The monitor must not hold the identity lock during SQLite I/O: live
        # tracking captures event targets through that same short-lived lock.
        # Closing/rotation already own their frame barrier and deliberately
        # serialize the final flush. An old monitor checkpoint cannot update an
        # ended row or leak its elapsed time into a newly-created session.
        if checkpoint is not None:
            identifier, seconds, status = checkpoint
            self.database.checkpoint_session_activity(identifier, seconds, status=status)
            with self._lock:
                if self._active and self._session_id == identifier:
                    self._activity_flushed_at = max(self._activity_flushed_at or tick, tick)
                    self._activity_flushed_seconds = max(self._activity_flushed_seconds, seconds)

    def activity_snapshot(self) -> dict[str, object]:
        with self._lock:
            return {"active_seconds": round(self._activity_seconds, 3),
                    "auto_save_eligible": self._activity_seconds >= 60,
                    "auto_save_threshold_seconds": 60, "checkpoint_interval_seconds": 5,
                    "active_capture_observed": self._activity_running}

    def close(self, *, status: str = "completed") -> None:
        with self._lock:
            if self._active and self._session_id:
                self.observe_activity(False, force=True)
                self.database.end_session(self._session_id, status=status)
            self._active = False

    def rotate(self, metadata: Mapping[str, object]) -> str:
        with self._lock:
            new_session_id = self.database.create_session(metadata)
            try:
                if self._active and self._session_id:
                    self.observe_activity(False, force=True)
                    self.database.end_session(self._session_id)
            except Exception:
                self.database.end_session(new_session_id)
                raise
            self._session_id = new_session_id
            self._active = True
            self._reset_activity_clock()
            return self._session_id

    @staticmethod
    def _is_late_update(action: str) -> bool:
        return action in {"updated", "reviewed"}

    def _record_event_for_locked(self, session_id: str | None, action: str, event: Mapping[str, object]) -> str | None:
        """Immediate-write path, deliberately serialized with rotation."""

        if not session_id:
            return None
        current_active = self._active and session_id == self._session_id
        # A closed or superseded session is deliberately write-once except for
        # a late enrichment/review of an event already committed to that exact
        # session. This is also the rule used by queued persistence workers.
        if not current_active and (
            not self._is_late_update(action)
            or not self.database.event_exists(session_id, event.get("track_id"))
        ):
            return None
        self.database.upsert_event(session_id, event)
        return session_id

    def _captured_target_is_eligible(
        self,
        session_id: str | None,
        action: str,
        event: Mapping[str, object],
    ) -> bool:
        """Check a queued target without retaining the identity lock for SQLite I/O."""

        if not session_id:
            return False
        with self._lock:
            target_is_active = self._active and session_id == self._session_id
        if target_is_active:
            return True
        return self._is_late_update(action) and self.database.event_exists(session_id, event.get("track_id"))

    def capture_event_target(self, action: str, event: Mapping[str, object]) -> str | None:
        """Capture the currently eligible durable session for a later write.

        The returned ID is suitable for an ordered persistence worker. Callers
        must drain queued work before rotating or closing an active session so a
        newly-created event cannot become a stale write after its session ends.
        """

        with self._lock:
            session_id = self._session_id
            target_is_active = self._active and bool(session_id)
        if not session_id:
            return None
        if target_is_active:
            return session_id
        if self._is_late_update(action) and self.database.event_exists(session_id, event.get("track_id")):
            return session_id
        return None

    def record_event_for(self, session_id: str | None, action: str, event: Mapping[str, object]) -> str | None:
        """Persist to a captured session ID without resolving a newer session.

        This intentionally releases the session identity/rotation lock before
        database I/O.  A queued caller must therefore drain writes before a
        close or rotate operation; that barrier makes the eligibility snapshot
        and the subsequent upsert one durable-session operation.
        """

        if not self._captured_target_is_eligible(session_id, action, event):
            return None
        assert session_id is not None
        self.database.upsert_event(session_id, event)
        return session_id

    def record_event(self, action: str, event: Mapping[str, object]) -> str | None:
        """Serialize an immediate event write with close/rotate semantics."""

        with self._lock:
            return self._record_event_for_locked(self._session_id, action, event)

    def event_session(self, metadata: Mapping[str, object]) -> str:
        """Use the last session for late updates; create one only when necessary."""

        with self._lock:
            if self._session_id:
                return self._session_id
        return self.start(metadata)


def _parse_timestamp(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _event_local_date(event_json: str, stored_timestamp: str) -> str | None:
    event = _decoded(event_json, {})
    timestamp = event.get("timestamp", stored_timestamp) if isinstance(event, dict) else stored_timestamp
    parsed = _parse_timestamp(timestamp)
    return parsed.date().isoformat() if parsed else None


def _history_matches(event_json: str, analysis_json: str, final_grade: str, track_id: int, search: str | None,
                     grade: str | None, feature: str | None, min_confidence: float | None) -> int:
    event = _decoded(event_json, {})
    event = event if isinstance(event, dict) else {}
    analysis = event.get("analysis")
    if not isinstance(analysis, dict):
        analysis = _decoded(analysis_json, {})
    if search:
        needle = search.casefold().replace("fish", "").replace("#", "").strip()
        if needle not in str(event.get("track_id", track_id)).casefold():
            return 0
    if grade and grade.casefold() != "all":
        quality = str(event.get("quality") or final_grade or "Ungraded").casefold()
        if grade.casefold() == "graded":
            if quality not in {"class a", "class b", "class c", "rejected"}:
                return 0
        elif grade.casefold() == "accepted":
            if quality not in {"class a", "class b", "class c"}:
                return 0
        elif quality != grade.casefold():
            return 0
    if feature and feature.casefold() != "all":
        parts = event.get("parts") or []
        if not any(isinstance(part, dict) and str(part.get("region", "")).casefold() == feature.casefold() for part in parts):
            return 0
    if min_confidence is not None:
        support = None
        if isinstance(analysis, dict):
            for key in ("final_score", "provisional_score", "best_evidence_score"):
                try:
                    if analysis.get(key) is not None:
                        support = float(analysis[key])
                        break
                except (TypeError, ValueError):
                    continue
        if support is None:
            try:
                support = float(event.get("quality_confidence") or 0)
            except (TypeError, ValueError):
                support = 0.0
        if not support * 100 >= min_confidence:
            return 0
    return 1


def _history_verdict(event_json: str, analysis_json: str) -> str:
    event = _decoded(event_json, {})
    analysis = event.get("analysis") if isinstance(event, dict) else None
    if not isinstance(analysis, dict):
        analysis = _decoded(analysis_json, {})
    return str(analysis.get("verdict_status") or "UNAVAILABLE").upper() if isinstance(analysis, dict) else "UNAVAILABLE"


def _history_has_reason(event_json: str, analysis_json: str, reason: str) -> int:
    event = _decoded(event_json, {})
    analysis = event.get("analysis") if isinstance(event, dict) else None
    if not isinstance(analysis, dict):
        analysis = _decoded(analysis_json, {})
    if not isinstance(analysis, dict):
        return 0
    codes = analysis.get("reason_codes")
    if not isinstance(codes, (list, tuple)):
        codes = []
    if reason == "Not recorded":
        return int(not codes and not analysis.get("verdict_reason_code"))
    return int(reason in codes or reason == analysis.get("verdict_reason_code"))


def _history_region_present(event_json: str, analysis_json: str, region: str) -> int:
    event = _decoded(event_json, {})
    analysis = event.get("analysis") if isinstance(event, dict) else None
    if not isinstance(analysis, dict):
        analysis = _decoded(analysis_json, {})
    parts = analysis.get("part_results") if isinstance(analysis, dict) else None
    if not isinstance(parts, dict):
        return 0
    return int(any(name.casefold() == region.casefold() and isinstance(value, dict) and value.get("present") is True
                   for name, value in parts.items()))
