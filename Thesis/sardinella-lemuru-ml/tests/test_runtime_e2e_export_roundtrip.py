"""Real detector traces must survive Excel's 32,767-character cell limit."""
from copy import deepcopy
import csv
import hashlib
from io import BytesIO, StringIO
import json

from openpyxl import load_workbook
import pytest

from src.api.export import EXPORT_FIELDS, inspection_row, make_csv, make_xlsx
from src.evaluation.evaluate_association_repairs import csv_scene
from src.inference.association import ParentAnchor, associate_parts_to_parents, association_summary
from src.inference.part_types import PartDetection


FIELDS = ("fish_id", "grade", "anatomical_association_diagnostics", "anatomical_part_decisions",
          "anatomical_inference_provenance", "model2_raw_detection_diagnostics", "complete_fish_event")


def real_trace(tmp_path):
    scene = csv_scene(image_root=tmp_path)
    parents = [ParentAnchor(row["id"], tuple(row["bbox"]), row["confidence"]) for row in scene["detections"]]
    parts = [PartDetection.from_source_class(row["source_class_id"], row["confidence"], tuple(row["bbox"]))
             for row in scene["parts"]]
    association = association_summary(associate_parts_to_parents(parts, parents), 3)
    association.update(coordinate_space="original_frame", frame_id="real-csv-trace", frame_width_px=3840, frame_height_px=2160)
    event = {"id": 3, "bbox": list(parents[2].bbox), "quality": "Class B", "timestamp": "2026-11-01T00:20:20.811Z",
             "analysis": {"final_grade": "Class B", "final_score": .8, "weighted_scores": {"Class B": .8},
                          "quality_inference": {"association": association},
                          "model2_debug": {"raw_detections": [p.to_dict() for p in parts], "coordinate_space": "original_frame"}}}
    return event


def recover(workbook, value):
    reference = json.loads(value)["xlsx_extended_evidence"]
    sheet = workbook[reference["sheet"]]
    records = [dict(zip(next(sheet.values), row)) for row in list(sheet.values)[1:]]
    chunks = sorted([row for row in records if row["Record key"] == reference["record_key"]], key=lambda row: row["Chunk number"])
    assert len(chunks) == reference["chunk_count"]
    assert [row["Chunk number"] for row in chunks] == list(range(1, len(chunks) + 1))
    text = "".join(row["Text chunk"] for row in chunks)
    assert len(text) == reference["character_count"]
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == reference["sha256"]
    assert all(row["SHA-256"] == reference["sha256"] for row in chunks)
    assert all(len(row["Text chunk"].encode("utf-16-le")) // 2 <= 32767 for row in chunks)
    return text, chunks


def test_actual_native_association_and_complete_event_roundtrip_in_xlsx(tmp_path):
    event = real_trace(tmp_path)
    before = deepcopy(event)
    expected = inspection_row(event)
    assert len(expected["anatomical_association_diagnostics"]) > 32767
    workbook = load_workbook(BytesIO(make_xlsx([event], FIELDS, {})), data_only=True)
    assert workbook.sheetnames[-1] == "Extended Evidence"
    actual = dict(zip(FIELDS, list(workbook["Fish Inspections"].values)[1]))
    assert actual["grade"] == "Class B"
    for field in FIELDS[2:]:
        if len(expected[field].encode("utf-16-le")) // 2 > 32767:
            text, chunks = recover(workbook, actual[field])
            assert json.loads(text) == json.loads(expected[field])
            assert chunks[0]["Source sheet"] == "Fish Inspections"
            assert chunks[0]["Source row"] == 2
            assert chunks[0]["Field key"] == field
            assert chunks[0]["Fish ID"] == "Fish #3"
        else:
            assert actual[field] == expected[field]
    assert event == before


def test_csv_keeps_full_native_json_and_existing_grade_without_excel_references(tmp_path):
    event = real_trace(tmp_path)
    expected = inspection_row(event)
    limit = csv.field_size_limit(10_000_000)
    try:
        row = next(csv.DictReader(StringIO(make_csv([event], FIELDS).decode("utf-8-sig"))))
    finally:
        csv.field_size_limit(limit)
    assert row[EXPORT_FIELDS["grade"]] == "Class B"
    for field in FIELDS[2:]:
        assert row[EXPORT_FIELDS[field]] == expected[field]
        assert "xlsx_extended_evidence" not in row[EXPORT_FIELDS[field]]


@pytest.mark.parametrize("text", ["x" * 32768, "🐟" * 17000, "=" + "x" * 65000], ids=["long-ascii", "utf16-fish", "formula-like"])
def test_oversized_session_text_uses_explicit_reference_and_literal_chunks(text):
    workbook = load_workbook(BytesIO(make_xlsx([], ["fish_id"], {}, session_configuration={"review_note": text})), data_only=False)
    reference = workbook["Session Configuration"]["B2"].value
    assert reference.startswith("Full text stored in Extended Evidence:")
    chunks = list(workbook["Extended Evidence"].iter_rows(min_row=2, values_only=True))
    assert "".join(row[-1] for row in chunks) == text
    for row in workbook["Extended Evidence"].iter_rows(min_row=2):
        assert row[-1].data_type == "s"
        assert len(row[-1].value.encode("utf-16-le")) // 2 <= 32767


def test_small_workbooks_preserve_cells_and_existing_sheet_order():
    workbook = load_workbook(BytesIO(make_xlsx([], ["fish_id"], {}, session_configuration={"review_note": "x" * 32767})))
    assert workbook.sheetnames == ["Fish Inspections", "Session Summary", "Feature Summary", "Grade Calculation Rules", "Review Queue", "Session Configuration"]
    assert workbook["Session Configuration"]["B2"].value == "x" * 32767
