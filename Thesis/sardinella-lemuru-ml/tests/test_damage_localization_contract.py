"""Localized damage claims must agree across evidence cards and saved reports."""
from copy import deepcopy
import csv
from html import unescape
from io import BytesIO, StringIO
import json
from pathlib import Path
import re
import shutil
import subprocess

from openpyxl import load_workbook
import pytest

from src.api.export import (
    EXPORT_FIELDS, _localized_damage_locations, inspection_row, make_csv, make_xlsx,
)


ROOT = Path(__file__).resolve().parents[1]
BOX = {"x": 4, "y": 5, "width": 12, "height": 3}
NONE = "No reliable evidence"
SUSPECTED = "Suspected Damage"
VALIDATED = "Validated Damage"


def damage(**changes):
    return {
        "status": "suspected", "locations": [deepcopy(BOX)],
        "validation_status": "validated", "mask_validated_for_cracks": True,
        "validation_provenance": "Expert reference review 7",
        "confidence": .7, "estimated_length_px": 12.3,
        "reason": "Recorded image support <fish>; raw evidence retained",
        **changes,
    }


CASES = [
    ("empty_locations", damage(locations=[]), NONE),
    ("empty_location_object", damage(locations=[{}]), NONE),
    ("nonlist_locations", damage(locations=BOX), NONE),
    ("nondictionary_location", damage(locations=[17]), NONE),
    ("missing_height", damage(locations=[{"x": 4, "y": 5, "width": 12}]), NONE),
    ("string_coordinate", damage(locations=[{**BOX, "x": "4"}]), NONE),
    ("boolean_coordinate", damage(locations=[{**BOX, "x": True}]), NONE),
    ("boolean_extent", damage(locations=[{**BOX, "width": True}]), NONE),
    ("negative_x", damage(locations=[{**BOX, "x": -1}]), NONE),
    ("negative_y", damage(locations=[{**BOX, "y": -1}]), NONE),
    ("zero_width", damage(locations=[{**BOX, "width": 0}]), NONE),
    ("negative_height", damage(locations=[{**BOX, "height": -3}]), NONE),
    ("overflowing_right", damage(locations=[{**BOX, "x": 1e308, "width": 1e308}]), NONE),
    ("overflowing_bottom", damage(locations=[{**BOX, "y": 1e308, "height": 1e308}]), NONE),
    ("invalid_bound_count", damage(crop_bounds=[100, 200, 140]), NONE),
    ("invalid_bound_type", damage(crop_bounds="100,200,140,230"), NONE),
    ("string_bound", damage(crop_bounds=[100, 200, "140", 230]), NONE),
    ("boolean_bound", damage(crop_bounds=[False, 0, 40, 30]), NONE),
    ("negative_bound", damage(crop_bounds=[-1, 0, 40, 30]), NONE),
    ("reversed_bounds", damage(crop_bounds=[140, 200, 100, 230]), NONE),
    ("outside_local_crop", damage(crop_bounds=[100, 200, 140, 230],
                                  coordinate_space="crop_local_native_pixels",
                                  locations=[{**BOX, "x": 35}]), NONE),
    ("outside_original_crop", damage(crop_bounds=[100, 200, 140, 230],
                                     coordinate_space="original_frame",
                                     locations=[{"x": 90, "y": 210, "width": 12, "height": 3}]), NONE),
    ("local_edge_inclusive", damage(crop_bounds=[100, 200, 140, 230],
                                    coordinate_space="crop_local_native_pixels",
                                    locations=[{"x": 0, "y": 0, "width": 40, "height": 30}]), VALIDATED),
    ("original_edge_inclusive", damage(crop_bounds=[100, 200, 140, 230],
                                       coordinate_space="original_frame",
                                       locations=[{"x": 100, "y": 200, "width": 40, "height": 30}]), VALIDATED),
    ("no_validation_status", damage(validation_status=None), SUSPECTED),
    ("no_mask_validation", damage(mask_validated_for_cracks=False), SUSPECTED),
    ("string_mask_validation", damage(mask_validated_for_cracks="true"), SUSPECTED),
    ("no_provenance", damage(validation_provenance=None), SUSPECTED),
    ("empty_provenance", damage(validation_provenance=""), SUSPECTED),
    ("whitespace_provenance", damage(validation_provenance=" \t\n"), SUSPECTED),
    ("numeric_provenance", damage(validation_provenance=7), SUSPECTED),
    ("empty_mapping_provenance", damage(validation_provenance={}), SUSPECTED),
    ("explicit_string_provenance", damage(), VALIDATED),
    ("explicit_mapping_provenance", damage(validation_provenance={"review_id": "expert-7"}), VALIDATED),
    ("explicit_validated_status", damage(status="validated"), VALIDATED),
    ("not_detected_status", damage(status="not_detected"), NONE),
    ("invalid_and_valid_locations", damage(locations=[{}, deepcopy(BOX)]), VALIDATED),
]


def specimen(recorded_damage):
    return {
        "track_id": 7, "quality": "Class B", "quality_confidence": .82,
        "timestamp": "2026-11-01T00:20:20.811Z",
        "analysis": {
            "weighted_scores": {"Class A": .1, "Class B": .82, "Class C": .03, "Rejected": 0},
            "geometric_support": {"original_grade": "Class B", "final_grade": "Class B",
                                  "original_support": .82, "applied_score_shift": 0},
            "surface_damage": deepcopy(recorded_damage),
        },
    }


FIELDS = (
    "grade", "original_weighted_grade", "final_combined_grade", "class_b_weighted_score",
    "surface_damage_evidence_state", "surface_damage_validation_status",
    "surface_damage_analysis", "surface_damage_locations", "surface_damage_extent_px",
)


@pytest.mark.parametrize("name,recorded_damage,expected", CASES, ids=[case[0] for case in CASES])
def test_python_csv_xlsx_require_localization_and_preserve_raw_evidence(name, recorded_damage, expected):
    event = specimen(recorded_damage)
    before = deepcopy(event)
    row = inspection_row(event)
    csv_row = next(csv.DictReader(StringIO(make_csv([event], FIELDS).decode("utf-8-sig"))))
    workbook = load_workbook(BytesIO(make_xlsx([event], FIELDS, {})), data_only=True)
    excel_row = dict(zip(FIELDS, list(workbook["Fish Inspections"].values)[1]))
    csv_values = {field: csv_row[EXPORT_FIELDS[field]] for field in FIELDS}
    for saved in (row, csv_values, excel_row):
        assert saved["surface_damage_evidence_state"] == expected
        assert saved["surface_damage_validation_status"] == ("validated" if expected == VALIDATED else "unvalidated")
        assert json.loads(saved["surface_damage_analysis"]) == recorded_damage
        assert json.loads(saved["surface_damage_locations"]) == recorded_damage["locations"]
        assert saved["grade"] == saved["original_weighted_grade"] == saved["final_combined_grade"] == "Class B"
        assert float(saved["class_b_weighted_score"]) == pytest.approx(82)
        if expected == NONE:
            assert saved["surface_damage_extent_px"] in ("", None)
    assert event == before


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), 10 ** 400],
                         ids=["nan", "positive_infinity", "negative_infinity", "integer_overflow"])
@pytest.mark.parametrize("field", ["x", "y", "width", "height"])
def test_python_in_memory_nonfinite_rectangle_cannot_localize(field, value):
    candidate = damage(locations=[{**BOX, field: value}])
    assert _localized_damage_locations(candidate) == []
    bounds = [100, 200, 140, 230]
    bounds[("x", "y", "width", "height").index(field)] = value
    assert _localized_damage_locations(damage(crop_bounds=bounds)) == []


@pytest.fixture(scope="module")
def browser_results():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for browser damage evidence contracts")
    script = r'''
const fs = require("fs"); const vm = require("vm");
const source = fs.readFileSync("frontend/app.js", "utf8");
const cases = JSON.parse(fs.readFileSync(0, "utf8"));
function include(name) {
  const start = source.indexOf(`function ${name}(`);
  if (start < 0) throw Error(`Missing actual function: ${name}`);
  const next = source.slice(start + 1).search(/\n(?:async )?function /);
  vm.runInThisContext(source.slice(start, next < 0 ? source.length : start + 1 + next));
}
for (const name of ["analysisFor", "partFor", "partStatus", "latestFeatureRows", "surfaceDamageEvidence", "surfaceDamageRows", "resultGrade", "resultIdentity", "recordedResultTimestamp", "flattenResultData", "resultExportRecord", "resultReportHtml"]) include(name);
global.resultsFilter = "All"; global.resultsSource = "upload";
global.resultDatasets = {upload: {scope: "photo", metadata: {source_name: "localized-damage regression"}}};
global.sessionGradeBuckets = ["Class A", "Class B", "Class C", "Rejected", "Ungraded"];
global.manualGrade = () => null; global.aiFinalGrade = event => event.quality;
global.weightedFinalSupport = event => event.quality_confidence;
global.scoreText = value => value == null ? "Not recorded" : `${value * 100}%`;
// These helpers concern independent geometry/grading formatting; damage callers remain real.
global.bodyWidthRows = () => []; global.resultEvidenceRows = event => [["Original AI grade", event.quality]];
global.finalExplanationRows = event => [["Final classification", event.quality]];
global.measurementRegion = () => ({status: "unavailable", reading: {}});
const output = {};
for (const [name, event] of cases) {
  const before = JSON.stringify(event);
  const evidence = surfaceDamageEvidence(event);
  output[name] = {state: evidence.state, count: evidence.locations.length,
    rows: surfaceDamageRows(event), latest: latestFeatureRows(event),
    csv: resultExportRecord(event), report: resultReportHtml([event]),
    unmodified: before === JSON.stringify(event)};
}
output.nonfinite = [];
for (const value of [NaN, Infinity, -Infinity]) {
  for (const field of ["x", "y", "width", "height"]) {
    const event = structuredClone(cases[0][1]);
    event.analysis.surface_damage.locations = [{x: 4, y: 5, width: 12, height: 3, [field]: value}];
    output.nonfinite.push(surfaceDamageEvidence(event).state);
    event.analysis.surface_damage.locations = [{x: 4, y: 5, width: 12, height: 3}];
    event.analysis.surface_damage.crop_bounds = [100, 200, 140, 230];
    event.analysis.surface_damage.crop_bounds[["x", "y", "width", "height"].indexOf(field)] = value;
    output.nonfinite.push(surfaceDamageEvidence(event).state);
  }
}
console.log(JSON.stringify(output));
'''
    payload = [(name, specimen(recorded_damage)) for name, recorded_damage, _ in CASES]
    run = subprocess.run([node, "-e", script], input=json.dumps(payload, allow_nan=False),
                         cwd=ROOT, text=True, capture_output=True, check=True)
    return json.loads(run.stdout)


@pytest.mark.parametrize("name,recorded_damage,expected", CASES, ids=[case[0] for case in CASES])
def test_browser_card_csv_and_printable_pdf_share_localized_claim(name, recorded_damage, expected, browser_results):
    actual = browser_results[name]
    record = actual["csv"]
    assert actual["state"] == dict(actual["rows"])["Evidence state"] == expected
    assert next(row[1] for row in actual["latest"] if row[0] == "Cracks") == expected
    assert record["Structural damage evidence state"] == expected
    assert record["Structural damage validation status"] == ("validated" if expected == VALIDATED else "unvalidated")
    assert json.loads(record["Complete Structural Damage Evidence"]) == recorded_damage
    assert json.loads(record["Complete fish event"])["analysis"]["surface_damage"] == recorded_damage
    assert record["Final AI grade"] == record["Final classification"] == record["Original weighted grade"] == "Class B"
    assert record["Final combined support (0-1)"] == .82
    assert f"<td>Evidence state</td><td>{expected}</td>" in actual["report"]
    assert "Recorded image support &lt;fish&gt;" in actual["report"]
    assert "<fish>" not in actual["report"]
    raw_cell = re.search(r"<td>Recorded structural evidence</td><td>(.*?)</td>", actual["report"], re.S)
    assert raw_cell is not None
    assert json.loads(unescape(raw_cell[1])) == recorded_damage
    assert actual["unmodified"] is True
    if expected == NONE:
        assert actual["count"] == 0 or recorded_damage["status"] == "not_detected"
        assert record["Structural discontinuity support extent (px)"] == ""
        assert dict(actual["rows"])["Heuristic strength (0-1)"].startswith("Unavailable")


def test_browser_in_memory_nonfinite_rectangles_cannot_localize(browser_results):
    assert browser_results["nonfinite"] == [NONE] * 24
