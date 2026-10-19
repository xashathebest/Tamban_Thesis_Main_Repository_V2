"""Exported inspection columns follow the operator's selected order."""
import csv
from io import BytesIO, StringIO
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from src.api import app
from src.api.export import DEFAULT_EXPORT_FIELDS, EXPORT_FIELDS, make_csv, make_xlsx


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(app, "_durable_events", lambda **_: [{"track_id": 7, "timestamp": "2026-01-01T00:00:00+00:00", "quality": "Class A", "analysis": {}}])
    monkeypatch.setattr(app, "_status_payload", lambda: {"grading_rules": {}})
    monkeypatch.setattr(app, "inspection_sessions", SimpleNamespace(session_id=None))
    monkeypatch.setattr(app, "inspection_database", SimpleNamespace(session=lambda _: None))
    return TestClient(app.app)


def headers(response, export_format):
    if export_format == "csv":
        return next(csv.reader(StringIO(response.content.decode("utf-8-sig"))))
    workbook = load_workbook(BytesIO(response.content), data_only=True)
    assert {"Fish Inspections", "Session Summary", "Feature Summary", "Grade Calculation Rules", "Review Queue"} <= set(workbook.sheetnames)
    return [cell.value for cell in workbook["Fish Inspections"][1]]


@pytest.mark.parametrize("export_format", ["csv", "xlsx"])
def test_selected_fields_are_the_only_inspection_columns_in_requested_order(client, export_format):
    fields = ["grade", "fish_id", "timestamp"]
    response = client.post("/api/export", json={"format": export_format, "fields": fields})
    assert response.status_code == 200
    assert headers(response, export_format) == [EXPORT_FIELDS[field] for field in fields]


@pytest.mark.parametrize("export_format", ["csv", "xlsx"])
def test_explicit_full_evidence_export_works_with_no_checked_fields(client, export_format):
    response = client.post("/api/export", json={"format": export_format, "fields": [], "complete_analysis": True})
    assert response.status_code == 200
    assert headers(response, export_format) == [EXPORT_FIELDS[field] for field in DEFAULT_EXPORT_FIELDS]


@pytest.mark.parametrize("payload", [
    {},
    {"fields": []},
    {"fields": ["fish_id", "fish_id"]},
    {"fields": ["fish_id"], "complete_analysis": "true"},
])
def test_invalid_selection_is_rejected(client, payload):
    assert client.post("/api/export", json=payload).status_code == 422


def test_exported_user_text_remains_text_in_spreadsheets():
    event = {"track_id": 7, "fish_label": 'Fish, "Mañana"\nBatch', "reviewer": '=1+1',
             "timestamp": "2026-10-18T12:00:00-04:00", "quality": "Class A", "analysis": {}}
    fields = ["fish_id", "timestamp", "reviewer"]
    csv_rows = list(csv.reader(StringIO(make_csv([event], fields).decode("utf-8-sig"))))
    assert csv_rows[1] == [event["fish_label"], event["timestamp"], "'=1+1"]
    workbook = load_workbook(BytesIO(make_xlsx([event], fields, {}, session_configuration={"note": "=2+2"})), data_only=False)
    row = workbook["Fish Inspections"][2]
    assert [cell.value for cell in row] == [event["fish_label"], event["timestamp"], event["reviewer"]]
    assert row[2].data_type == "s"
    assert workbook["Session Configuration"]["B2"].value == "=2+2"
    assert workbook["Session Configuration"]["B2"].data_type == "s"


def test_empty_exports_keep_headers():
    assert len(list(csv.reader(StringIO(make_csv([], ["fish_id"]).decode("utf-8-sig"))))) == 1
    workbook = load_workbook(BytesIO(make_xlsx([], ["fish_id"], {})), data_only=True)
    assert list(workbook["Fish Inspections"].values) == [(EXPORT_FIELDS["fish_id"],)]


@pytest.mark.parametrize("value", ["=1+1", "  =1+1", "+1", "-1", "@name", "\ttext"])
def test_csv_neutralizes_spreadsheet_formula_prefixes(value):
    rows = list(csv.reader(StringIO(make_csv([{"reviewer": value}], ["reviewer"]).decode("utf-8-sig"))))
    assert rows[1] == ["'" + value]
