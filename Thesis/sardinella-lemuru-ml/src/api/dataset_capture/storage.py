"""Capture-only originals, transactional provenance and durable upload intent.

This store never opens inspection data. Interrupted originals are retained and
reconciled; derived previews and exports do not replace the saved camera image.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import threading
import time
import uuid
import zipfile

import cv2
import numpy as np

from .errors import CaptureError
from .quality import assess_quality


_ID = re.compile(r"^[a-f0-9]{32}$")
_GRADES = {"A", "B", "C", "Rejected", "Unknown", "Background", "Hard negative"}
_REVIEW = {"unreviewed", "review", "reviewed", "keep", "exclude"}
_TRAINING = {"review", "include", "exclude", "keep"}
_METADATA = {"name", "session_name", "operator", "operator_code", "source_code", "vendor_code",
             "batch_id", "source_id", "specimen_id", "specimen_confirmed", "camera_profile",
             "camera_setup", "lighting", "background", "conveyor_on", "conveyor", "angle",
             "orientation", "notes", "provisional_grade", "tentative_grade", "review_state",
             "training_state", "privacy_consent", "consent", "review_thresholds"}


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _metadata(values: dict, *, defaults: bool = False) -> dict:
    if not isinstance(values, dict) or set(values) - _METADATA:
        raise CaptureError(422, "INVALID_METADATA", "Unknown collection metadata fields.")
    result = {"provisional_grade": "Unknown", "review_state": "unreviewed",
              "training_state": "review", "specimen_confirmed": False} if defaults else {}
    for key, value in values.items():
        if key == "tentative_grade":
            key = "provisional_grade"
        if key == "review_thresholds":
            if not isinstance(value, dict) or set(value) - {
                    "focus_min", "clipped_ratio", "duplicate_distance", "background_drift"}:
                raise CaptureError(422, "INVALID_METADATA", "Invalid quality review thresholds.")
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                   or v < 0 or v > 10000 for v in value.values()):
                raise CaptureError(422, "INVALID_METADATA", "Invalid quality review thresholds.")
        elif key in {"specimen_confirmed", "conveyor_on", "privacy_consent", "consent"}:
            if not isinstance(value, bool):
                raise CaptureError(422, "INVALID_METADATA", f"{key} must be boolean.")
        elif not isinstance(value, str) or len(value) > (4000 if key == "notes" else 256) or "\x00" in value:
            raise CaptureError(422, "INVALID_METADATA", f"Invalid {key} value.")
        if key == "provisional_grade" and value not in _GRADES:
            raise CaptureError(422, "INVALID_METADATA", "Grade is a provisional operator tag only.")
        if key == "review_state" and value not in _REVIEW:
            raise CaptureError(422, "INVALID_METADATA", "Invalid non-destructive review state.")
        if key == "training_state" and value not in _TRAINING:
            raise CaptureError(422, "INVALID_METADATA", "Invalid training inclusion state.")
        result[key] = value
    return result


def _confirmed_metadata(values: dict) -> dict:
    if values.get("specimen_confirmed") and not values.get("specimen_id", "").strip():
        raise CaptureError(422, "INVALID_METADATA", "A confirmed specimen requires an explicit specimen ID.")
    return values


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class CaptureStore:
    def __init__(self, root, quota_bytes: int = 10 * 1024**3,
                 min_free_bytes: int = 100 * 1024**2, max_items: int = 10000):
        self.root = Path(root).resolve()
        if quota_bytes <= 0 or min_free_bytes < 0 or max_items <= 0:
            raise ValueError("Storage limits must be positive.")
        self.quota_bytes, self.min_free_bytes, self.max_items = quota_bytes, min_free_bytes, max_items
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.root / "capture.sqlite3", check_same_thread=False,
                                           timeout=10, isolation_level=None)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=FULL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.executescript("""
            CREATE TABLE IF NOT EXISTS capture_sessions(
                id TEXT PRIMARY KEY, created_utc TEXT NOT NULL, metadata TEXT NOT NULL,
                sequence INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS capture_items(
                id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES capture_sessions(id),
                sequence INTEGER NOT NULL, generation TEXT NOT NULL, frame_id INTEGER NOT NULL,
                filename TEXT NOT NULL UNIQUE, sha256 TEXT NOT NULL, width INTEGER NOT NULL,
                height INTEGER NOT NULL, byte_count INTEGER NOT NULL, capture_mode TEXT NOT NULL,
                captured_utc TEXT NOT NULL, captured_monotonic REAL NOT NULL,
                scheduled_monotonic REAL, metadata TEXT NOT NULL, frame_metadata TEXT NOT NULL,
                quality TEXT NOT NULL, local_status TEXT NOT NULL,
                UNIQUE(session_id,generation,frame_id), UNIQUE(session_id,sequence));
            CREATE TABLE IF NOT EXISTS capture_sync_queue(
                image_id TEXT PRIMARY KEY REFERENCES capture_items(id), state TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0, next_attempt REAL NOT NULL DEFAULT 0,
                lease_id TEXT, lease_until REAL, remote_id TEXT, last_error TEXT,
                idempotency_key TEXT NOT NULL UNIQUE);
            CREATE TABLE IF NOT EXISTS capture_events(
                sequence INTEGER PRIMARY KEY AUTOINCREMENT, utc TEXT NOT NULL,
                session_id TEXT, image_id TEXT, event TEXT NOT NULL, detail TEXT NOT NULL);
        """)
        self.reconcile()

    def _id(self, value: str) -> str:
        if not isinstance(value, str) or not _ID.fullmatch(value):
            raise CaptureError(422, "INVALID_ID", "Invalid capture identifier.")
        return value

    def _path(self, relative: str) -> Path:
        path = self.root / relative
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root) or path.is_symlink():
            raise CaptureError(403, "UNSAFE_PATH", "Capture path escapes its storage root.")
        return path

    def _event(self, event, detail=None, session_id=None, image_id=None):
        self._connection.execute("INSERT INTO capture_events(utc,session_id,image_id,event,detail) VALUES(?,?,?,?,?)",
                                 (_utc(), session_id, image_id, event, _json(detail or {})))

    def _capacity(self, extra: int = 0):
        used = self._used_bytes()
        # Reserve the unwritten portion of other processes' durable save intents.
        reserved = 0
        for row in self._connection.execute("SELECT filename,byte_count FROM capture_items WHERE local_status='pending'"):
            published, temporary = self._path(row["filename"]), self._path(row["filename"] + ".pending")
            present = 0
            for path in (published, temporary):
                try:
                    present += path.stat().st_size
                except FileNotFoundError:
                    pass
            reserved += max(0, row["byte_count"] - present)
        free = shutil.disk_usage(self.root).free
        if used + reserved + extra > self.quota_bytes or free - reserved - extra < self.min_free_bytes:
            raise CaptureError(507, "STORAGE_LIMIT", "Capture storage is full or below its free-space reserve.")
        return used, free

    def _used_bytes(self):
        used = 0
        for path in self.root.rglob("*"):
            try:
                if path.is_file() and not path.is_symlink():
                    used += path.stat().st_size
            except FileNotFoundError:
                # Another store may have just published and unlinked its temporary file.
                pass
        return used

    def create_session(self, metadata: dict | None = None) -> dict:
        values = _confirmed_metadata(_metadata(metadata or {}, defaults=True))
        session_id = uuid.uuid4().hex
        with self._lock:
            self._capacity()
            self._connection.execute("INSERT INTO capture_sessions(id,created_utc,metadata) VALUES(?,?,?)",
                                     (session_id, _utc(), _json(values)))
            self._event("session_created", values, session_id)
            return self.session(session_id)

    def session(self, session_id: str) -> dict:
        with self._lock:
            row = self._connection.execute("SELECT * FROM capture_sessions WHERE id=?", (self._id(session_id),)).fetchone()
            if row is None:
                raise CaptureError(404, "SESSION_NOT_FOUND", "Capture session does not exist.")
            return {"id": row["id"], "session_id": row["id"], "created_utc": row["created_utc"],
                    "metadata": json.loads(row["metadata"]), "sequence": row["sequence"]}

    def list_sessions(self, limit: int = 100) -> list[dict]:
        with self._lock:
            rows = self._connection.execute("SELECT id FROM capture_sessions ORDER BY created_utc DESC LIMIT ?",
                                            (max(1, min(int(limit), 1000)),)).fetchall()
            return [self.session(row["id"]) for row in rows]

    def update_session(self, session_id: str, metadata: dict) -> dict:
        patch = _metadata(metadata)
        with self._lock:
            current = self.session(session_id)["metadata"]
            current.update(patch)
            _confirmed_metadata(current)
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                self._connection.execute("UPDATE capture_sessions SET metadata=? WHERE id=?", (_json(current), session_id))
                self._event("session_metadata_updated", patch, session_id)
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
            return self.session(session_id)

    def save_frame(self, session_id: str, frame: np.ndarray, frame_metadata: dict,
                   capture_mode: str, scheduled_monotonic: float | None = None) -> dict:
        if capture_mode not in {"manual", "automatic"}:
            raise CaptureError(422, "INVALID_CAPTURE_MODE", "Capture mode must be manual or automatic.")
        if not isinstance(frame, np.ndarray) or frame.dtype != np.uint8 or frame.ndim != 3 or frame.shape[2] != 3 \
                or min(frame.shape[:2]) < 1 or frame.shape[0] * frame.shape[1] > 50_000_000:
            raise CaptureError(422, "INVALID_FRAME", "Expected a native uint8 BGR camera frame.")
        try:
            generation = str(frame_metadata["generation"])
            frame_id = int(frame_metadata["frame_id"])
            monotonic = float(frame_metadata.get("captured_monotonic", frame_metadata.get("monotonic_capture_time")))
            captured_utc = str(frame_metadata["captured_utc"])
            parsed = datetime.fromisoformat(captured_utc.replace("Z", "+00:00"))
            if parsed.tzinfo is None or not math.isfinite(monotonic) or frame_id < 0 or len(generation) > 100:
                raise ValueError()
            if scheduled_monotonic is not None and not math.isfinite(float(scheduled_monotonic)):
                raise ValueError()
            if len(_json(frame_metadata)) > 65536:
                raise ValueError()
        except (ValueError, KeyError, TypeError, OverflowError):
            raise CaptureError(422, "INVALID_FRAME_METADATA", "Frame identity and UTC/monotonic timing are required.") from None
        encoded_ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
        if not encoded_ok:
            raise CaptureError(500, "ENCODING_FAILED", "The camera frame could not be encoded.")
        content = encoded.tobytes()
        digest = hashlib.sha256(content).hexdigest()
        with self._lock:
            session = self.session(session_id)
            if self._connection.execute("SELECT 1 FROM capture_items WHERE session_id=? AND generation=? AND frame_id=?",
                                        (session_id, generation, frame_id)).fetchone():
                raise CaptureError(409, "DUPLICATE_FRAME", "This camera frame has already been saved or reserved.")
            if self._connection.execute("SELECT COUNT(*) FROM capture_items").fetchone()[0] >= self.max_items:
                raise CaptureError(507, "ITEM_LIMIT", "The configured capture image limit has been reached.")
            self._capacity(len(content) + 65536)
            previous = self._connection.execute("SELECT quality FROM capture_items WHERE session_id=? AND local_status='saved' ORDER BY sequence DESC LIMIT 1", (session_id,)).fetchone()
            quality = assess_quality(frame, json.loads(previous[0]) if previous else None,
                                     session["metadata"].get("review_thresholds"))
            if self._connection.execute("SELECT 1 FROM capture_items WHERE session_id=? AND sha256=? AND local_status='saved'", (session_id, digest)).fetchone():
                quality["warnings"].append("IDENTICAL_PIXELS_REVIEW")
            image_id = uuid.uuid4().hex
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                # Two app processes may share the store: allocate under SQLite's write lock.
                sequence = self._connection.execute("SELECT sequence FROM capture_sessions WHERE id=?", (session_id,)).fetchone()[0] + 1
                if self._connection.execute("SELECT COUNT(*) FROM capture_items").fetchone()[0] >= self.max_items:
                    raise CaptureError(507, "ITEM_LIMIT", "The configured capture image limit has been reached.")
                self._capacity(len(content) + 65536)
                stamp = parsed.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                filename = f"{session_id}/raw/{stamp}_{session_id}_{sequence:06d}_{image_id}.jpg"
                path = self._path(filename)
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self._path(filename + ".pending")
                self._connection.execute("UPDATE capture_sessions SET sequence=? WHERE id=?", (sequence, session_id))
                self._connection.execute("""INSERT INTO capture_items VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (image_id, session_id, sequence, generation, frame_id, filename, digest,
                     frame.shape[1], frame.shape[0], len(content), capture_mode, captured_utc, monotonic,
                     scheduled_monotonic, _json(session["metadata"]), _json(frame_metadata), _json(quality), "pending"))
                self._event("save_intent", {"sha256": digest}, session_id, image_id)
                self._connection.execute("COMMIT")
            except sqlite3.IntegrityError:
                self._connection.execute("ROLLBACK")
                raise CaptureError(409, "DUPLICATE_FRAME", "The frame was already reserved by another writer.") from None
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
            try:
                with temporary.open("xb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                # Hard-link publication is atomic and refuses an existing destination.
                os.link(temporary, path)
                temporary.unlink()
                self._finish_save(image_id)
            except (OSError, sqlite3.Error) as error:
                try:
                    self._event("save_interrupted", {"error_type": type(error).__name__}, session_id, image_id)
                except sqlite3.Error:
                    pass
                raise CaptureError(507, "SAVE_FAILED", "The original was not confirmed saved; recovery evidence was retained.") from error
            return self.item(session_id, image_id)

    def _finish_save(self, image_id):
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            self._connection.execute("UPDATE capture_items SET local_status='saved' WHERE id=?", (image_id,))
            self._connection.execute("INSERT OR IGNORE INTO capture_sync_queue(image_id,state,idempotency_key) VALUES(?,'queued',?)",
                                     (image_id, f"tamban-capture-{image_id}"))
            self._event("saved_locally", image_id=image_id)
            self._connection.execute("COMMIT")
        except Exception:
            self._connection.execute("ROLLBACK")
            raise

    def reconcile(self) -> dict:
        recovered, interrupted, missing, orphans = [], [], [], []
        with self._lock:
            rows = self._connection.execute("SELECT id,filename,sha256,local_status FROM capture_items").fetchall()
            known = {row["filename"] for row in rows}
            for row in rows:
                path = self._path(row["filename"])
                if path.is_file() and _checksum(path) == row["sha256"]:
                    if row["local_status"] != "saved":
                        self._finish_save(row["id"])
                        recovered.append(row["id"])
                elif row["local_status"] == "pending":
                    # A newly mounted app must not flag another live writer's intent as a crash.
                    event = self._connection.execute("SELECT utc,event FROM capture_events WHERE image_id=? AND event IN ('save_intent','save_interrupted') ORDER BY sequence DESC LIMIT 1", (row["id"],)).fetchone()
                    age = (datetime.now(timezone.utc) - datetime.fromisoformat(event["utc"])).total_seconds() if event else 0
                    if event and (event["event"] == "save_interrupted" or age > 120):
                        interrupted.append(row["id"])
                else:
                    self._connection.execute("UPDATE capture_items SET local_status='missing_or_changed' WHERE id=?", (row["id"],))
                    self._connection.execute("UPDATE capture_sync_queue SET state='failed',last_error='LOCAL_FILE_MISSING_OR_CHANGED' WHERE image_id=?", (row["id"],))
                    missing.append(row["id"])
            for path in self.root.glob("*/raw/*.jpg"):
                relative = path.relative_to(self.root).as_posix()
                if relative not in known:
                    orphans.append(relative)
            result = {"recovered": recovered, "interrupted": interrupted,
                      "missing_or_changed": missing, "orphan_files": orphans}
            if any(result.values()):
                self._event("reconciliation", result)
            self.recovery = result
            return result

    def _item(self, row) -> dict:
        metadata, frame_metadata, quality = (json.loads(row[name]) for name in ("metadata", "frame_metadata", "quality"))
        return {"id": row["id"], "image_id": row["id"], "session_id": row["session_id"],
                "sequence": row["sequence"], "filename": Path(row["filename"]).name,
                "local_filename": row["filename"], "sha256": row["sha256"],
                "width": row["width"], "height": row["height"], "encoding": "JPEG", "jpeg_quality": 95,
                "byte_count": row["byte_count"], "capture_mode": row["capture_mode"],
                "captured_utc": row["captured_utc"], "captured_monotonic": row["captured_monotonic"],
                "scheduled_monotonic": row["scheduled_monotonic"], "frame_id": row["frame_id"],
                "generation": row["generation"], "local_status": row["local_status"],
                "sync_status": row["sync_status"] or "queued", "drive_file_id": row["remote_id"],
                "metadata": metadata, "frame_metadata": frame_metadata, "quality": quality,
                "provisional_label_warning": "Operator tags are provisional, not expert ground truth."}

    _SELECT = """SELECT i.*,q.state AS sync_status,q.remote_id FROM capture_items i
                 LEFT JOIN capture_sync_queue q ON q.image_id=i.id"""

    def item(self, session_id: str, item_id: str) -> dict:
        with self._lock:
            row = self._connection.execute(self._SELECT + " WHERE i.session_id=? AND i.id=?",
                                           (self._id(session_id), self._id(item_id))).fetchone()
            if row is None:
                raise CaptureError(404, "IMAGE_NOT_FOUND", "Capture image does not exist.")
            return self._item(row)

    def items(self, session_id: str, limit: int = 100, offset: int = 0) -> dict:
        with self._lock:
            self.session(session_id)
            rows = self._connection.execute(self._SELECT + " WHERE i.session_id=? ORDER BY i.sequence DESC LIMIT ? OFFSET ?",
                                           (session_id, max(1, min(int(limit), 1000)), max(0, int(offset)))).fetchall()
            total = self._connection.execute("SELECT COUNT(*) FROM capture_items WHERE session_id=?", (session_id,)).fetchone()[0]
            return {"items": [self._item(row) for row in rows], "total": total}

    def update_items(self, session_id: str, ids: list[str], metadata: dict) -> dict:
        if not ids or len(ids) > 1000:
            raise CaptureError(422, "INVALID_SELECTION", "Select between 1 and 1000 images.")
        patch = _metadata(metadata)
        with self._lock:
            selected = [self.item(session_id, image_id) for image_id in dict.fromkeys(ids)]
            for item in selected:
                _confirmed_metadata({**item["metadata"], **patch})
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                for item in selected:
                    item["metadata"].update(patch)
                    self._connection.execute("UPDATE capture_items SET metadata=? WHERE id=?", (_json(item["metadata"]), item["id"]))
                    self._event("image_metadata_updated", patch, session_id, item["id"])
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
            return {"updated": len(selected), "items": [self.item(session_id, i["id"]) for i in selected]}

    def media_path(self, session_id: str, item_id: str, thumbnail: bool = False) -> Path:
        with self._lock:
            item = self.item(session_id, item_id)
            path = self._path(item["local_filename"])
            if item["local_status"] != "saved" or not path.is_file():
                raise CaptureError(404, "ORIGINAL_UNAVAILABLE", "This original is not confirmed saved locally.")
            if not thumbnail:
                return path
            derived = self._path(f"{session_id}/thumbnails/{item_id}.jpg")
            if not derived.exists():
                self._capacity(128 * 1024)
                frame = cv2.imread(str(path))
                if frame is None:
                    raise CaptureError(409, "ORIGINAL_UNREADABLE", "The original could not be decoded.")
                h, w = frame.shape[:2]
                thumb = cv2.resize(frame, (max(1, round(w * min(1, 320 / max(w, h)))),
                                            max(1, round(h * min(1, 320 / max(w, h))))))
                ok, content = cv2.imencode(".jpg", thumb, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if not ok:
                    raise CaptureError(500, "THUMBNAIL_FAILED", "The thumbnail could not be encoded.")
                derived.parent.mkdir(parents=True, exist_ok=True)
                with derived.open("xb") as stream:
                    stream.write(content.tobytes())
            return derived

    def queue_status(self, session_id: str | None = None) -> dict:
        with self._lock:
            sql = "SELECT q.state,COUNT(*) FROM capture_sync_queue q JOIN capture_items i ON i.id=q.image_id"
            rows = self._connection.execute(sql + (" WHERE i.session_id=?" if session_id else "") + " GROUP BY q.state",
                                            (self._id(session_id),) if session_id else ()).fetchall()
            counts = {state: 0 for state in ("queued", "uploading", "synced", "failed")}
            counts.update(dict(rows))
            return counts

    def stats(self, session_id: str | None = None) -> dict:
        with self._lock:
            if session_id:
                self.session(session_id)
            rows = self._connection.execute("SELECT metadata,local_status FROM capture_items" +
                                            (" WHERE session_id=?" if session_id else ""), (session_id,) if session_id else ()).fetchall()
            specimens, per_grade = set(), {g: set() for g in sorted(_GRADES)}
            reviewed = saved = manual = 0
            for row in rows:
                if row["local_status"] != "saved":
                    continue
                saved += 1
                meta = json.loads(row["metadata"])
                reviewed += meta.get("review_state", "unreviewed") in {"reviewed", "keep", "exclude"}
                if meta.get("specimen_confirmed") and meta.get("specimen_id", "").strip():
                    identity = (meta.get("source_code") or meta.get("vendor_code") or "", meta["specimen_id"].strip())
                    specimens.add(identity)
                    per_grade[meta.get("provisional_grade", "Unknown")].add(identity)
            count_sql = "SELECT capture_mode,COUNT(*) FROM capture_items WHERE local_status='saved'" + (" AND session_id=?" if session_id else "") + " GROUP BY capture_mode"
            modes = dict(self._connection.execute(count_sql, (session_id,) if session_id else ()).fetchall())
            queue = self.queue_status(session_id)
            used = self._used_bytes()
            latest = self._connection.execute("SELECT captured_utc FROM capture_items WHERE local_status='saved'" +
                                               (" AND session_id=?" if session_id else "") + " ORDER BY rowid DESC LIMIT 1",
                                               (session_id,) if session_id else ()).fetchone()
            grade_counts = {k: len(v) for k, v in per_grade.items()}
            return {"raw_frames": saved, "reviewed_photos": reviewed, "unique_specimens_confirmed": len(specimens),
                    "specimens_per_provisional_grade": grade_counts, "specimens_per_grade_provisional": grade_counts,
                    "manual_photos": modes.get("manual", 0), "automatic_photos": modes.get("automatic", 0),
                    "last_capture_utc": latest[0] if latest else None,
                    "upload_backlog": queue["queued"] + queue["uploading"] + queue["failed"], "sync": queue,
                    "used_bytes": used, "quota_bytes": self.quota_bytes, "disk_free_bytes": shutil.disk_usage(self.root).free,
                    "recovery": self.recovery, "lineage_warning": "Frames are not independent fish; grades are provisional operator tags."}

    def export(self, session_id: str, format: str) -> Path:
        if format not in {"json", "csv", "zip"}:
            raise CaptureError(422, "INVALID_EXPORT", "Choose JSON, CSV or ZIP.")
        with self._lock:
            session = self.session(session_id)
            rows = self._connection.execute(self._SELECT + " WHERE i.session_id=? ORDER BY i.sequence", (session_id,)).fetchall()
            items = [self._item(row) for row in rows]
            size = sum(i["byte_count"] for i in items if i["local_status"] == "saved")
            if size > min(self.quota_bytes, 2 * 1024**3):
                raise CaptureError(413, "EXPORT_LIMIT", "This session exceeds the bounded export size.")
            manifest = _json({"schema_version": 1, "session": session, "items": items,
                              "warning": "Unlabeled raw source photos; operator labels are provisional, not expert ground truth."})
            columns = ["id", "sequence", "filename", "capture_mode", "captured_utc", "captured_monotonic",
                       "width", "height", "sha256", "sync_status", "drive_file_id", "metadata", "quality"]
            csv_buffer = io.StringIO(newline="")
            writer = csv.DictWriter(csv_buffer, fieldnames=columns)
            writer.writeheader()
            for item in items:
                cells = {k: _json(item[k]) if isinstance(item[k], (dict, list)) else item[k] for k in columns}
                for key, value in cells.items():
                    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
                        cells[key] = "'" + value
                writer.writerow(cells)
            csv_text = csv_buffer.getvalue()
            self._capacity((size if format == "zip" else 0) + len(manifest.encode()) + len(csv_text.encode()) + 65536)
            path = self._path(f"exports/{session_id}_{uuid.uuid4().hex}.{format}")
            path.parent.mkdir(exist_ok=True)
            if format == "zip":
                with zipfile.ZipFile(path, "x", compression=zipfile.ZIP_STORED) as archive:
                    archive.writestr("manifest.json", manifest)
                    archive.writestr("manifest.csv", csv_text)
                    for item in items:
                        if item["local_status"] == "saved":
                            original = self.media_path(session_id, item["id"])
                            if _checksum(original) != item["sha256"]:
                                raise CaptureError(409, "CHECKSUM_MISMATCH", "Export stopped because an original changed.")
                            archive.write(original, "raw/" + item["filename"])
            else:
                with path.open("x", encoding="utf-8", newline="") as stream:
                    stream.write(manifest if format == "json" else csv_text)
            return path

    def claim_upload(self, now: float, lease_seconds: float = 120) -> dict | None:
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._connection.execute("""SELECT q.*,i.session_id FROM capture_sync_queue q
                    JOIN capture_items i ON q.image_id=i.id WHERE i.local_status='saved' AND
                    ((q.state='queued' AND q.next_attempt<=?) OR (q.state='uploading' AND q.lease_until<=?))
                    ORDER BY i.captured_utc LIMIT 1""", (now, now)).fetchone()
                if row is None:
                    self._connection.execute("COMMIT")
                    return None
                lease = uuid.uuid4().hex
                self._connection.execute("UPDATE capture_sync_queue SET state='uploading',lease_id=?,lease_until=?,attempts=attempts+1 WHERE image_id=?",
                                         (lease, now + lease_seconds, row["image_id"]))
                self._connection.execute("COMMIT")
                return {**dict(row), "lease_id": lease, "attempts": row["attempts"] + 1,
                        "item": self.item(row["session_id"], row["image_id"])}
            except Exception:
                self._connection.execute("ROLLBACK")
                raise

    def complete_upload(self, image_id, lease_id, remote_id):
        with self._lock:
            changed = self._connection.execute("UPDATE capture_sync_queue SET state='synced',remote_id=?,last_error=NULL,lease_id=NULL,lease_until=NULL WHERE image_id=? AND lease_id=? AND state='uploading'",
                                              (remote_id, image_id, lease_id)).rowcount
            if changed:
                self._event("synced_to_drive", {"remote_id": remote_id}, image_id=image_id)
            return bool(changed)

    def renew_upload(self, image_id, lease_id, now, lease_seconds):
        with self._lock:
            return bool(self._connection.execute("UPDATE capture_sync_queue SET lease_until=? WHERE image_id=? AND lease_id=? AND state='uploading'",
                (now + lease_seconds, image_id, lease_id)).rowcount)

    def fail_upload(self, image_id, lease_id, error_code, next_attempt=None):
        with self._lock:
            return bool(self._connection.execute("UPDATE capture_sync_queue SET state=?,last_error=?,next_attempt=?,lease_id=NULL,lease_until=NULL WHERE image_id=? AND lease_id=? AND state='uploading'",
                ("queued" if next_attempt is not None else "failed", error_code[:100], next_attempt or 0, image_id, lease_id)).rowcount)

    def retry_failed(self):
        with self._lock:
            return self._connection.execute("UPDATE capture_sync_queue SET state='queued',attempts=0,next_attempt=0,last_error=NULL WHERE state='failed'").rowcount

    def close(self):
        with self._lock:
            self._connection.close()
