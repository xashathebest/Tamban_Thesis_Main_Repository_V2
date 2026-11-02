"""Damage, segmentation and timing evidence never imply validated grading."""

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


ROOT = Path(__file__).resolve().parents[1]
VALID_LOCATION = {"x": 1, "y": 2, "width": 3, "height": 4}
DIAGNOSTIC_FIELDS = (
    "surface_damage_evidence_state", "surface_damage_validation_status",
    "surface_damage_confidence_kind", "surface_damage_reason", "surface_damage_analysis",
    "texture_status", "texture_missing_value_reason", "texture_analysis", "fish_mask_analysis",
    "mask_context_analysis", "inspection_performance", "inspection_compute_report",
    "surface_damage_extent_px", "surface_damage_length_method", "surface_damage_coordinate_space",
)


def specimen():
    return {"id": 3, "quality": "Class B", "analysis": {
        "final_grade": "Class B", "weighted_scores": {"Class B": .8},
        "surface_damage": {"status": "suspected", "severity": "unassessed", "confidence": .7,
            "confidence_kind": "heuristic_not_probability", "validation_status": "unvalidated",
            "mask_validated_for_cracks": False, "reason": "Original image contrast; expert review required",
            "coordinate_space": "crop_local_native_pixels", "crop_bounds": [20, 30, 200, 150],
            "locations": [{"x": 40, "y": 30, "width": 60, "height": 5,
                           "endpoints": [[40, 30], [100, 35]]}], "estimated_length_px": 60.2},
        "supporting_image_measurements": {"texture": {"status": "measured", "source": "runtime foreground mask",
            "mask_validated_for_cracks": False, "values": {"entropy": 3.2}}},
        "fish_mask": {"status": "validated_foreground", "source": "grabcut", "frame_id": 10,
            "parent_track_id": 3, "crop_bounds": [20, 30, 200, 150], "segmentation_ms": 12.5},
        "mask_context": {"segmentation_calls": 1, "cache_hits": 2},
        "performance": {"model1_inference_ms": 20.5, "model2_inference_ms": 30.2,
            "geometry_processing_ms": 2.5, "compute_report": {"device": "cpu", "fp16_enabled": False,
                "fallback_reason": "CUDA is unavailable"}},
    }}


def test_complete_diagnostics_roundtrip_without_changing_original_grade_or_observation():
    event = specimen()
    before = deepcopy(event)
    assert set(DIAGNOSTIC_FIELDS) <= set(DEFAULT_EXPORT_FIELDS)
    row = inspection_row(event)
    assert row["grade"] == "Class B"
    assert row["surface_damage_evidence_state"] == "Suspected Damage"
    assert row["surface_damage_validation_status"] == "unvalidated"
    assert row["texture_status"] == "measured"
    assert row["texture_missing_value_reason"] == ""
    expected_json = {
        "surface_damage_analysis": event["analysis"]["surface_damage"],
        "texture_analysis": event["analysis"]["supporting_image_measurements"]["texture"],
        "fish_mask_analysis": event["analysis"]["fish_mask"],
        "mask_context_analysis": event["analysis"]["mask_context"],
        "inspection_performance": event["analysis"]["performance"],
        "inspection_compute_report": event["analysis"]["performance"]["compute_report"],
    }
    csv_row = next(csv.DictReader(StringIO(make_csv([event], DIAGNOSTIC_FIELDS).decode("utf-8-sig"))))
    workbook = load_workbook(BytesIO(make_xlsx([event], DIAGNOSTIC_FIELDS, {})), data_only=True)
    spreadsheet = dict(zip(DIAGNOSTIC_FIELDS, list(workbook["Fish Inspections"].values)[1]))
    for field, expected in expected_json.items():
        assert json.loads(row[field]) == json.loads(csv_row[EXPORT_FIELDS[field]]) == json.loads(spreadsheet[field]) == expected
    assert event == before


@pytest.mark.parametrize("damage,expected", [
    ({}, "No reliable evidence"),
    ({"status": "not_detected"}, "No reliable evidence"),
    ({"status": "suspected", "locations": []}, "No reliable evidence"),
    ({"status": "suspected", "locations": [{}]}, "No reliable evidence"),
    ({"status": "suspected", "locations": [VALID_LOCATION], "evidence_state": "Validated Damage"}, "Suspected Damage"),
    ({"status": "suspected", "locations": [VALID_LOCATION], "mask_validated_for_cracks": True}, "Suspected Damage"),
    ({"status": "suspected", "locations": [VALID_LOCATION], "mask_validated_for_cracks": True,
      "validation_status": "validated"}, "Suspected Damage"),
    ({"status": "not_detected", "locations": [], "mask_validated_for_cracks": True,
      "validation_status": "validated", "validation_provenance": "Method reference labels"}, "No reliable evidence"),
    ({"status": "suspected", "locations": [VALID_LOCATION], "mask_validated_for_cracks": True,
      "validation_status": "validated", "validation_provenance": "Expert reference set, review 7"}, "Validated Damage"),
])
def test_damage_validation_requires_explicit_status_mask_validation_and_provenance(damage, expected):
    row = inspection_row({"analysis": {"surface_damage": damage}})
    assert row["surface_damage_evidence_state"] == expected
    assert row["surface_damage_validation_status"] == ("validated" if expected == "Validated Damage" else "unvalidated")


def test_historical_diagnostics_are_unavailable_without_fabricating_masks_or_compute():
    row = inspection_row({"quality": "Ungraded", "analysis": {}})
    assert row["surface_damage_evidence_state"] == "No reliable evidence"
    assert row["texture_status"] == "unavailable"
    assert "not recorded" in row["texture_missing_value_reason"]
    assert row["fish_mask_analysis"] == row["inspection_compute_report"] == ""


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for UI evidence behavior")
def test_browser_displays_actual_evidence_and_pauses_hidden_video_without_discarding_frames():
    script = r'''
const fs = require("fs"); const vm = require("vm");
const source = fs.readFileSync("frontend/app.js", "utf8");
const event = JSON.parse(fs.readFileSync(0, "utf8"));
function include(name) {
  const start = source.indexOf(`function ${name}(`);
  const next = source.slice(start + 1).search(/\n(?:async )?function /);
  vm.runInThisContext(source.slice(start, next < 0 ? source.length : start + 1 + next));
}
for (const name of ["surfaceDamageEvidence", "surfaceDamageRows", "textureEvidenceRows", "inspectionPerformanceRows", "playAnnotatedVideoFrames"]) include(name);
let tick; let workspaceClosed = false;
global.document = {hidden: false};
global.elements = {uploadImage: {classList: {remove() {}}}, uploadWorkspace: {classList: {contains() {return workspaceClosed;}}}};
global.resultDatasets = {upload: {rows: [event]}};
global.renderFishClickTargets = () => {};
global.setInterval = (callback) => {tick = callback; return 1;}; global.uploadFrameTimer = null;
const frames = ["frame-0", "frame-1", "frame-2"];
playAnnotatedVideoFrames(frames, "test.mp4"); const shown = [elements.uploadImage.src];
document.hidden = true; tick(); shown.push(elements.uploadImage.src);
document.hidden = false; workspaceClosed = true; tick(); shown.push(elements.uploadImage.src);
workspaceClosed = false; tick(); shown.push(elements.uploadImage.src); tick(); shown.push(elements.uploadImage.src);
const forged = {analysis: {surface_damage: {status: "suspected", locations: [{}], evidence_state: "Validated Damage"}}};
console.log(JSON.stringify({damage: surfaceDamageRows(event), missingDamage: surfaceDamageRows({}), forged: surfaceDamageRows(forged),
  texture: textureEvidenceRows(event), missingTexture: textureEvidenceRows({}),
  speed: inspectionPerformanceRows(event), missingSpeed: inspectionPerformanceRows({}), shown, frames}));
'''
    result = subprocess.run([shutil.which("node"), "-e", script], input=json.dumps(specimen()), cwd=ROOT,
                            capture_output=True, text=True, check=True)
    actual = json.loads(result.stdout)
    assert dict(actual["damage"])["Evidence state"] == "Suspected Damage"
    assert dict(actual["forged"])["Evidence state"] == "No reliable evidence"
    assert dict(actual["missingDamage"])["Evidence state"] == "No reliable evidence"
    assert "not a damage probability" in dict(actual["damage"])["Heuristic strength (0-1)"]
    assert "crop_local_native_pixels" in dict(actual["damage"])["Location coordinates"]
    assert dict(actual["texture"])["Texture analysis"] == "Measured diagnostic features"
    assert dict(actual["missingTexture"])["Texture analysis"].startswith("Unavailable:")
    assert dict(actual["speed"])["Inference device"] == "cpu"
    assert dict(actual["missingSpeed"])["Inference device"].startswith("Unavailable:")
    assert actual["shown"] == ["frame-0", "frame-0", "frame-0", "frame-1", "frame-2"]
    assert actual["frames"] == ["frame-0", "frame-1", "frame-2"]
