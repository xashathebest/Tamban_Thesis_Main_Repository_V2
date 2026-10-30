"""Static contract checks for the Analyze Image per-fish evidence panel."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_upload_result_has_a_dedicated_per_fish_evidence_panel():
    html = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "frontend/app.js").read_text(encoding="utf-8")

    assert 'id="upload-fish-evidence"' in html
    assert "function renderUploadEvidence" in javascript
    assert "renderUploadEvidence(isPartPreview ? [] : payload.fish)" in javascript


def test_upload_evidence_uses_returned_grading_fields_for_parts_weights_and_abstentions():
    javascript = (ROOT / "frontend/app.js").read_text(encoding="utf-8")

    for token in (
        "weightedFinalSupport(fish)",
        "effectiveWeightText(fish)",
        'partFor(fish, region)',
        "part?.effective_weight",
        "verdictReason(fish)",
        "Ungraded reason:",
    ):
        assert token in javascript


def test_upload_evidence_cards_are_native_collapsible_disclosures():
    javascript = (ROOT / "frontend/app.js").read_text(encoding="utf-8")
    stylesheet = (ROOT / "frontend/styles.css").read_text(encoding="utf-8")

    for token in (
        'document.createElement("details")',
        'document.createElement("summary")',
        "card.open = fishList.length === 1",
        "upload-evidence-toggle",
        "upload-evidence-body",
        "Expand evidence",
        "Hide evidence",
    ):
        assert token in javascript
    for token in (
        ".upload-evidence-card > summary",
        ".upload-evidence-card[open]",
        ".upload-evidence-body",
    ):
        assert token in stylesheet


def test_upload_measurements_separate_grading_inputs_from_diagnostic_color_and_pixel_values():
    html = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "frontend/app.js").read_text(encoding="utf-8")

    assert 'id="upload-fish-measurements"' in html
    for token in (
        "function renderUploadMeasurements",
        "renderUploadMeasurements(isPartPreview ? [] : payload.fish)",
        "analysisFor(fish).supporting_image_measurements",
        "pixelBoxText(fish?.bbox)",
        "uploadPartDetection(fish, region)",
        "Used for grade:",
        "Not used for grade:",
        "Not calibrated; pixels only",
        "No fish mask",
    ):
        assert token in javascript
