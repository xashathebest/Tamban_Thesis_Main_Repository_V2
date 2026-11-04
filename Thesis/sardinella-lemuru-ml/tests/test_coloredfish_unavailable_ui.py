"""Enabled overlays explain absent real evidence beside their controls."""
import pytest

from test_coloredfish_ui import specimen
from test_sam_preview_ui import HARNESS, INCLUDE, node


FEEDBACK = INCLUDE + HARNESS + r'''
for(const name of ["overlayPreviewFeedback","renderMaskOverlayFeedback"])include(name);
elements.maskPreviewOverlayStatus=new Element();
elements.maskPreviewMeasurements=new Element();elements.maskPreviewMeasurements.checked=false;
elements.maskPreviewCracks=new Element();elements.maskPreviewCracks.checked=false;
'''


def unavailable_specimen():
    value = specimen()
    geometry = value["fish"][0]["analysis"]["fish_geometry"]
    # Actual older completed analyses can contain numeric diagnostics but no
    # endpoints. A shaded mask and a checked control cannot locate those values.
    geometry.pop("candidate_visualization")
    geometry["reasons"] = ["experimental_mask_requires_ownership_validation", "parent_association_uncertain"]
    value["fish"][0]["analysis"]["surface_damage"] = {
        "status": "unavailable", "coordinate_space": "crop_local_native_pixels",
        "frame_id": "native-source", "parent_track_id": 1, "crop_bounds": [15, 30, 235, 120],
        "locations": [], "used_for_grading": False,
        "reason": "A reviewed, correctly owned Body pixel mask is unavailable; MobileSAM candidates do not establish Body anatomy.",
    }
    return value


def feedback(value, *, measurements=False, cracks=False):
    return node(FEEDBACK + r'''
const input=JSON.parse(fs.readFileSync(0,"utf8")),before=JSON.stringify(input.value);
elements.maskPreviewMeasurements.checked=input.measurements;elements.maskPreviewCracks.checked=input.cracks;
const entries=maskPreviewEntries(input.value),frame=maskPreviewSource(input.value);
renderMaskOverlayFeedback(entries,frame);
console.log(JSON.stringify({message:overlayPreviewFeedback(entries,frame),text:elements.maskPreviewOverlayStatus.textContent,
 hidden:elements.maskPreviewOverlayStatus.hidden,unchanged:before===JSON.stringify(input.value)}));
''', {"value": value, "measurements": measurements, "cracks": cracks})


def test_enabled_measurements_explain_numeric_diagnostics_without_drawable_endpoints():
    actual = feedback(unavailable_specimen(), measurements=True)
    text = actual["text"].lower()
    assert not actual["hidden"] and actual["unchanged"]
    assert "measurements" in text and "unavailable" in text
    assert "endpoints" in text and "ownership" in text


def test_enabled_cracks_explain_unavailable_body_support_at_the_controls():
    actual = feedback(unavailable_specimen(), cracks=True)
    text = actual["text"].lower()
    assert not actual["hidden"] and actual["unchanged"]
    assert "cracks" in text and "unavailable" in text
    assert "body" in text and "mobilesam" in text
    assert "no cracks" not in text


def test_both_enabled_overlays_report_each_unavailable_reason_without_reanalysis():
    actual = feedback(unavailable_specimen(), measurements=True, cracks=True)
    text = actual["text"].lower()
    assert "measurements" in text and "cracks" in text
    assert "endpoints" in text and "body" in text
    assert actual["unchanged"]


def test_disabled_overlays_clear_immediate_feedback():
    actual = feedback(unavailable_specimen())
    assert actual["hidden"] and not actual["text"]


def test_available_evidence_reports_visible_axes_and_candidate_count():
    actual = feedback(specimen(), measurements=True, cracks=True)
    text = actual["text"].lower()
    assert "measurements" in text and "cracks" in text
    assert "3" in text and "1" in text
    assert "estimated" in text
    assert actual["unchanged"]


@pytest.mark.parametrize("measurements,cracks", [(True, False), (False, True), (True, True)])
def test_pending_source_still_explains_enabled_overlays(measurements, cracks):
    actual = node(FEEDBACK + r'''
const input=JSON.parse(fs.readFileSync(0,"utf8"));
elements.maskPreviewMeasurements.checked=input.measurements;elements.maskPreviewCracks.checked=input.cracks;
renderMaskOverlayFeedback([],null);
console.log(JSON.stringify({text:elements.maskPreviewOverlayStatus.textContent,hidden:elements.maskPreviewOverlayStatus.hidden}));
''', {"measurements": measurements, "cracks": cracks})
    assert not actual["hidden"]
    assert "unavailable" in actual["text"].lower() or "ready" in actual["text"].lower()
