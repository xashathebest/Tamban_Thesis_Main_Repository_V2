"""Real seven-fish CSV records cross the backend/frontend export boundary."""

import csv
from io import StringIO
import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/fish-inspection-upload-all.csv"


def reproduction():
    with FIXTURE.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    assert len(rows) == 7
    return [json.loads(row["Complete fish event"]) for row in rows], json.loads(rows[0]["Source metadata"])


HARNESS = r'''
const fs = require("fs"); const vm = require("vm");
const source = fs.readFileSync("frontend/app.js", "utf8");
const input = JSON.parse(fs.readFileSync(0, "utf8"));
function include(name) {
  const declaration = source.indexOf(`function ${name}(`);
  if (declaration < 0) throw new Error(`Missing helper: ${name}`);
  const start = source.slice(declaration - 6, declaration) === "async " ? declaration - 6 : declaration;
  const next = source.slice(start + 1).search(/\n(?:async )?function /);
  const end = next < 0 ? source.length : start + 1 + next;
  vm.runInThisContext(source.slice(start, end));
}
for (const name of ["resultGrade", "resultIdentity", "mergeResultEvidence", "uniqueResultEvents",
  "selectedResultEvents", "recordedResultTimestamp", "hasBodyWidthExportEvidence", "hasCompleteInspectionAnalysis",
  "normalizeInspectionFish", "ensureNormalizedResultsForExport", "flattenResultData", "resultExportRecord",
  "exportResultsCsv", "exportResultsPdf"]) include(name);
global.resultsSource = "upload"; global.resultsFilter = "All";
global.sessionGradeBuckets = ["Class A", "Class B", "Class C", "Rejected", "Ungraded"];
global.manualGrade = event => event.manual_grade || null;
global.aiFinalGrade = event => event.analysis?.final_grade || event.quality || "Ungraded";
global.weightedFinalSupport = event => event.analysis?.final_score ?? event.quality_confidence;
global.verdictReason = event => ({text: event.analysis?.verdict_reason_text || ""});
global.elements = {resultsSummary: {textContent: ""}, uploadStatus: {textContent: ""}};
let csvText = ""; let blobCount = 0; let closed = 0; let calls = [];
global.Blob = class {constructor(parts) {blobCount++; csvText = parts.join("");}};
global.URL = {createObjectURL: () => "blob:test", revokeObjectURL() {}};
global.document = {createElement: () => ({click() {}})};
global.window = {open: () => ({document: {write() {}, close() {}}, focus() {}, close() {closed++;}, print() {}})};
global.setTimeout = () => 0;
global.resultDatasets = {upload: {scope: "actual-seven-fish", rows: input.raw, metadata: input.metadata}};
global.resultsEvents = input.raw;
global.renderResultsDashboard = (fish, options) => {
  resultDatasets[options.source].rows = fish;
  resultDatasets[options.source].metadata = options.metadata;
  resultsEvents = fish;
};
'''


def node_case(script, value):
    if shutil.which("node") is None:
        pytest.skip("Node.js is required for structured frontend export tests")
    result = subprocess.run([shutil.which("node"), "-e", HARNESS + script], input=json.dumps(value),
                            cwd=ROOT, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_all_seven_records_are_normalized_once_and_csv_preserves_recorded_results_and_dates():
    from src.inference.body_width import BodyWidthConfig
    from src.inference.inspection_results import normalize_inspection_results

    raw, metadata = reproduction()
    normalized = normalize_inspection_results(raw, source_metadata=metadata, body_width_config=BodyWidthConfig())
    result = node_case(r'''
(async () => {
  global.fetch = async (url, options) => {
    const body = JSON.parse(options.body); calls.push({url, fishCount: body.fish.length, analyzed_at: body.source_metadata.analyzed_at});
    return {ok: true, json: async () => ({fish: input.normalized, results_schema_version: "body_width_v3"})};
  };
  const fish = await normalizeInspectionFish(input.raw, input.metadata);
  resultDatasets.upload.rows = fish; resultsEvents = fish;
  await normalizeInspectionFish(fish, input.metadata);
  await exportResultsCsv();
  const noTimestamp = {...fish[0]}; delete noTimestamp.timestamp;
  console.log(JSON.stringify({csv: csvText, calls, groups: Object.fromEntries(sessionGradeBuckets.map(grade =>
    [grade, fish.filter(event => resultGrade(event) === grade).length])), fallback: resultExportRecord(noTimestamp).Timestamp,
    noFabricatedDate: recordedResultTimestamp({}, {}), analysisDate: recordedResultTimestamp({analysis: {analyzed_at: input.metadata.analyzed_at}}, {})}));
})().catch(error => {console.error(error); process.exitCode=1;});
''', {"raw": raw, "metadata": metadata, "normalized": normalized})
    assert result["calls"] == [{"url": "/api/inspection-results/normalize", "fishCount": 7,
                                  "analyzed_at": metadata["analyzed_at"]}]
    assert result["groups"] == {"Class A": 0, "Class B": 2, "Class C": 0, "Rejected": 0, "Ungraded": 5}
    assert result["fallback"] == result["analysisDate"] == metadata["analyzed_at"]
    assert result["noFabricatedDate"] == ""
    rows = list(csv.DictReader(StringIO(result["csv"].lstrip("\ufeff"))))
    assert len(rows) == 7
    expected_proxies = {1: .386, 2: .481, 3: .265, 5: .302}
    for original, row in zip(raw, rows):
        assert row["Timestamp"] == metadata["analyzed_at"]
        assert row["Original weighted grade"] == row["Final AI grade"] == row["Final classification"] == original["quality"]
        assert row["Width changed classification"] == "false"
        assert row["Class C width points (0-10)"] == "Not calibrated"
        assert row["Calibration status"].lower() == "not calibrated"
        assert float(row["Geometric score contribution"]) == 0
        assert row["Width score contributed"] == "false"
        assert json.loads(row["Body Width Threshold Configuration"])["calibration_validated"] is False
        saved = json.loads(row["Complete fish event"])
        assert saved["timestamp"] == metadata["analyzed_at"]
        assert saved["analysis"]["weighted_scores"] == original["analysis"]["weighted_scores"]
        width = json.loads(row["Body Width Analysis"])
        if original["id"] in expected_proxies:
            assert width["relative_width_proxy"] == pytest.approx(expected_proxies[original["id"]], abs=.001)
        else:
            assert width["measurement_status"] == "Missing Detection"
            assert width["relative_width_proxy"] is None


def test_old_backend_cannot_silently_export_empty_width_objects_or_invent_a_timestamp():
    raw, metadata = reproduction()
    result = node_case(r'''
(async () => {
  global.fetch = async (url) => {calls.push(url); return {ok:false,status:404,json:async()=>({detail:"Not Found"})};};
  await exportResultsCsv(); await exportResultsPdf();
  console.log(JSON.stringify({blobCount, csv:csvText, closed, calls, message:elements.resultsSummary.textContent,
    uploadMessage:elements.uploadStatus.textContent}));
})().catch(error => {console.error(error); process.exitCode=1;});
''', {"raw": raw, "metadata": metadata})
    assert result["blobCount"] == 0
    assert result["csv"] == ""
    assert result["closed"] == 1
    assert result["calls"] == ["/api/inspection-results/normalize"] * 2
    assert "Restart the backend" in result["message"]
    assert result["uploadMessage"] == result["message"]


def test_partial_normalization_response_is_rejected_instead_of_dropping_a_fish():
    raw, metadata = reproduction()
    result = node_case(r'''
(async () => {
  global.fetch = async () => ({ok:true,json:async()=>({fish:input.raw.slice(0,6)})});
  try {await normalizeInspectionFish(input.raw,input.metadata); throw new Error("Incomplete data accepted");}
  catch (error) {console.log(JSON.stringify({message:error.message}));}
})().catch(error => {console.error(error); process.exitCode=1;});
''', {"raw": raw, "metadata": metadata})
    assert "normalization response is incomplete" in result["message"]


def test_slow_normalization_cannot_replace_newer_same_source_fish_evidence():
    from src.inference.inspection_results import normalize_inspection_results

    raw, metadata = reproduction()
    normalized = normalize_inspection_results(raw, source_metadata=metadata)
    result = node_case(r'''
(async () => {
  const newer = input.raw.map(event => ({...event, newer_evidence: true}));
  global.fetch = async () => {
    resultDatasets.upload.rows = newer;
    resultsEvents = newer;
    return {ok:true,json:async()=>({fish:input.normalized})};
  };
  const ready = await ensureNormalizedResultsForExport();
  console.log(JSON.stringify({ready,preserved:resultsEvents===newer && resultDatasets.upload.rows===newer}));
})().catch(error => {console.error(error); process.exitCode=1;});
''', {"raw": raw, "metadata": metadata, "normalized": normalized})
    assert result == {"ready": False, "preserved": True}
