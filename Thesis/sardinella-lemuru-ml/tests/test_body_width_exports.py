"""Width evidence remains explicit and reconstructable in fish reports."""

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
WIDTH = {
    "status": "measured",
    "whole_fish_width_px": 200.125,
    "whole_fish_height_px": 50.5,
    "body_width_px": 110.25,
    "body_height_px": 40.25,
    "relative_width_proxy": 0.2011243,
    "initial_relative_width_proxy": 0.2011243,
    "reliability": "Reliable proxy",
    "reliability_reasons": [],
    "normal_reference_range": None,
    "width_abnormality": "Not calibrated",
    "score_status": "Not calibrated",
    "class_c_supporting_points": None,
    "scoring_enabled": False,
    "score_contributed": False,
    "applied_body_score_shift": 0.0,
    "contribution_reason": "Scoring disabled until validation",
    "threshold_configuration": {"scoring_enabled": False, "normal_max": None},
}


def test_width_csv_and_xlsx_preserve_pixels_reliability_and_uncalibrated_state():
    event = {"track_id": 7, "analysis": {"body_width": WIDTH}}
    fields = ["whole_fish_bbox_width_px", "body_bbox_height_px", "relative_body_width_proxy",
              "body_width_reliability", "body_width_score_status", "body_width_class_c_points",
              "body_width_score_contributed", "body_width_threshold_configuration", "body_width_analysis"]
    assert set(fields) <= set(DEFAULT_EXPORT_FIELDS)
    rows = list(csv.DictReader(StringIO(make_csv([event], fields).decode("utf-8-sig"))))
    row = rows[0]
    assert row[EXPORT_FIELDS["whole_fish_bbox_width_px"]] == "200.125"
    assert row[EXPORT_FIELDS["body_bbox_height_px"]] == "40.25"
    assert row[EXPORT_FIELDS["body_width_reliability"]] == "Reliable proxy"
    assert row[EXPORT_FIELDS["body_width_score_status"]] == "Not calibrated"
    assert row[EXPORT_FIELDS["body_width_class_c_points"]] == ""
    assert row[EXPORT_FIELDS["body_width_score_contributed"]] == "No"
    assert json.loads(row[EXPORT_FIELDS["body_width_analysis"]]) == WIDTH
    workbook = load_workbook(BytesIO(make_xlsx([event], fields, {})), data_only=True)
    values = list(workbook["Fish Inspections"].values)[1]
    assert values[:2] == (200.125, 40.25)
    assert values[5:7] == (None, "No")
    assert json.loads(values[-2]) == WIDTH["threshold_configuration"]
    assert json.loads(values[-1])["relative_width_proxy"] == WIDTH["relative_width_proxy"]


def test_unavailable_historical_width_is_not_reported_as_normal_or_zero_points():
    row = inspection_row({"analysis": {}})
    assert row["relative_body_width_proxy"] == ""
    assert row["body_width_class_c_points"] == ""
    assert row["body_width_reliability"] == "Unavailable"
    assert row["body_width_abnormality"] == "Unavailable"
    assert row["body_width_score_contributed"] == "Unavailable"
    measured = dict(WIDTH, class_c_supporting_points=0.0, score_status="Calibrated",
                    normal_reference_range=[0.1, 0.25], width_abnormality="Normal")
    assert inspection_row({"analysis": {"body_width": measured}})["body_width_class_c_points"] == 0.0


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for frontend report checks")
def test_browser_width_display_and_pdf_csv_reports_use_saved_evidence():
    script = r'''
const fs = require("fs"); const vm = require("vm");
const source = fs.readFileSync("frontend/app.js", "utf8");
function include(name) {
  const start = source.indexOf(`function ${name}(`);
  const end = source.indexOf("\nfunction ", start + 1);
  vm.runInThisContext(source.slice(start, end < 0 ? source.length : end));
}
for (const name of ["bodyWidthRows", "resultGrade", "resultValue", "partEvidenceText", "measurementRegion", "measurementRows", "resultEvidenceRows", "finalExplanationRows", "resultIdentity", "mergeResultEvidence", "uniqueResultEvents", "selectedResultEvents", "flattenResultData", "resultExportRecord", "exportResultsCsv", "resultReportHtml", "exportResultsPdf"]) include(name);
const width = JSON.parse(process.argv[1]);
width.reliability_reasons = ["manually checked <fish>"];
width.threshold_configuration.calibration_id = "review <script>";
global.resultsFilter = "All"; global.resultsSource = "upload";
global.resultDatasets = {upload: {scope: "photo", metadata: {source_name: "test photo"}}};
global.resultsEvents = [{id: 7, quality: "Class A", analysis: {body_width: width}}];
global.sessionGradeBuckets = ["Class A", "Class B", "Class C", "Rejected", "Ungraded"];
global.manualGrade = event => event.manual_grade || null;
global.aiFinalGrade = event => event.quality || "Ungraded";
global.verdictReason = () => ({text: ""});
global.effectiveWeightText = () => "Body 50% / Head 30% / Tail 20%";
global.weightedFinalSupport = () => 0.8;
global.scoreText = value => value == null ? "Not recorded" : `${value * 100}%`;
global.pixelBox = () => null;
let report = ""; let csv = "";
global.window = {open: () => ({document: {write: value => {report = value;}, close() {}}, focus() {}, print() {}})};
global.document = {createElement: () => ({click() {}})};
global.Blob = class {constructor(parts) {csv = parts.join("");}};
global.URL = {createObjectURL: () => "blob:test", revokeObjectURL() {}};
global.setTimeout = () => 0;
exportResultsCsv(); exportResultsPdf();
console.log(JSON.stringify({rows: bodyWidthRows(resultsEvents[0]), missing: bodyWidthRows({}), report, csv}));
'''
    result = subprocess.run([shutil.which("node"), "-e", script, json.dumps(WIDTH)], cwd=ROOT,
                            text=True, capture_output=True, check=True)
    rendered = json.loads(result.stdout)
    values = dict(rendered["rows"])
    assert values["Whole-fish bounding box"] == "200.125 x 50.5 px"
    assert values["Class C supporting points"] == "Not calibrated"
    assert values["Contributed to final grade"].startswith("No:")
    assert dict(rendered["missing"])["Relative width proxy"] == "Unavailable"
    assert "B. Body Width and Geometric Analysis" in rendered["report"]
    assert "manually checked &lt;fish&gt;" in rendered["report"]
    assert "review &lt;script&gt;" in rendered["report"]
    assert "<script>" not in rendered["report"]
    csv_rows = list(csv.DictReader(StringIO(rendered["csv"].lstrip("\ufeff"))))
    saved = json.loads(csv_rows[0]["Body Width Analysis"])
    assert saved["relative_width_proxy"] == WIDTH["relative_width_proxy"]
    assert saved["score_contributed"] is False
    assert "Body Width Threshold Configuration" in csv_rows[0]
    assert "Complete structured evidence" not in rendered["report"]
