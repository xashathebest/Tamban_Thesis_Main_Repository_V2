"""Persisted analytics count unique fish and never write or invent telemetry."""
from __future__ import annotations

import importlib
import json
from pathlib import Path
import sqlite3

import pytest

from src.api.database import InspectionDatabase, InspectionSessionContext


def populate_database(database: InspectionDatabase):
    """Seven unique fish in two sessions, reusable by real-browser validation."""
    plans = [
        ("saved-one", "2026-11-03", 120, ["Class A", "Class B", "Class C", "Ungraded"]),
        ("saved-two", "2026-11-04", 60, ["Class A", "Rejected", "Ungraded"]),
    ]
    events = []
    for session_id, day, seconds, grades in plans:
        database.create_session({"started_at": f"{day}T09:00:00-05:00"}, session_id=session_id)
        database.checkpoint_session_activity(session_id, seconds)
        database.end_session(session_id, ended_at=f"{day}T11:00:00-05:00")
        for index, grade in enumerate(grades, 1):
            regions = ["Body"] + (["Head"] if grade != "Ungraded" else []) + (["Tail"] if grade == "Class A" else [])
            event = {"track_id": index, "timestamp": f"{day}T{9 + (index - 1) // 2:02d}:{10 + (index - 1) % 2 * 20:02d}:00-05:00",
                     "quality": grade, "final_confidence": .9, "processing_time_ms": index * 10,
                     "fps": 999, "analysis": {"final_grade": grade,
                         "final_score": .8 if grade != "Ungraded" else None,
                         "reason_codes": ["UG_MISSING_HEAD", "UG_MISSING_HEAD"] if grade == "Ungraded" else [],
                         "part_results": {region: {"present": region in regions} for region in ("Head", "Body", "Tail")},
                         "model2_debug": {"raw_detections": [{"region": region} for region in ["Head", "Head", "Body", "Tail"]],
                                          "selected_detections": [{"region": region} for region in regions]},
                         "performance": {"model1_inference_ms": 10, "model2_inference_ms": 20}}}
            if index == 1:
                event["analysis"]["performance"].update(
                    processing_fps=2 if session_id == "saved-one" else 4,
                    capture_fps=30 if session_id == "saved-one" else 24,
                    image_processing_time_ms=200 if session_id == "saved-one" else 400,
                )
            if grade == "Ungraded":
                event.update(manual_override=True, manual_grade="Class A")
            database.upsert_event(session_id, event)
            events.append({**event, "session_id": session_id})
        # Repeated observations/update replace one persisted fish, not its count.
        database.upsert_event(session_id, {key: value for key, value in events[-1].items() if key != "session_id"})
    return events


@pytest.fixture
def saved(tmp_path):
    database = InspectionDatabase(tmp_path / "analytics.sqlite3")
    populate_database(database)
    return database


def test_saved_counts_and_sessions_agree_with_sql_and_original_ai_results(saved):
    data = saved.dashboard_analytics()
    with sqlite3.connect(saved.path) as connection:
        count = connection.execute("SELECT COUNT(*) FROM fish_inspections").fetchone()[0]
    assert data["kpis"]["total_inspected"] == count == 7
    assert data["kpis"]["session_count"] == 2
    assert data["kpis"]["grade_distribution"] == {"Class A": 2, "Class B": 1, "Class C": 1, "Rejected": 1, "Ungraded": 2}
    assert data["coverage"] == {"classified": 4, "rejected": 1, "ungraded": 2,
                                "basis": "Mutually exclusive original final grade buckets; legacy graded_count includes Rejected."}
    assert data["kpis"]["graded_count"] == 5
    assert data["kpis"]["active_seconds"] == 180
    assert data["kpis"]["duration_seconds"] == 14400
    assert data["performance"]["fish_per_minute"] == pytest.approx(7 / 3, abs=.001)
    assert {row["session_id"]: row["fish_count"] for row in data["session_comparison"]} == {"saved-one": 4, "saved-two": 3}
    assert data["ungraded_reasons"] == {"UG_MISSING_HEAD": 2}


@pytest.mark.parametrize("granularity,buckets", [("hour", 4), ("day", 2), ("week", 1), ("month", 1)])
def test_activity_granularities_keep_all_unique_fish(saved, granularity, buckets):
    data = saved.dashboard_analytics(granularity=granularity)
    assert len(data["activity"]["items"]) == buckets
    assert sum(row["fish_count"] for row in data["activity"]["items"]) == 7
    assert all(sum(row["grade_distribution"].values()) == row["fish_count"] for row in data["activity"]["items"])


def test_all_latest_individual_dates_and_zero_fish_sessions(saved):
    latest = saved.dashboard_analytics(range_name="latest")
    assert latest["scope"]["session_id"] == "saved-two"
    assert latest["kpis"]["total_inspected"] == 3
    individual = saved.dashboard_analytics(session_id="saved-one")
    assert individual["kpis"]["total_inspected"] == 4
    dates = saved.dashboard_analytics(range_name="custom", start_date="2026-11-04", end_date="2026-11-04")
    assert dates["kpis"]["total_inspected"] == 3
    assert dates["kpis"]["session_count"] == 1
    assert dates["performance"]["fish_per_minute"] == 3
    saved.create_session({"started_at": "2026-11-05T09:00:00-05:00"}, session_id="empty-latest")
    zero = saved.dashboard_analytics(range_name="latest")
    assert zero["kpis"]["total_inspected"] == 0
    assert zero["kpis"]["session_count"] == 1
    assert zero["session_comparison"][0]["duration_seconds"] is None
    assert zero["performance"]["fish_per_minute"] is None


def test_raw_and_assigned_parts_are_separate_with_explicit_sample_coverage(saved):
    anatomy = saved.dashboard_analytics()["anatomical_association"]
    assert anatomy["Head"]["raw_count"] == 7
    assert anatomy["Head"]["raw_candidate_count"] == 14
    assert anatomy["Head"]["assigned_count"] == 5
    assert anatomy["Tail"]["assigned_count"] == 2
    assert anatomy["Body"]["present_fish_count"] == 7
    assert anatomy["Head"]["raw_fish_samples"] == anatomy["Head"]["assigned_fish_samples"] == 7


def test_performance_uses_only_recorded_unambiguous_measurements(saved):
    performance = saved.dashboard_analytics()["performance"]
    assert [row["value"] for row in performance["ai_fps"]] == [2, 4]
    assert [row["value"] for row in performance["camera_fps"]] == [30, 24]
    assert performance["average_image_processing_time_ms"] == 300
    assert performance["image_processing_samples"] == 2
    assert performance["average_fish_processing_time_ms"] == pytest.approx(160 / 7, abs=.001)
    assert performance["stage_ms"]["model1_inference_ms"] == 10
    assert sum(row["count"] for row in performance["distributions"]["detection_confidence"]) == 7
    assert sum(row["count"] for row in performance["distributions"]["final_support"]) == 5


def test_missing_telemetry_is_unavailable_instead_of_derived_from_capture_or_duration(tmp_path):
    database = InspectionDatabase(tmp_path / "missing.sqlite3")
    database.create_session({"started_at": "2026-11-01T09:00:00-05:00"}, session_id="legacy")
    database.upsert_event("legacy", {"track_id": 1, "timestamp": "2026-11-01T09:01:00-05:00", "quality": "Ungraded",
                                     "fps": 99, "processing_time_ms": 10, "analysis": {"part_results": {"Body": {"present": True}}}})
    data = database.dashboard_analytics()
    assert data["anatomical_association"]["Body"]["raw_count"] is None
    assert data["anatomical_association"]["Body"]["assigned_count"] is None
    assert data["anatomical_association"]["Body"]["present_fish_count"] == 1
    assert data["performance"]["ai_fps"] == data["performance"]["camera_fps"] == []
    assert data["performance"]["average_image_processing_time_ms"] is None
    assert data["performance"]["fish_per_minute"] is None
    assert len(data["performance"]["unavailable"]) == 4


def test_mixed_sessions_with_unmeasured_active_time_do_not_inflate_fish_per_minute(saved):
    saved.create_session({"started_at": "2026-11-05T09:00:00-05:00"}, session_id="no-activity-checkpoint")
    saved.upsert_event("no-activity-checkpoint", {"track_id": 1, "timestamp": "2026-11-05T09:01:00-05:00", "quality": "Class A"})
    data = saved.dashboard_analytics()
    assert data["kpis"]["total_inspected"] == 8
    assert data["performance"]["fish_per_minute"] is None


def test_read_only_aggregation_does_not_change_any_persisted_rows(saved):
    def contents():
        with sqlite3.connect(saved.path) as connection:
            tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            return {table: connection.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall() for table in tables}
    before = contents()
    for granularity in ("hour", "day", "week", "month"):
        saved.dashboard_analytics(granularity=granularity)
    saved.dashboard_analytics(range_name="latest")
    saved.dashboard_analytics(range_name="custom", start_date="2026-11-03", end_date="2026-11-04")
    assert contents() == before


def test_cross_midnight_date_scope_never_uses_whole_session_active_time_for_partial_throughput(tmp_path):
    database = InspectionDatabase(tmp_path / "midnight.sqlite3")
    identifier = database.create_session({"started_at": "2026-11-03T23:50:00-05:00"})
    database.checkpoint_session_activity(identifier, 1200)
    database.end_session(identifier, ended_at="2026-11-04T00:10:00-05:00")
    for index, stamp in enumerate(("2026-11-03T23:55:00-05:00", "2026-11-04T00:05:00-05:00"), 1):
        database.upsert_event(identifier, {"track_id": index, "timestamp": stamp, "quality": "Class B"})
    data = database.dashboard_analytics(range_name="custom", start_date="2026-11-04", end_date="2026-11-04")
    assert data["kpis"]["total_inspected"] == data["kpis"]["session_count"] == 1
    assert data["session_comparison"][0]["partial_scope"]
    assert data["session_comparison"][0]["complete_fish_count"] == 2
    assert data["session_comparison"][0]["duration_seconds"] == 1200
    assert data["session_comparison"][0]["fish_per_minute"] is None
    assert data["performance"]["fish_per_minute"] is None


def test_analytics_api_adds_saved_dashboard_and_retains_legacy_graphs(saved, monkeypatch):
    app_module = importlib.import_module("src.api.app")
    monkeypatch.setattr(app_module, "inspection_database", saved)
    monkeypatch.setattr(app_module, "inspection_sessions", InspectionSessionContext(saved))
    result = app_module.get_analytics(range_name="latest", granularity="week")
    assert result["session_id"] == "saved-two"
    assert result["analytics_v2"]["kpis"]["total_inspected"] == result["total_inspected"] == 3
    assert result["analytics_v2"]["activity"]["granularity"] == "week"
    assert result["grade_distribution"] == result["analytics_v2"]["kpis"]["grade_distribution"]
    for legacy_field in ("average_part_quality_scores", "color_trend", "average_whole_fish_hue",
                         "average_first_detection_to_decision_ms", "decision_deadline_status_counts",
                         "average_evidence_coverage", "model_support", "session_activity"):
        assert legacy_field in result
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as invalid:
        app_module.get_analytics(range_name="all", granularity="invalid")
    assert invalid.value.status_code == 422


def test_coverage_chart_accepted_drilldown_excludes_rejected_and_ungraded(saved):
    rows, total = saved.events_page(session_id=None, range_name="all", start_date=None, end_date=None,
                                   page=1, page_size=100, search=None, grade="accepted", feature=None, min_confidence=None)
    dashboard = saved.dashboard_analytics()
    assert total == dashboard["coverage"]["classified"] == 4
    assert {row["quality"] for row in rows} == {"Class A", "Class B", "Class C"}


@pytest.mark.parametrize("kwargs", [{"granularity": "minute"}, {"range_name": "invalid"},
                                   {"range_name": "custom", "start_date": "bad"},
                                   {"range_name": "custom", "start_date": "2026-11-05", "end_date": "2026-11-01"}])
def test_invalid_analytics_filters_are_rejected(saved, kwargs):
    with pytest.raises(ValueError):
        saved.dashboard_analytics(**kwargs)
