"""Per-fish silhouette measurements stay distinct from legacy box proxies."""

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
FIELDS = (
    "fish_length_px", "max_body_width_px", "relative_fish_body_width_ratio",
    "fish_geometry_status", "fish_geometry_reliability", "fish_geometry_reasons",
    "fish_geometry_method", "fish_geometry_orientation_degrees",
    "fish_geometry_measurement_validated", "fish_geometry_used_for_grading",
    "fish_length_cm", "max_body_width_cm", "physical_calibration_status",
    "physical_calibration", "fish_geometry_analysis",
)
GEOMETRY = {
    "status": "measured", "reliability": "Reliable pixel geometry", "reasons": [],
    "method": "segmentation_centerline_profile_v1", "fish_length_px": 280.125,
    "max_body_width_px": 70.03125, "relative_width_ratio": .25,
    "orientation_degrees": 37.5, "measurement_validated": False, "used_for_grading": False,
    "fish_length_cm": None, "max_body_width_cm": None,
    "physical_calibration": {"validated": False, "status": "Not calibrated"},
}


def test_segmentation_csv_xlsx_preserve_measurements_validation_and_full_evidence():
    event = {"id": 3, "analysis": {"fish_geometry": GEOMETRY}}
    before = deepcopy(event)
    assert set(FIELDS) <= set(DEFAULT_EXPORT_FIELDS)
    row = list(csv.DictReader(StringIO(make_csv([event], FIELDS).decode("utf-8-sig"))))[0]
    assert row[EXPORT_FIELDS["fish_length_px"]] == "280.125"
    assert row[EXPORT_FIELDS["max_body_width_px"]] == "70.0312"
    assert row[EXPORT_FIELDS["relative_fish_body_width_ratio"]] == "0.25"
    assert row[EXPORT_FIELDS["fish_geometry_measurement_validated"]] == "Not validated"
    assert row[EXPORT_FIELDS["fish_geometry_used_for_grading"]] == "No"
    assert row[EXPORT_FIELDS["fish_length_cm"]] == ""
    assert row[EXPORT_FIELDS["physical_calibration_status"]] == "Not calibrated"
    assert json.loads(row[EXPORT_FIELDS["fish_geometry_analysis"]]) == GEOMETRY
    workbook = load_workbook(BytesIO(make_xlsx([event], FIELDS, {})), data_only=True)
    values = list(workbook["Fish Inspections"].values)[1]
    assert values[:3] == (280.125, 70.0312, .25)
    assert values[10:12] == (None, None)
    assert json.loads(values[-1]) == GEOMETRY
    assert event == before


@pytest.mark.parametrize("status,validated,calibration_status,expected", [
    ("measured", True, "Applied", 14.0062),
    ("measured", False, "Not calibrated", ""),
    ("measured", True, "Context mismatch", ""),
    ("unreliable", True, "Applied", ""),
    ("unavailable", True, "Applied", ""),
])
def test_physical_export_requires_reliable_measurement_and_applied_validated_calibration(status, validated, calibration_status, expected):
    geometry = dict(GEOMETRY, status=status, fish_length_cm=14.00625, max_body_width_cm=3.5015625,
                    physical_calibration={"validated": validated, "status": calibration_status})
    geometry["candidate_measurements"] = {"fish_length_px": 999, "max_body_width_px": 888}
    row = inspection_row({"analysis": {"fish_geometry": geometry}})
    assert row["fish_length_cm"] == expected
    assert row["max_body_width_cm"] == (3.5016 if expected != "" else "")
    if status != "measured":
        assert row["fish_length_px"] == row["max_body_width_px"] == row["relative_fish_body_width_ratio"] == ""
    assert json.loads(row["fish_geometry_analysis"])["candidate_measurements"]["fish_length_px"] == 999


def test_all_seven_historical_records_have_no_invented_silhouette_size_and_keep_grades():
    with (ROOT / "tests/fixtures/fish-inspection-upload-all.csv").open(encoding="utf-8-sig", newline="") as source:
        saved = list(csv.DictReader(source))
    events = [json.loads(row["Complete fish event"]) for row in saved]
    metadata = json.loads(saved[0]["Source metadata"])
    before = deepcopy(events)
    assert len(events) == 7
    for event in events:
        row = inspection_row(event, source_metadata=metadata)
        assert row["fish_length_px"] == row["max_body_width_px"] == row["relative_fish_body_width_ratio"] == ""
        clipped = event["id"] in {1, 2, 7}
        assert row["fish_geometry_reliability"] == ("Unreliable" if clipped else "Unavailable")
        assert row["fish_geometry_status"] == ("unreliable" if clipped else "unavailable")
        assert "historical_image_unavailable" in row["fish_geometry_reasons"]
        if clipped:
            assert "parent_touches_frame_boundary" in row["fish_geometry_reasons"]
        assert row["fish_length_cm"] == row["max_body_width_cm"] == ""
        assert row["fish_geometry_used_for_grading"] == "No"
        assert row["original_weighted_grade"] == row["final_combined_grade"] == event["quality"]
        assert json.loads(row["original_weighted_scores"]) == json.loads(row["final_combined_scores"]) == event["analysis"]["weighted_scores"]
    assert events == before


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for browser evidence contracts")
def test_browser_fish_evidence_and_printable_report_show_geometry_without_candidates_or_uncalibrated_cm():
    script = r'''
const fs = require("fs"); const vm = require("vm");
const source = fs.readFileSync("frontend/app.js", "utf8");
const geometry = JSON.parse(fs.readFileSync(0, "utf8"));
function include(name) {
  const start = source.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`Missing ${name}`);
  const next = source.slice(start + 1).search(/\n(?:async )?function /);
  vm.runInThisContext(source.slice(start, next < 0 ? source.length : start + 1 + next));
}
for (const name of ["bodyWidthRows", "resultGrade", "resultValue", "partEvidenceText", "measurementRegion", "measurementRows", "resultEvidenceRows", "finalExplanationRows", "resultIdentity", "recordedResultTimestamp", "flattenResultData", "resultExportRecord", "resultReportHtml"]) include(name);
global.resultsFilter = "All"; global.resultsSource = "upload";
global.resultDatasets = {upload: {scope: "photo", metadata: {source_name: "segmented fish"}}};
global.sessionGradeBuckets = ["Class A", "Class B", "Class C", "Rejected", "Ungraded"];
global.manualGrade = event => event.manual_grade || null;
global.aiFinalGrade = event => event.quality || "Ungraded";
global.verdictReason = () => ({text: ""});
global.effectiveWeightText = () => "Body 50% / Head 30% / Tail 20%";
global.weightedFinalSupport = () => .8;
global.scoreText = value => value == null ? "Not recorded" : `${value * 100}%`;
global.pixelBox = () => null;
const measured = {id: 1, quality: "Class A", analysis: {fish_geometry: geometry}};
const unsafe = structuredClone(measured); unsafe.id = 2;
unsafe.analysis.fish_geometry.status = "unreliable";
unsafe.analysis.fish_geometry.reliability = "Unreliable";
unsafe.analysis.fish_geometry.reasons = ["overlap <fish>"];
unsafe.analysis.fish_geometry.candidate_measurements = {fish_length_px: 999};
unsafe.analysis.fish_geometry.physical_calibration = {validated: true, status: "Applied"};
unsafe.analysis.fish_geometry.fish_length_cm = 99;
unsafe.analysis.fish_geometry.max_body_width_cm = 88;
const physical = structuredClone(measured);
physical.analysis.fish_geometry.physical_calibration = {validated: true, status: "Applied"};
physical.analysis.fish_geometry.fish_length_cm = 14.00625;
physical.analysis.fish_geometry.max_body_width_cm = 3.5015625;
const mismatch = structuredClone(physical); mismatch.analysis.fish_geometry.physical_calibration.status = "Context mismatch";
console.log(JSON.stringify({measured: bodyWidthRows(measured), missing: bodyWidthRows({}), unsafe: bodyWidthRows(unsafe), physical: bodyWidthRows(physical), mismatch: bodyWidthRows(mismatch), csv: resultExportRecord(measured), unsafeCsv: resultExportRecord(unsafe), physicalCsv: resultExportRecord(physical), mismatchCsv: resultExportRecord(mismatch), report: resultReportHtml([measured, unsafe])}));
'''
    result = subprocess.run([shutil.which("node"), "-e", script], input=json.dumps(GEOMETRY), cwd=ROOT,
                            text=True, capture_output=True, check=True)
    rendered = json.loads(result.stdout)
    measured, unsafe, physical = (dict(rendered[name]) for name in ("measured", "unsafe", "physical"))
    assert measured["Measured fish length (px)"] == "280.125"
    assert measured["Maximum body width (px)"] == "70.0313"
    assert measured["Relative body width ratio"] == "0.25"
    assert measured["Measurement validation"].startswith("Not validated")
    assert "Physical length (cm)" not in measured
    assert unsafe["Measured fish length (px)"] == "Unavailable"
    assert "overlap <fish>" in unsafe["Fish measurement reliability"]
    assert "Physical length (cm)" not in unsafe
    assert "Physical length (cm)" not in dict(rendered["mismatch"])
    assert physical["Physical length (cm)"] == "14.0062"
    assert dict(rendered["missing"])["Measured fish length (px)"] == "Unavailable"
    assert rendered["csv"]["Measured fish length (px)"] == GEOMETRY["fish_length_px"]
    assert json.loads(rendered["csv"]["Fish Geometry Analysis"]) == GEOMETRY
    assert rendered["unsafeCsv"]["Measured fish length (px)"] == ""
    assert rendered["unsafeCsv"]["Physical length (cm)"] == rendered["mismatchCsv"]["Physical length (cm)"] == ""
    assert rendered["physicalCsv"]["Physical length (cm)"] == 14.00625
    assert rendered["report"].count("B. Body Width and Geometric Analysis") == 2
    assert rendered["report"].count("Measured fish length (px)") == 2
    assert "overlap &lt;fish&gt;" in rendered["report"]
    assert "999" not in rendered["report"]
    assert "Physical length (cm)" not in rendered["report"]
