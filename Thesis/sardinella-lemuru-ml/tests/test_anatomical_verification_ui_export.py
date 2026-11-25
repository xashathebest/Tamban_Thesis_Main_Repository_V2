"""Anatomical verification stays separate from detector and grading evidence."""

from copy import deepcopy
import csv
from io import BytesIO, StringIO
import json
from pathlib import Path
import shutil
import subprocess

from openpyxl import load_workbook
import pytest

from src.api.export import DEFAULT_EXPORT_FIELDS, EXPORT_FIELDS, inspection_row, make_csv, make_xlsx
from test_qualitycheck_ui_exports import NODE


ROOT = Path(__file__).resolve().parents[1]
ORIGINAL_FIELDS = (
    "anatomical_verification_status", "anatomical_secondary_activated", "anatomical_automatic_rejection",
    "anatomical_missing_regions", "anatomical_rejection_reason", "anatomical_verification_reason", "anatomical_verification",
    *(field for region in ("head", "body") for field in (
        f"model2_{region}_detected", f"model2_{region}_detection_status", f"model2_{region}_detection_confidence",
        f"{region}_anatomical_state", f"{region}_anatomical_source", f"{region}_anatomical_confidence", f"{region}_anatomical_reason")),
)
FIELDS = (*ORIGINAL_FIELDS,
    "anatomical_fish_id", "anatomical_frame_id", "anatomical_review_reason", "anatomical_uncertainty_causes", "needs_review_reason",
    "model2_tail_detected", "model2_tail_detection_status", "model2_tail_detection_confidence", "anatomical_geometry_caveat",
    *(field for region in ("head", "body") for field in (
        f"{region}_anatomical_evidence_summary", f"{region}_anatomical_evidence")),
)


def specimen(status="UNCERTAIN"):
    missing = status == "MISSING"
    present = status == "PRESENT"
    verification = {
        "version": "1", "status": status, "activated": not present, "fish_id": 7, "frame_id": "software-frame-1",
        "review_reason": "Head visibility is ambiguous because neighboring fish overlap" if status == "UNCERTAIN" else None,
        "uncertainty_causes": ["neighbor_or_ownership_conflict", "occlusion_not_excluded"] if status == "UNCERTAIN" else [],
        "primary": {
            "Head": {"detected": present, "confidence": .82 if present else .13,
                     "status": "detected" if present else "below_threshold"},
            "Body": {"detected": True, "confidence": .91, "status": "detected"},
            "Tail": {"detected": False, "confidence": None, "status": "not_detected"},
        },
        "parts": {
            "Head": {"state": status, "source": "model2" if present else "reviewed_anatomy" if missing else "silhouette_geometry",
                     "confidence": .82 if present else .99 if missing else None,
                     "reason": "Assigned Model 2 Head" if present else "Reviewed Head is physically absent" if missing else "Neighbor overlap; ownership cannot be established <script>alert(1)</script>"},
            "Body": {"state": "PRESENT", "source": "model2", "confidence": .91, "reason": "Assigned Model 2 Body"},
        },
        "missing_regions": ["Head"] if missing else [],
        "rejection_reason": "=Confirmed Head absence" if missing else None,
        "geometry": {"orientation_degrees": 12., "ownership_reliable": not (status == "UNCERTAIN")},
        "reason": "Confirmed anatomical absence" if missing else "Primary anatomy verified" if present else "Insufficient independent evidence",
        "automatic_rejection": missing,
    }
    if missing:
        verification["parts"]["Head"]["evidence"] = [{
            "region": "Head", "state": "confirmed_absent", "source": "expert_review", "source_id": "software-fixture-only",
            "fish_id": 7, "frame_id": "software-frame-1", "review_id": "software-review-1", "reviewer": "test reviewer <script>",
        }]
    grade = "Rejected" if missing else "Class B" if present else "Ungraded"
    return {"id": 7, "quality": grade, "quality_confidence": .8, "analysis": {
        "final_grade": grade, "final_score": .8, "weighted_scores": {"Class B": .8},
        "verdict_status": "NEEDS_REVIEW" if status == "UNCERTAIN" else "AUTO_GRADED",
        "anatomical_verification": verification,
    }}


@pytest.mark.parametrize("status", ["PRESENT", "MISSING", "UNCERTAIN"])
def test_backend_csv_xlsx_preserve_primary_and_secondary_evidence(status):
    event = specimen(status); original = deepcopy(event)
    evidence = event["analysis"]["anatomical_verification"]
    row = inspection_row(event)
    assert set(FIELDS) <= set(DEFAULT_EXPORT_FIELDS)
    assert len(ORIGINAL_FIELDS) == 21
    assert not any("tail" in field for field in ORIGINAL_FIELDS)
    assert row["anatomical_verification_status"] == status
    assert row["model2_body_detected"] == "Yes"
    assert row["model2_body_detection_confidence"] == 91.
    assert row["head_anatomical_state"] == status
    assert row["head_anatomical_confidence"] == (82. if status == "PRESENT" else 99. if status == "MISSING" else "")
    assert row["anatomical_automatic_rejection"] == ("Yes" if status == "MISSING" else "No")
    assert json.loads(row["anatomical_verification"]) == evidence
    assert row["anatomical_fish_id"] == 7
    assert row["anatomical_frame_id"] == "software-frame-1"
    assert row["model2_tail_detected"] == "No"
    assert row["model2_tail_detection_confidence"] == ""
    assert row["needs_review_reason"] == (evidence["review_reason"] if status == "UNCERTAIN" else "")
    assert "not independently validated" in row["anatomical_geometry_caveat"]
    csv_row = next(csv.DictReader(StringIO(make_csv([event], FIELDS).decode("utf-8-sig"))))
    workbook = load_workbook(BytesIO(make_xlsx([event], FIELDS, {})), data_only=False)
    spreadsheet = dict(zip(FIELDS, list(workbook["Fish Inspections"].values)[1]))
    assert json.loads(csv_row[EXPORT_FIELDS["anatomical_verification"]]) == evidence
    assert json.loads(spreadsheet["anatomical_verification"]) == evidence
    assert spreadsheet["head_anatomical_reason"] == evidence["parts"]["Head"]["reason"]
    if status == "MISSING":
        assert "Review: software-review-1" in row["head_anatomical_evidence_summary"]
        assert "reviewer: test reviewer <script>" in row["head_anatomical_evidence_summary"]
        assert json.loads(row["head_anatomical_evidence"]) == evidence["parts"]["Head"]["evidence"]
        assert csv_row[EXPORT_FIELDS["anatomical_rejection_reason"]] == "'=Confirmed Head absence"
        cell = workbook["Fish Inspections"].cell(2, FIELDS.index("anatomical_rejection_reason") + 1)
        assert cell.value == "=Confirmed Head absence" and cell.data_type == "s"
    assert event == original


def test_legacy_record_has_unavailable_anatomy_without_invented_uncertainty():
    row = inspection_row({"id": 4, "quality": "Class B", "analysis": {}})
    assert row["anatomical_verification_status"] == row["head_anatomical_state"] == row["body_anatomical_state"] == "UNAVAILABLE"
    assert row["model2_head_detected"] == row["model2_body_detected"] == ""
    assert row["model2_head_detection_confidence"] == row["head_anatomical_confidence"] == ""
    assert row["anatomical_secondary_activated"] == row["anatomical_automatic_rejection"] == ""
    assert json.loads(row["anatomical_verification"]) == {}
    assert row["grade"] == "Class B"


def test_unavailable_model2_is_not_presented_as_failed_detection_or_verified_primary():
    from test_anatomical_verification import FISH_ID, FRAME_ID, SYNTHETIC_FRAME, engine, engine_parts

    verdict = engine().evaluate(FISH_ID, SYNTHETIC_FRAME, engine_parts(), stabilize=False, frame_id=FRAME_ID, model2_available=False)
    event = {"id": FISH_ID, "quality": "Ungraded", "analysis": verdict.to_dict()}
    row = inspection_row(event)
    assert row["anatomical_verification_status"] == "UNAVAILABLE"
    for region in ("head", "body", "tail"):
        assert row[f"model2_{region}_detected"] == row[f"model2_{region}_detection_confidence"] == ""
        assert row[f"model2_{region}_detection_status"] == "unavailable"
    shown = run_node(UI_NODE, [event])["rows"][0]
    rows = dict(shown["anatomy"])
    assert rows["Secondary verification"] == "Not activated; primary verification unavailable"
    for region in ("Head", "Body", "Tail"):
        assert rows[f"Model 2 {region}"].startswith("UNAVAILABLE; confidence Not recorded")
        suffix = " (optional)" if region == "Tail" else ""
        assert shown["record"][f"Model 2 {region} detected{suffix}"] == ""
        assert shown["record"][f"Model 2 {region} detection confidence (%){suffix}"] == ""


def test_primary_detections_with_ambiguous_association_display_needs_review():
    from test_anatomical_verification import FISH_ID, FRAME_ID, SYNTHETIC_FRAME, engine, engine_parts

    verdict = engine().evaluate(FISH_ID, SYNTHETIC_FRAME, engine_parts(), stabilize=False, frame_id=FRAME_ID, association_status="ambiguous")
    analysis = verdict.to_dict()
    event = {"id": FISH_ID, "quality": "Ungraded", "analysis": analysis}
    row = inspection_row(event)
    shown = run_node(UI_NODE, [event])["rows"][0]
    rows = dict(shown["anatomy"])
    assert row["anatomical_verification_status"] == "UNCERTAIN"
    assert row["anatomical_secondary_activated"] == "No"
    assert row["needs_review_reason"] == analysis["anatomical_verification"]["review_reason"]
    assert rows["Anatomical verification result"] == "NEEDS REVIEW"
    assert rows["Secondary verification"] == "Not activated; primary detection association requires review"
    assert rows["Model 2 Head"].startswith("DETECTED; confidence 90.0%")
    assert rows["Model 2 Body"].startswith("DETECTED; confidence 90.0%")
    assert rows["Model 2 Head association"].startswith("UNVERIFIED")
    assert rows["Model 2 Body association"].startswith("UNVERIFIED")
    assert shown["record"]["Reason for NEEDS REVIEW"] == row["needs_review_reason"]
    assert "association ambiguous" in rows["Anatomical uncertainty causes"]


def test_reviewed_absence_without_recorded_confidence_does_not_invent_scores():
    from test_anatomical_verification import FISH_ID, FRAME_ID, SOURCE, SYNTHETIC_FRAME, engine, engine_parts, review

    evidence = review()
    evidence.pop("confidence")
    verdict = engine().evaluate(FISH_ID, SYNTHETIC_FRAME, engine_parts(missing=("Head",)), stabilize=False,
                               frame_id=FRAME_ID, source_context=SOURCE, anatomical_evidence=[evidence])
    event = {"id": FISH_ID, "quality": "Rejected", "analysis": verdict.to_dict()}
    row = inspection_row(event)
    shown = run_node(UI_NODE, [event])["rows"][0]
    assert verdict.final_grade == "Rejected"
    assert row["model2_head_detection_confidence"] == row["head_anatomical_confidence"] == row["grade_confidence"] == ""
    assert shown["record"]["Head anatomical verification confidence (%)"] == ""
    assert dict(shown["anatomy"])["Head verification confidence"] == "Not recorded"
    assert "synthetic-review-1" in dict(shown["anatomy"])["Evidence supporting rejection"]


@pytest.mark.parametrize("region", ["Head", "Body"])
@pytest.mark.parametrize("reviewed", [True, False])
def test_real_engine_anatomical_gate_survives_fusion_and_csv_without_invented_support(region, reviewed):
    from test_anatomical_verification import FISH_ID, FRAME_ID, SOURCE, SYNTHETIC_FRAME, engine, engine_parts, review

    verdict = engine().evaluate(
        FISH_ID, SYNTHETIC_FRAME, engine_parts(missing=(region,)), stabilize=False, frame_id=FRAME_ID,
        source_context=SOURCE, anatomical_evidence=[review(region)] if reviewed else [],
    )
    analysis = verdict.to_dict()
    final_grade = "Rejected" if reviewed else "Ungraded"
    state = "MISSING" if reviewed else "UNCERTAIN"
    event = {"id": FISH_ID, "quality": final_grade, "quality_confidence": verdict.final_score, "analysis": analysis}
    assert verdict.final_score is analysis["final_score"] is analysis["final_support"] is None
    assert analysis["feature_fusion"]["final_grade"] == final_grade
    assert analysis["feature_fusion"]["final_support"] is None
    nested_fusion = analysis["feature_fusion"]["decision_fusion"]
    assert nested_fusion["final_fused_prediction"] == final_grade
    assert nested_fusion["decision_confidence"] is None
    row = inspection_row(event)
    assert row["grade"] == row["final_combined_grade"] == row["final_fused_prediction"] == final_grade
    assert row["final_weighted_score"] == row["grade_confidence"] == row["final_combined_support"] == row["fusion_decision_confidence"] == ""
    assert row["anatomical_verification_status"] == row[f"{region.lower()}_anatomical_state"] == state
    assert row["verdict_status"] == ("AUTO_GRADED" if reviewed else "NEEDS_REVIEW")
    assert row["anatomical_automatic_rejection"] == ("Yes" if reviewed else "No")
    if reviewed:
        assert region in row["anatomical_rejection_reason"]
        assert row["anatomical_rejection_reason"] == analysis["verdict_reason_text"]
        assert row["anatomical_missing_regions"] == region
        summary = row[f"{region.lower()}_anatomical_evidence_summary"]
        assert "synthetic-review-1" in summary and "synthetic-software-fixture" in summary
        assert f"Fish: {FISH_ID}" in summary and f"frame: {FRAME_ID}" in summary
        assert json.loads(row[f"{region.lower()}_anatomical_evidence"])[0]["source_id"] == SOURCE["source_id"]
    else:
        assert row["anatomical_rejection_reason"] == row["anatomical_missing_regions"] == ""
    fields = ("grade", "final_combined_grade", "final_fused_prediction", "final_weighted_score", "grade_confidence",
              "final_combined_support", "fusion_decision_confidence", "verdict_status", *FIELDS)
    csv_row = next(csv.DictReader(StringIO(make_csv([event], fields).decode("utf-8-sig"))))
    for field in fields:
        assert csv_row[EXPORT_FIELDS[field]] == str(row[field])
    assert json.loads(csv_row[EXPORT_FIELDS["anatomical_verification"]]) == analysis["anatomical_verification"]
    # Execute the real frontend grade/support functions against the engine's
    # fusion report; this catches a stale pre-anatomy fusion grade taking priority.
    script = UI_NODE.replace('"anatomicalReviewHeld",', '"aiFinalGrade", "weightedFinalSupport", "resultGrade", "manualGrade", "eventValue", "decisionFusionEvidence", "decisionFusionState", "decisionFusionBadge", "decisionFusionFeatureRows", "anatomicalReviewHeld",', 1)
    script = script.replace('global.aiFinalGrade = global.resultGrade = e => e.quality || "Ungraded";', '')
    script = script.replace('global.weightedFinalSupport = e => e.quality_confidence;', '')
    script = script.replace('({anatomy: anatomicalVerificationRows(e),', '({fusionBadge: decisionFusionBadge(e).textContent, fusionState: decisionFusionState(decisionFusionEvidence(e)), anatomy: anatomicalVerificationRows(e),', 1)
    actual = run_node(script, [event])["rows"][0]
    assert actual["record"]["Final AI grade"] == actual["record"]["Final classification"] == final_grade
    assert actual["record"]["Final fused prediction"] == final_grade
    assert actual["record"]["Final combined support (0-1)"] == ""
    assert actual["record"]["Anatomical automatic rejection reason"] == row["anatomical_rejection_reason"]
    assert ("confirmed missing anatomy" if reviewed else "UNCERTAIN") in actual["fusionState"]["label"]
    assert actual["fusionBadge"] == actual["fusionState"]["label"]
    assert dict(actual["anatomy"])["Anatomical Fish ID"] == FISH_ID
    assert dict(actual["anatomy"])["Anatomical frame ID"] == FRAME_ID
    assert actual["record"]["Anatomical verification Fish ID"] == FISH_ID
    assert actual["record"]["Anatomical verification frame ID"] == FRAME_ID
    assert "not independently validated" in actual["record"]["Anatomical geometry evidence limitation"]
    if reviewed:
        assert "synthetic-review-1" in dict(actual["anatomy"])["Evidence supporting rejection"]
        assert "synthetic-software-fixture" in actual["record"][f"{region} recorded anatomical supporting evidence"]
    else:
        assert dict(actual["anatomy"])["Anatomical verification result"] == "NEEDS REVIEW"
        assert actual["record"]["Reason for NEEDS REVIEW"] == row["needs_review_reason"]


UI_NODE = NODE.replace('"surfaceDamageEvidence",', '"anatomicalReviewHeld", "anatomicalVerificationRows", "anatomicalVerificationExportFields", "surfaceDamageEvidence",', 1)
UI_NODE = UI_NODE.replace('global.resultsSource =', 'global.analysisFor = e => e?.analysis || {};\nglobal.resultsSource =', 1)
UI_NODE = UI_NODE.replace('({body: bodyWidthRows(e),', '({anatomy: anatomicalVerificationRows(e), held: anatomicalReviewHeld(e), exportFields: anatomicalVerificationExportFields(), body: bodyWidthRows(e),', 1)


def run_node(script, value):
    if not shutil.which("node"):
        pytest.skip("Node is unavailable for dashboard interpretation")
    result = subprocess.run([shutil.which("node"), "-e", script], input=json.dumps(value), cwd=ROOT,
                            capture_output=True, text=True, check=True, timeout=30)
    return json.loads(result.stdout)


def test_browser_reports_detector_and_secondary_states_and_escapes_reasons():
    inputs = [specimen(status) for status in ("PRESENT", "MISSING", "UNCERTAIN")]
    # A current automatic absence decision supersedes the old UI-only hold.
    inputs[1]["analysis"]["structural_evidence"] = {"regions": {"Head": {"state": "confirmed_absent"}}}
    inputs.append({"id": 9, "quality": "Class B", "analysis": {}})
    actual = run_node(UI_NODE, inputs)
    for index, status in enumerate(("PRESENT", "MISSING", "UNCERTAIN", "UNAVAILABLE")):
        shown = actual["rows"][index]; evidence = inputs[index]["analysis"].get("anatomical_verification", {})
        rows = dict(shown["anatomy"])
        assert rows["Head / Body anatomy"] == status
        assert rows["Head anatomical state"] == status
        assert rows["Tail policy"].startswith("Optional")
        assert shown["held"] is (status == "UNCERTAIN")
        assert set(shown["exportFields"]) == set(FIELDS)
        assert shown["record"]["Head / Body anatomical verification status"] == status
        assert json.loads(shown["record"]["Complete anatomical verification"]) == evidence
        assert "<h4>Head / Body anatomical verification</h4>" in shown["report"]
    uncertain = actual["rows"][2]
    assert dict(uncertain["anatomy"])["Model 2 Head"] == "BELOW THRESHOLD; confidence 13.0%"
    assert dict(uncertain["anatomy"])["Head verification confidence"] == "Not recorded"
    assert dict(uncertain["anatomy"])["Model 2 Tail"] == "NOT DETECTED; confidence Not recorded; optional"
    assert dict(uncertain["anatomy"])["Reason for NEEDS REVIEW"] == inputs[2]["analysis"]["anatomical_verification"]["review_reason"]
    assert "neighbor or ownership conflict" in dict(uncertain["anatomy"])["Anatomical uncertainty causes"]
    assert "software-review-1" in actual["rows"][1]["report"]
    assert "test reviewer &lt;script&gt;" in actual["rows"][1]["report"]
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in uncertain["report"]
    assert "<script>alert(1)</script>" not in uncertain["report"]
    assert "UNCERTAIN" not in json.dumps(actual["rows"][3]["anatomy"])
    csv_rows = list(csv.DictReader(StringIO(actual["csv"].lstrip("\ufeff"))))
    assert csv_rows[1]["Anatomical automatic rejection reason"] == "'=Confirmed Head absence"
    assert csv_rows[2]["Head anatomical state"] == "UNCERTAIN"


def test_default_export_checkbox_groups_human_readable_and_raw_evidence_once():
    script = NODE.split('for (const name of [', 1)[0] + r'''
include("ensureAnatomicalExportFields"); include("anatomicalVerificationExportFields");
const container = {children:[], querySelector() { return this.children[0]?.children?.find(item => item.value === "anatomical_verification"); }, append(item) { this.children.push(item); }};
global.document = {querySelector: () => container, createTextNode: text => ({text}), createElement: tag => ({tag, children:[], append(...items) { this.children.push(...items); }})};
ensureAnatomicalExportFields(); ensureAnatomicalExportFields();
console.log(JSON.stringify({labels: container.children.length, input: container.children[0].children[0], fields: anatomicalVerificationExportFields()}));
'''
    actual = run_node(script, [])
    assert actual["labels"] == 1
    assert actual["input"]["checked"] is True
    assert actual["input"]["value"] == "anatomical_verification"
    assert set(actual["fields"]) == set(FIELDS)
    source = (ROOT / "frontend/app.js").read_text(encoding="utf-8")
    assert 'if (fields.includes("anatomical_verification")) fields.push(...anatomicalVerificationExportFields()' in source
    for name in ("renderLatest", "appendResultCard", "renderFishZoomDetails"):
        code = source.split(f"function {name}(", 1)[1].split("\nfunction ", 1)[0]
        assert "appendAnatomicalVerificationPanel" in code
    history = source.split("function renderHistoryRows(", 1)[1].split("\nfunction ", 1)[0]
    assert "anatomicalVerificationRows(event)" in history
