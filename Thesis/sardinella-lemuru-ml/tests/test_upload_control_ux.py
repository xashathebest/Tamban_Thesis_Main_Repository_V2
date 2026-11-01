"""Static UX contracts for the Analyze Media control flow."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_upload_launcher_and_picker_have_distinct_clear_actions():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    assert 'id="upload-mode-button"' in html
    assert 'aria-controls="upload-workspace"' in html
    assert 'aria-expanded="false"' in html
    assert '>Analyze Media</button>' in html
    assert 'role="dialog"' in html
    assert 'class="upload-workspace upload-modal surface hidden"' in html
    assert 'id="select-upload-button"' in html
    assert '>Choose media</button>' in html
    assert 'id="upload-file-name"' in html
    assert '>Run analysis</button>' in html
    assert 'id="upload-status" role="status" aria-live="polite"' in html


def test_live_view_exposes_a_webcam_switch_action():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert 'id="webcam-button"' in html
    assert '>Use webcam</button>' in html
    assert 'elements.webcam.addEventListener("click"' in javascript
    assert 'postControl("/api/inspection/start")' in javascript


def test_upload_flow_focuses_the_picker_and_guards_selection_during_analysis():
    javascript = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    for token in (
        "uploadSelectionVersion",
        "uploadRequestVersion",
        "function updateUploadControls()",
        "elements.shell.inert = anyOpen && !uploadOpen",
        "elements.selectUpload.disabled = uploadInFlight",
        "elements.uploadProgress.classList.toggle(\"hidden\", !uploadInFlight)",
        "elements.analyze.classList.add(\"is-analyzing\")",
        'elements.uploadWorkspace.setAttribute("aria-busy", String(uploadInFlight))',
        "requestAnimationFrame(() => elements.selectUpload.focus({ preventScroll: true }))",
        "const upload = selectedUpload;",
        "if (requestVersion !== uploadRequestVersion || upload !== selectedUpload) return;",
        "elements.analyze.textContent = \"Run analysis\"",
        "revokeUploadPreview()",
    ):
        assert token in javascript


def test_latest_feature_panel_reports_supported_brightness_and_unavailable_cracks():
    javascript = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert '["Brightness", brightness == null ? "Not measured" : `${scoreText(brightness)} (HSV value)`' in javascript
    assert '["Cracks", "Not measured", "unmeasured"]' in javascript
