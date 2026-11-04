"""Roundtrip actual computed native geometry through the browser viewer helpers."""

from copy import deepcopy

import numpy as np
import pytest

from src.inference.fish_geometry import measure_fish_geometry
from src.inference.frame_diagnostics import parent_damage
from src.inference.preprocessing import CropBounds, RuntimeMaskContext
from test_coloredfish_geometry_backend import geometry_case, line_scene
from test_sam_preview_ui import INCLUDE, node


ROUNDTRIP = INCLUDE + r'''
for(const name of ["inspectionEvidenceScope","measurementOverlayEvidence","crackOverlayEvidence"])include(name);
const value=JSON.parse(fs.readFileSync(0,"utf8")), before=JSON.stringify(value);
const entry=maskPreviewEntries(value)[0], native=maskPreviewSource(value);
console.log(JSON.stringify({geometry:measurementOverlayEvidence(entry,native),
  cracks:crackOverlayEvidence(entry,native), entry, unchanged:before===JSON.stringify(value)}));
'''


def viewer_payload(geometry, *, display_id=7, damage=None):
    visual = geometry.get("visualization") or geometry["candidate_visualization"]
    fish = {"id": display_id, "bbox": [118, 82, 328, 292], "parts": [],
            "analysis": {"fish_geometry": deepcopy(geometry), "surface_damage": damage or {}},
            "segmentation": {"backend": "mobilesam_experimental", "preview_usable": True,
                             "parent_track_id": display_id, "ownership_status": "checks_passed_unvalidated",
                             "engineering_checks_passed": True,
                             "mask_overlay": {"coordinate_space": "original_frame", "frame_id": "recorded-frame-8",
                                              "frame_width_px": 500, "frame_height_px": 450,
                                              "contours": [visual["silhouette_boundary"]]}}}
    source = {"frame_id": "recorded-frame-8", "frame_width_px": 500, "frame_height_px": 450}
    if display_id != 7:
        source["fish_id_mapping"] = {7: display_id}
        fish["source_parent_id"] = 7
        fish["segmentation"]["source_detection_id"] = 7
    return {"source": source, "fish": [fish]}


@pytest.mark.parametrize("mode", ["mobilesam_estimate", "unreviewed_measurement", "reviewed_measurement"])
@pytest.mark.parametrize("display_id", [7, 3], ids=["native-parent", "remapped-video-track"])
def test_computed_rotated_geometry_draws_three_source_bound_browser_lines(mode, display_id):
    mask, parts, kwargs = geometry_case(30, estimated=mode == "mobilesam_estimate")
    if mode == "reviewed_measurement":
        # A real native Body support region inside the rotated fish fixture.
        body = np.zeros_like(mask, dtype=bool)
        body[112:129, 105:136] = True
        kwargs["mask_metadata"].update(measurement_validated=True, ownership_validated=True,
                                       validation_provenance="Synthetic test whole-fish review")
        kwargs.update(body_mask=body, body_mask_metadata={"validated": True, "body_region_validated": True,
                                                        "parent_track_id": 7,
                                                        "validation_provenance": "Synthetic test Body review"})
    geometry = measure_fish_geometry(mask, parts, **kwargs)
    # Match the existing model-boundary attachment without changing the native
    # coordinates or their own source-parent provenance.
    geometry.update(frame_id="recorded-frame-8", parent_track_id=7)
    actual = node(ROUNDTRIP, viewer_payload(geometry, display_id=display_id))
    evidence = actual["geometry"]
    assert actual["unchanged"] and actual["entry"]["sourceIdentityVerified"]
    assert evidence["status"] == ("Validated" if mode == "reviewed_measurement" else "Estimated")
    lines = {item["key"]: item for item in evidence["lines"]}
    assert set(lines) == {"length", "maximum", "representative"}
    visual = geometry.get("visualization") or geometry["candidate_visualization"]
    assert lines["length"]["points"] == visual["length_path"]
    assert lines["maximum"]["points"] == visual["width_axis"]
    assert lines["representative"]["points"] == visual["representative_width_axis"]
    assert lines["representative"]["value"] == visual["representative_width_axis_value_px"]
    assert not geometry["used_for_grading"]


@pytest.mark.parametrize("display_id", [7, 3], ids=["native-parent", "remapped-video-track"])
def test_detected_rgb_support_contour_roundtrip_keeps_original_frame_location(monkeypatch, display_id):
    image, mask = line_scene()
    frame = np.full((450, 500, 3), 150, np.uint8)
    bounds = CropBounds(137, 101, 317, 221)
    frame[bounds.y1:bounds.y2, bounds.x1:bounds.x2] = image
    context = RuntimeMaskContext(frame, frame_id="recorded-frame-8")
    monkeypatch.setattr(context, "get", lambda *_: (mask, {"source": "synthetic native test mask"}))
    damage = parent_damage(frame, bounds, 7, mask_context=context, frame_id="recorded-frame-8")
    serialized = {key: value for key, value in damage.items() if key != "overlay_mask"}
    geometry_mask, parts, kwargs = geometry_case(30, estimated=True)
    geometry = measure_fish_geometry(geometry_mask, parts, **kwargs)
    actual = node(ROUNDTRIP, viewer_payload(geometry, display_id=display_id, damage=serialized))
    candidates = actual["cracks"]["candidates"]
    assert actual["unchanged"] and len(candidates) == len(damage["locations"]) > 0
    for candidate, recorded in zip(candidates, damage["locations"]):
        assert candidate["bbox"] == recorded["frame_bbox"]
        assert candidate["contours"] == recorded["frame_contours"]
        assert candidate["status"] == "Estimated" and candidate["severity"] == "Unassessed"
