"""Benchmark legacy and live status responses on isolated synthetic SQLite data."""
from __future__ import annotations

import argparse
import csv
import importlib
import json
import sqlite3
import statistics
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.api.database import InspectionDatabase, InspectionSessionContext
from src.api.domain import InspectionState


def percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * quantile
    low = int(index)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (index - low)


def benchmark(*, repetitions: int = 12) -> list[dict[str, object]]:
    if repetitions < 2:
        raise ValueError("At least two samples are needed.")
    module = importlib.import_module("src.api.app")
    rows = []
    with tempfile.TemporaryDirectory(prefix="tamban_status_fixture_") as directory:
        database = InspectionDatabase(Path(directory) / "fixture.sqlite3")
        sessions = InspectionSessionContext(database)
        session_id = sessions.start({})
        with patch.object(module, "inspection_database", database), patch.object(module, "inspection_sessions", sessions), patch.object(module, "state", InspectionState()):
            client = TestClient(module.app)
            previous = 0
            for size in (0, 100, 1000, 10000):
                records = []
                for number in range(previous + 1, size + 1):
                    event = {"track_id": number, "timestamp": "2026-01-01T00:00:00+00:00", "quality": "Ungraded", "final_confidence": .9,
                             "quality_confidence": None, "parts": [], "analysis": {"final_grade": "Ungraded", "part_results": {}}}
                    records.append((session_id, number, event["timestamp"], "Ungraded", json.dumps(event), event["timestamp"]))
                if records:
                    with database._connection() as connection:
                        connection.executemany("INSERT INTO fish_inspections(session_id, track_id, timestamp, final_grade, event_json, updated_at) VALUES (?, ?, ?, ?, ?, ?)", records)
                previous = size
                for endpoint in ("/api/status", "/api/status/live"):
                    response = client.get(endpoint)
                    response.raise_for_status()
                    durations = []
                    selects: list[int] = []
                    real_connect = sqlite3.connect
                    def traced_connect(*args, **kwargs):
                        connection = real_connect(*args, **kwargs)
                        connection.set_trace_callback(lambda sql: selects.append(1) if sql.lstrip().upper().startswith("SELECT ") else None)
                        return connection
                    with patch("src.api.database.sqlite3.connect", side_effect=traced_connect):
                        for _ in range(repetitions):
                            started = time.perf_counter()
                            response = client.get(endpoint)
                            response.raise_for_status()
                            durations.append((time.perf_counter() - started) * 1000)
                    rows.append({"fish": size, "endpoint": endpoint, "samples": repetitions,
                                 "p50_ms": round(statistics.median(durations), 3), "p95_ms": round(percentile(durations, .95), 3),
                                 "response_bytes": len(response.content), "selects_per_request": len(selects) / repetitions})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repetitions", type=int, default=12)
    parser.add_argument("--output", type=Path, default=Path("results/performance/status_polling_fixtures.csv"))
    args = parser.parse_args()
    rows = benchmark(repetitions=args.repetitions)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
