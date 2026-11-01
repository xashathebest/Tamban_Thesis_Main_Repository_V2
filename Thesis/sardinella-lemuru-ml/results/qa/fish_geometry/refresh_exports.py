"""Refresh seven-fish QA exports from saved records, without images or models.

Run with the repository's Python and Node.js available. The browser CSV is made
by the actual frontend exporter in an isolated Node context with inert download
objects. This script does not launch the application or update PDF artifacts.
"""

from __future__ import annotations

import ast
from collections import Counter
from copy import deepcopy
import csv
import hashlib
from io import StringIO
import json
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from src.api.export import DEFAULT_EXPORT_FIELDS, make_csv
from src.inference.inspection_results import normalize_inspection_results


FRONTEND_EXPORT = r'''
const fs = require("fs"); const vm = require("vm");
const source = fs.readFileSync("frontend/app.js", "utf8");
const input = JSON.parse(fs.readFileSync(0, "utf8"));
function include(name) {
  const declaration = source.indexOf(`function ${name}(`);
  if (declaration < 0) throw new Error(`Missing frontend helper: ${name}`);
  const start = source.slice(declaration - 6, declaration) === "async " ? declaration - 6 : declaration;
  const next = source.slice(start + 1).search(/\n(?:async )?function /);
  vm.runInThisContext(source.slice(start, next < 0 ? source.length : start + 1 + next));
}
for (const name of ["analysisFor", "eventValue", "aiFinalGrade", "manualGrade", "verdictReason",
  "weightedFinalSupport", "resultGrade", "resultIdentity", "mergeResultEvidence", "uniqueResultEvents",
  "selectedResultEvents", "recordedResultTimestamp", "hasBodyWidthExportEvidence", "hasCompleteInspectionAnalysis",
  "flattenResultData", "resultExportRecord", "exportResultsCsv"]) include(name);
global.resultsSource = "upload"; global.resultsFilter = "All";
global.sessionGradeBuckets = ["Class A", "Class B", "Class C", "Rejected", "Ungraded"];
global.resultDatasets = {upload: {scope: "upload:1", metadata: input.metadata}};
global.resultsEvents = input.fish;
let captured = "";
global.Blob = class { constructor(parts) { captured = parts.join(""); } };
global.URL = {createObjectURL: () => "blob:isolated-export", revokeObjectURL() {}};
global.document = {createElement: () => ({click() {}})};
(async () => {
  await exportResultsCsv();
  if (!captured.startsWith("\ufeff") || !captured.includes("Fish Geometry Analysis")) throw new Error("Incomplete frontend export");
  process.stdout.write(captured);
})().catch(error => { process.stderr.write(String(error)); process.exitCode = 1; });
'''


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def rows(encoded: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(StringIO(encoded.decode("utf-8-sig"))))


def schema_version() -> str:
    """Read the API constant without importing the application's model layer."""
    module = ast.parse((ROOT / "src/api/image_analysis.py").read_text(encoding="utf-8"))
    for node in module.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "RESULTS_SCHEMA_VERSION" for target in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("The API result schema version was not found")


def main() -> None:
    fixture = ROOT / "tests/fixtures/fish-inspection-upload-all.csv"
    saved_rows = rows(fixture.read_bytes())
    original = [json.loads(row["Complete fish event"]) for row in saved_rows]
    metadata = json.loads(saved_rows[0]["Source metadata"])
    snapshot = deepcopy(original)
    normalized = normalize_inspection_results(original, source_metadata=metadata)
    assert original == snapshot
    assert len(original) == len(normalized) == 7
    assert [event["id"] for event in normalized] == list(range(1, 8))
    for before, after in zip(original, normalized):
        for key, value in before.items():
            if key != "analysis":
                assert after[key] == value, (before["id"], key)
        for key, value in before["analysis"].items():
            if key == "grading_config":
                assert all(after["analysis"][key][name] == setting for name, setting in value.items())
            else:
                assert after["analysis"][key] == value, (before["id"], key)
        assert not any(key.startswith("_result_") for key in after)
        assert after["timestamp"] == metadata["analyzed_at"]
        pixel = after["analysis"]["fish_geometry"]
        assert all(pixel[key] is None for key in ("fish_length_px", "max_body_width_px", "relative_width_ratio", "fish_length_cm", "max_body_width_cm"))
        assert pixel["measurement_validated"] is pixel["used_for_grading"] is False
        assert pixel["physical_calibration"]["validated"] is False
        assert "historical_image_unavailable" in pixel["reasons"]
        assert pixel["reliability"] == ("Unreliable" if before["id"] in {1, 2, 7} else "Unavailable")
        support = after["analysis"]["geometric_support"]
        assert support["original_grade"] == support["final_grade"] == before["quality"]
        assert support["original_scores"] == support["final_scores"] == before["analysis"]["weighted_scores"]
        assert support["applied_score_shift"] == 0 and support["width_changed_classification"] is False
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js is required to reuse the actual browser exporter")
    browser_csv = subprocess.run([node, "-e", FRONTEND_EXPORT], cwd=ROOT,
        input=json.dumps({"fish": normalized, "metadata": metadata}).encode("utf-8"),
        capture_output=True, check=True).stdout
    browser_rows = rows(browser_csv)
    assert len(browser_rows) == 7
    assert set(saved_rows[0]) <= set(browser_rows[0])
    for saved, rendered, event in zip(saved_rows, browser_rows, normalized):
        assert saved["Unique identity"] == rendered["Unique identity"]
        assert rendered["Timestamp"] == metadata["analyzed_at"]
        assert rendered["Final AI grade"] == rendered["Final classification"] == event["quality"]
        assert json.loads(rendered["Complete fish event"]) == event
        assert json.loads(rendered["Fish Geometry Analysis"]) == event["analysis"]["fish_geometry"]
        assert rendered["Measured fish length (px)"] == rendered["Maximum body width (px)"] == rendered["Physical length (cm)"] == ""
        assert json.loads(rendered["Body Width Analysis"])
    server_csv = make_csv(normalized, DEFAULT_EXPORT_FIELDS, source_metadata=metadata)
    server_rows = rows(server_csv)
    assert len(server_rows) == 7
    assert all(json.loads(row["Fish Geometry Analysis (JSON)"])["used_for_grading"] is False for row in server_rows)
    output = ROOT / "results/qa/body_width"
    json_payload = {"fish": normalized, "source_metadata": metadata, "results_schema_version": schema_version()}
    artifacts = {
        "fish-inspection-upload-all.repaired.csv": browser_csv,
        "fish-inspection-upload-all.repaired.full-evidence.csv": server_csv,
        "fish-inspection-upload-all.repaired.json": (json.dumps(json_payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"),
    }
    audit_path = output / "upload_csv_width_audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    audit["fish_geometry_artifact_refresh"] = {
        "script": str(Path(__file__).resolve().relative_to(ROOT)).replace("\\", "/"),
        "source": str(fixture.relative_to(ROOT)).replace("\\", "/"),
        "input_sha256": sha256(fixture.read_bytes()),
        "frontend_source_sha256": sha256((ROOT / "frontend/app.js").read_bytes()),
        "server_export_source_sha256": sha256((ROOT / "src/api/export.py").read_bytes()),
        "record_count": 7,
        "browser_csv_column_count": len(browser_rows[0]),
        "server_csv_column_count": len(server_rows[0]),
        "original_csv_columns_preserved": len(saved_rows[0]),
        "source_scope": "upload:1",
        "recorded_timestamp": metadata["analyzed_at"],
        "final_grade_counts": dict(Counter(event["quality"] for event in normalized)),
        "original_fields_preserved": True,
        "all_original_scores_preserved": True,
        "identities_preserved": True,
        "models_invoked": False,
        "anatomical_measurements_validated": False,
        "physical_calibration_enabled": False,
        "silhouette_used_for_grading": False,
        "actual_frontend_exporter_used": True,
        "pdf_updated_by_this_script": False,
        "historical_fish": [{"fish_id": event["id"], "status": event["analysis"]["fish_geometry"]["status"],
            "reliability": event["analysis"]["fish_geometry"]["reliability"], "reasons": event["analysis"]["fish_geometry"]["reasons"]}
            for event in normalized],
        "artifact_sha256": {name: sha256(content) for name, content in artifacts.items()},
    }
    artifacts[audit_path.name] = (json.dumps(audit, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    for name, content in artifacts.items():
        (output / name).write_bytes(content)
    print(json.dumps({"rows": 7, "browser_columns": len(browser_rows[0]), "server_columns": len(server_rows[0]),
        "original_columns_preserved": len(saved_rows[0]), "all_preservation_checks_passed": True,
        "sha256": {name: sha256(content) for name, content in artifacts.items()}}, indent=2))


if __name__ == "__main__":
    main()
