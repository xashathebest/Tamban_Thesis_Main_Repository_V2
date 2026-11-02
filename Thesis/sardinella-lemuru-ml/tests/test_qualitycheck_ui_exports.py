"""Sampled geometry and nested timing scopes remain explicit in UI and exports."""

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
QUALITY_FIELDS = (
    "estimated_fish_length_px", "estimated_max_body_width_px", "estimated_relative_width_ratio",
    "fish_geometry_sampling", "frame_stage_performance", "inspection_gpu_memory",
    "fish_performance_scope", "frame_performance_scope", "fish_color_processing_ms",
    "fish_texture_processing_ms", "fish_grading_policy_ms", "fish_structural_damage_ms",
    "frame_annotation_rendering_ms", "frame_segmentation_processing_ms", "frame_foreground_grabcut_ms",
    "frame_mask_preprocessing_ms", "frame_mask_cache_lookup_ms", "frame_wall_time_ms",
)
BROWSER_FIELDS = (
    "Estimated fish length (px; sampled mask)", "Estimated maximum body width (px; sampled mask)",
    "Estimated relative body width ratio", "Estimated geometry interpretation", "Geometry sampling and uncertainty",
    "Shared Frame Stage Performance", "Process GPU Memory",
)
SAMPLING = {"mode": "bounded_working_grid", "estimated": True, "native_shape": [1200, 600],
    "working_shape": [600, 300], "scale_to_native": [2., 2.], "mask_reconstruction": "nearest_neighbor",
    "boundary_sampling_footprint_native_px": [2., 2.], "native_boundary_validated": False,
    "uncertainty_interpretation": "Working-grid sampling footprint; not a validated anatomical error bound"}


def event(*, sampled=True, contradictory=False):
    geometry = {"status": "measured" if not sampled or contradictory else "unreliable",
        "reliability": "Estimated pixel geometry" if sampled else "Reliable pixel geometry",
        "measurement_validated": contradictory, "used_for_grading": contradictory,
        "fish_length_px": 281.5, "max_body_width_px": 60.25, "relative_width_ratio": .214,
        "fish_length_cm": 99., "max_body_width_cm": 88.,
        "physical_calibration": {"validated": True, "status": "Applied"},
        "candidate_measurements": {"fish_length_px": 280., "max_body_width_px": 60., "relative_width_ratio": .2143},
        "sampling": deepcopy(SAMPLING) if sampled else {"mode": "native", "estimated": False}}
    return {"id": 1, "quality": "Class B", "quality_confidence": .8, "analysis": {
        "final_grade": "Class B", "final_score": .8, "weighted_scores": {"Class A": .2, "Class B": .8, "Class C": 0, "Rejected": 0},
        "fish_geometry": geometry,
        "supporting_image_measurements": {"texture": {"status": "measured", "foreground_estimated": sampled,
            "mask_metadata": {"sampling": deepcopy(geometry["sampling"])}}},
        "performance": {"scope": "current_fish_observation", "color_processing_ms": 2., "texture_processing_ms": 3.,
            "grading_policy_ms": 1., "grading_engine_ms": 7., "hsv_processing_ms": 6., "structural_damage_ms": 4.,
            "model2_inference_ms": 8., "model2_inference_scope": "shared_full_frame",
            "compute_report": {"device": "cpu", "fp16_enabled": False}},
        "frame_performance": {"scope": "one_original_frame", "timing_scope": "Frame wall time; child stages overlap",
            "total_processing_ms": 30., "segmentation_processing_ms": 10., "foreground_grabcut_ms": 7.,
            "mask_preprocessing_ms": 3., "mask_cache_lookup_ms": .5, "annotation_rendering_ms": 2.,
            "segmentation_backend": "CPU / OpenCV GrabCut", "gpu_memory": {"scope": "process_lifetime", "allocated_bytes": 1048576, "peak_allocated_bytes": 2097152},
            "mask_context": {"segmentation_calls": 2, "cache_hits": 3, "cache_misses": 2, "feature_cache_hits": 1, "projection_fallbacks": 0}},
    }}


@pytest.mark.parametrize("contradictory", [False, True])
def test_backend_sampled_candidates_never_become_native_or_physical_measurements(contradictory):
    specimen = event(contradictory=contradictory)
    original = deepcopy(specimen)
    row = inspection_row(specimen)
    assert row["fish_length_px"] == row["max_body_width_px"] == row["relative_fish_body_width_ratio"] == ""
    assert row["fish_length_cm"] == row["max_body_width_cm"] == ""
    assert row["fish_geometry_measurement_validated"] == "Not validated"
    assert row["fish_geometry_used_for_grading"] == "No"
    assert row["physical_calibration_status"].startswith("Not applied:")
    assert [row[key] for key in QUALITY_FIELDS[:3]] == [280., 60., .2143]
    assert json.loads(row["fish_geometry_sampling"]) == SAMPLING
    assert json.loads(row["frame_stage_performance"]) == specimen["analysis"]["frame_performance"]
    assert row["grade"] == "Class B" and row["final_weighted_score"] == 80.
    assert specimen == original


def test_native_values_and_unrelated_withheld_candidates_keep_their_original_meaning():
    native = event(sampled=False)
    row = inspection_row(native)
    assert row["fish_length_px"] == 281.5 and row["fish_length_cm"] == 99.
    assert all(row[key] == "" for key in QUALITY_FIELDS[:3])
    native["analysis"]["fish_geometry"]["status"] = "unreliable"
    row = inspection_row(native)
    assert row["fish_length_px"] == row["fish_length_cm"] == ""
    assert all(row[key] == "" for key in QUALITY_FIELDS[:3])


@pytest.mark.parametrize("value", [True, "280", 0, -1, None])
def test_estimated_values_require_positive_numeric_pixel_evidence(value):
    specimen = event()
    specimen["analysis"]["fish_geometry"]["candidate_measurements"]["fish_length_px"] = value
    assert inspection_row(specimen)["estimated_fish_length_px"] == ""


def test_appended_backend_fields_roundtrip_without_summing_nested_stages():
    quality_start = DEFAULT_EXPORT_FIELDS.index(QUALITY_FIELDS[0])
    assert DEFAULT_EXPORT_FIELDS[quality_start:quality_start + len(QUALITY_FIELDS)] == QUALITY_FIELDS
    specimen = event()
    csv_row = next(csv.DictReader(StringIO(make_csv([specimen], QUALITY_FIELDS).decode("utf-8-sig"))))
    workbook = load_workbook(BytesIO(make_xlsx([specimen], QUALITY_FIELDS, {})), data_only=True)
    spreadsheet = dict(zip(QUALITY_FIELDS, list(workbook["Fish Inspections"].values)[1]))
    for key in ("frame_stage_performance", "inspection_gpu_memory", "fish_geometry_sampling"):
        assert json.loads(csv_row[EXPORT_FIELDS[key]]) == json.loads(spreadsheet[key])
    assert float(csv_row[EXPORT_FIELDS["frame_wall_time_ms"]]) == 30.
    assert float(csv_row[EXPORT_FIELDS["fish_grading_policy_ms"]]) == 1.
    assert float(csv_row[EXPORT_FIELDS["fish_color_processing_ms"]]) == 2.
    assert float(csv_row[EXPORT_FIELDS["fish_texture_processing_ms"]]) == 3.


NODE = r'''
const fs = require("fs"); const vm = require("vm");
const source = fs.readFileSync("frontend/app.js", "utf8"); const inputs = JSON.parse(fs.readFileSync(0, "utf8"));
function include(name) {
  const declaration = source.indexOf(`function ${name}(`);
  const start = source.slice(declaration - 6, declaration) === "async " ? declaration - 6 : declaration;
  if (declaration < 0) throw new Error(`Missing ${name}`);
  const next = source.slice(start + 1).search(/\n(?:async )?function /);
  vm.runInThisContext(source.slice(start, next < 0 ? source.length : start + 1 + next));
}
for (const name of ["surfaceDamageEvidence", "bodyWidthRows", "inspectionPerformanceRows", "textureEvidenceRows", "flattenResultData", "resultExportRecord", "resultReportHtml", "exportResultsCsv"]) include(name);
global.resultsSource = "upload"; global.resultsFilter = "All";
global.resultDatasets = {upload: {scope: "qualitycheck", metadata: {source_name: "CPU contract fixture", performance: {fps: 30}}}};
global.sessionGradeBuckets = ["Class A", "Class B", "Class C", "Rejected", "Ungraded"];
global.pixelBox = () => null; global.recordedResultTimestamp = () => "2026-11-01T12:00:00-05:00";
global.resultIdentity = e => `fixture:${e.id}`; global.aiFinalGrade = global.resultGrade = e => e.quality || "Ungraded";
global.weightedFinalSupport = e => e.quality_confidence; global.verdictReason = () => ({text: ""});
global.scoreText = value => String(value); global.measurementRegion = () => ({status: "unavailable", reading: {}});
global.resultEvidenceRows = e => [["Grade", e.quality]]; global.finalExplanationRows = e => [["Final", e.quality]];
global.selectedResultEvents = () => inputs; global.hasCompleteInspectionAnalysis = () => true;
let csvText; global.Blob = class {constructor(parts) {csvText = parts.join("");}};
global.URL = {createObjectURL: () => "blob:qualitycheck", revokeObjectURL() {}};
global.document = {createElement: () => ({click() {}})};
(async () => {
  await exportResultsCsv();
  console.log(JSON.stringify({rows: inputs.map(e => ({body: bodyWidthRows(e), timing: inspectionPerformanceRows(e), texture: textureEvidenceRows(e), record: resultExportRecord(e), report: resultReportHtml([e])})), csv: csvText}));
})().catch(error => {console.error(error); process.exitCode=1;});
'''


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for actual UI/export interpretation")
def test_actual_browser_labels_estimates_scopes_and_preserves_append_only_csv_columns():
    inputs = [event(), event(sampled=False), event(contradictory=True)]
    inputs[1]["only_second_record"] = "Late legacy column"
    result = subprocess.run([shutil.which("node"), "-e", NODE], input=json.dumps(inputs), cwd=ROOT,
                            capture_output=True, text=True, check=True)
    actual = json.loads(result.stdout)
    for index in (0, 2):
        shown = actual["rows"][index]
        body = dict(shown["body"])
        assert body["Measured fish length (px)"] == body["Maximum body width (px)"] == "Unavailable"
        assert body["Estimated fish length (px; sampled mask)"] == "280"
        assert body["Estimated maximum body width (px; sampled mask)"] == "60"
        assert "not a validated anatomical error bound" in body["Sampling uncertainty interpretation"]
        assert "Physical length (cm)" not in body
        assert shown["record"]["Measured fish length (px)"] == shown["record"]["Physical length (cm)"] == ""
        assert shown["record"]["Estimated fish length (px; sampled mask)"] == 280.
        assert "<td>Estimated fish length (px; sampled mask)</td><td>280</td>" in shown["report"]
        assert "do not sum nested stages" in shown["report"]
        assert dict(shown["texture"])["Texture analysis"] == "Measured native-pixel texture; foreground support is estimated"
    native = actual["rows"][1]
    assert dict(native["body"])["Measured fish length (px)"] == "281.5"
    assert "Estimated fish length (px; sampled mask)" not in dict(native["body"])
    assert dict(native["texture"])["Texture analysis"] == "Measured diagnostic features"
    timing = dict(actual["rows"][0]["timing"])
    assert timing["Recorded frame-scope wall time"] == "30 ms"
    assert timing["Fish grading policy, excluding features"] == "1 ms"
    assert timing["Fish color extraction"] == "2 ms" and timing["Fish texture extraction"] == "3 ms"
    assert timing["Frame mask-cache hits"] == "3" and timing["Frame segmentation attempts"] == "2"
    assert timing["Recorded process GPU allocation"] == "1 MiB" and timing["GPU memory scope"] == "process_lifetime"
    assert "do not sum nested stages" in timing["Timing interpretation"]
    assert timing["Upload processing speed"].startswith("Unavailable:")
    assert "source/capture FPS is not throughput" in timing["Upload processing speed"]
    csv_rows = list(csv.DictReader(StringIO(actual["csv"].lstrip("\ufeff"))))
    browser_headers = tuple(csv_rows[0])
    quality_start = browser_headers.index(BROWSER_FIELDS[0])
    assert browser_headers[quality_start:quality_start + len(BROWSER_FIELDS)] == BROWSER_FIELDS
    assert list(csv_rows[0]).index("record.only_second_record") < list(csv_rows[0]).index(BROWSER_FIELDS[0])
    assert [row["Final AI grade"] for row in csv_rows] == ["Class B"] * 3
