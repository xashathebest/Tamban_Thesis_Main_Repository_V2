"""Structural contracts for the shared, lazy per-fish results workspace.

Actual grouping, updates, mobile layout and exports are exercised by
body_width_browser_smoke.py using real headless Chrome.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_upload_and_live_results_share_one_workspace_without_external_measurements():
    html = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
    script = (ROOT / "frontend/app.js").read_text(encoding="utf-8")
    assert html.count('id="results-groups"') == 1
    assert 'id="results-source"' in html
    assert 'id="upload-fish-evidence"' not in html
    assert 'id="upload-fish-measurements"' not in html
    assert "renderUploadEvidence" not in script
    assert "renderUploadMeasurements" not in script
    assert "elements.uploadResults.append(elements.resultsDashboard)" in script
    assert "resultsHomeAnchor.after(elements.resultsDashboard)" in script


def test_each_lazy_fish_card_contains_the_four_required_evidence_sections():
    script = (ROOT / "frontend/app.js").read_text(encoding="utf-8")
    for section in ("A. Grading Evidence", "B. Body Width and Geometric Analysis",
                    "C. Image Features and Measurements", "D. Final Grading Explanation"):
        assert section in script
    assert 'details.className = "result-fish-card"' in script
    assert "if (!details.open || built) return" in script
    assert "Math.min(rendered + 50, groupRows.length)" in script


def test_reports_use_structured_evidence_instead_of_expanded_dom():
    script = (ROOT / "frontend/app.js").read_text(encoding="utf-8")
    start = script.index("function selectedResultEvents(")
    end = script.index("function manualChoiceForDisplay(", start)
    exporters = script[start:end]
    assert "selectedResultEvents().map(resultExportRecord)" in exporters
    assert '"Complete fish event": JSON.stringify(event)' in exporters
    assert 'flattenResultData(event, "record")' in exporters
    assert "document.querySelector" not in exporters
    assert "table-header-group" in exporters
    assert "counter(page)" in exporters


def test_measurement_status_and_all_color_proxies_are_kept_distinct_from_scores():
    script = (ROOT / "frontend/app.js").read_text(encoding="utf-8")
    for value in ("measurement_status", "calibration_status", "Not Detected", "normal_reference_range",
                  "mean_hue_deg", "mean_saturation", "mean_value", "yellow_ratio_proxy", "brown_ratio_proxy",
                  "dark_patch_ratio_proxy", "discoloration_coverage_proxy", "specular_ratio_proxy"):
        assert value in script
    assert "Unreliable measurements remain visible" in script
    assert "support is not measured accuracy" in script
    assert "geometric support cannot bypass missing evidence" in script
