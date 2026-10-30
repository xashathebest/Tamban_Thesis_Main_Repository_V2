"""Static UX contracts for the Analyze-a-photo control flow."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_upload_launcher_and_picker_have_distinct_clear_actions():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    assert 'id="upload-mode-button"' in html
    assert 'aria-controls="upload-workspace"' in html
    assert 'aria-expanded="false"' in html
    assert '>Analyze a photo</button>' in html
    assert 'id="select-upload-button"' in html
    assert '>Choose photo</button>' in html
    assert 'id="upload-file-name"' in html
    assert '>Run analysis</button>' in html
    assert 'id="upload-status" role="status" aria-live="polite"' in html


def test_upload_flow_focuses_the_picker_and_guards_selection_during_analysis():
    javascript = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    for token in (
        "uploadSelectionVersion",
        "uploadRequestVersion",
        "function updateUploadControls()",
        "elements.selectUpload.disabled = uploadInFlight",
        'elements.uploadWorkspace.setAttribute("aria-busy", String(uploadInFlight))',
        "requestAnimationFrame(() => elements.selectUpload.focus({ preventScroll: true }))",
        "const upload = selectedUpload;",
        "if (requestVersion !== uploadRequestVersion || upload !== selectedUpload) return;",
        "elements.analyze.textContent = \"Analyzing...\"",
        "revokeUploadPreview()",
    ):
        assert token in javascript
