"""Measure synthetic history/analytics costs without touching production data."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
from time import perf_counter
import tracemalloc

from src.api import app as app_module
from src.api.database import InspectionDatabase, InspectionSessionContext


def _measure(call):
    tracemalloc.start()
    started = perf_counter()
    value = call()
    elapsed = perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {"milliseconds": round(elapsed * 1000, 2), "python_peak_bytes": peak, "result_size": len(value.get("items", value.get("throughput", [])))}


def run() -> dict[str, object]:
    results = []
    with tempfile.TemporaryDirectory(prefix="tamban-history-benchmark-") as tempdir:
        database = InspectionDatabase(Path(tempdir) / "synthetic.sqlite3")
        sessions = InspectionSessionContext(database)
        session_id = sessions.start({})
        app_module.inspection_database = database
        app_module.inspection_sessions = sessions
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        previous = 0
        for size in (100, 10_000, 100_000):
            def rows():
                for track_id in range(previous + 1, size + 1):
                    timestamp = (base + timedelta(seconds=track_id)).isoformat(timespec="seconds")
                    analysis = {"final_grade": "Class A", "final_score": .8, "verdict_status": "AUTO_GRADED", "part_results": {"Body": {"present": True, "grade_confidence": .8}}, "observed_regions": ["Body"]}
                    event = {"track_id": track_id, "timestamp": timestamp, "quality": "Class A", "quality_confidence": .8, "final_confidence": .9, "parts": [{"region": "Body"}], "analysis": analysis}
                    yield (session_id, track_id, timestamp, "Class A", .8, json.dumps(analysis), json.dumps(event), timestamp)
            with database._connection() as connection:
                connection.executemany("INSERT INTO fish_inspections (session_id, track_id, timestamp, final_grade, final_support, analysis_json, event_json, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows())
            previous = size
            measurement = {"records": size}
            measurement["history_first_page"] = _measure(lambda: app_module.get_history(page=1, page_size=25))
            measurement["analytics_first"] = _measure(app_module.get_analytics)
            measurement["analytics_repeat"] = _measure(app_module.get_analytics)
            measurement["live_status"] = _measure(app_module.get_live_status)
            if size == 100_000:
                database.upsert_event(session_id, {
                    "track_id": size + 1, "timestamp": "2027-01-01T00:00:00+00:00", "quality": "Class A",
                    "analysis": {"final_grade": "Class A", "verdict_status": "AUTO_GRADED"},
                })
                measurement["analytics_after_append"] = _measure(app_module.get_analytics)
                database.apply_manual_review(session_id, size + 1, "Class B")
                measurement["analytics_after_review"] = _measure(app_module.get_analytics)
            results.append(measurement)
            print(json.dumps(measurement), flush=True)
    return {"method": "Synthetic SQLite rows; single call per measurement; tracemalloc Python allocation peak, not process RSS; no camera or FPS measurement.", "results": results}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = run()
    Path(args.output).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
