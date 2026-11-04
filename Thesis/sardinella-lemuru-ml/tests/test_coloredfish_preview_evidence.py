"""On-demand native mask previews supply diagnostics without rerunning grades."""

from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pytest

from src.api.segmentation_preview import PreviewSnapshotCache, generate_mask_preview
from src.inference.experimental_segmentation import ExperimentalFrameSegmentation
from test_coloredfish_evidence_integration import ROUNDTRIP
from test_experimental_segmentation_pipeline import PARENTS, Service, parts
from test_sam_preview_ui import node


class PreviewService(Service):
    def status(self):
        return {"loaded": True, "fixture": "native masks, not fish validation"}


def scene(mode="normal"):
    frame = np.full((120, 640, 3), 150, np.uint8)
    service = PreviewService(mode)
    detected = parts()
    fish = []
    for parent in PARENTS:
        owned = detected[:2] if parent.track_id == 1 else detected[2:]
        fish.append({"id": parent.track_id, "bbox": list(parent.bbox), "detector_confidence": parent.confidence,
                     "parts": [{**part.to_dict(), "coordinate_space": "original_frame",
                                "parent_track_id": parent.track_id} for part in owned]})
    return frame, service, fish


def existing_provider(frame, service):
    provider = ExperimentalFrameSegmentation(frame, "preview-native-source", service=service)
    provider.prepare(PARENTS, parts())
    context = SimpleNamespace(_experimental=provider, is_for_frame=lambda candidate: candidate is frame)
    return provider, context


def test_snapshot_cache_stays_metadata_only_while_preview_computes_native_axes():
    frame, service, fish = scene()
    detector = SimpleNamespace(model=object())
    cache = PreviewSnapshotCache()
    fish[0].update(quality="Class B", analysis={"weighted_scores": {"Class B": .9}})
    token = cache.remember("exact-source-pixels", frame.shape, fish, detector)
    cached = cache.resolve(token, "exact-source-pixels", frame.shape, detector)
    assert all("analysis" not in record and "quality" not in record for record in cached)
    result = generate_mask_preview(frame, cached, image_sha256="exact-source-pixels", sam_service=service, reused=True)
    assert result["detector_snapshot_reused"]
    assert len(service.frames) == 1 and len(service.prompts) == 2
    geometry = result["fish"][0]["analysis"]["fish_geometry"]
    visual = geometry["candidate_visualization"]
    assert visual["status"] == "estimated"
    assert visual["coordinate_space"] == "original_frame" and visual["parent_track_id"] == 1
    assert visual["frame_id"] == result["source"]["frame_id"]
    assert visual["frame_width_px"] == 640 and visual["frame_height_px"] == 120
    assert geometry["candidate_measurements"]["fish_length_px"] == pytest.approx(241, abs=1)
    assert geometry["candidate_measurements"]["max_body_width_px"] == pytest.approx(45, abs=1)
    assert visual["length_path"] and visual["width_axis"] and visual["representative_width_axis"]


def test_actual_on_demand_preview_geometry_roundtrips_into_three_browser_lines():
    frame, service, fish = scene()
    result = generate_mask_preview(frame, fish, image_sha256="source", sam_service=service, reused=True)
    actual = node(ROUNDTRIP, result)
    assert actual["unchanged"] and actual["geometry"]["status"] == "Estimated"
    assert {line["key"] for line in actual["geometry"]["lines"]} == {"length", "maximum", "representative"}
    assert actual["cracks"]["candidates"] == [] and "Body" in actual["cracks"]["reason"]


def test_preview_diagnostics_do_not_grade_or_mutate_the_recorded_analysis():
    frame, service, fish = scene()
    before = deepcopy(fish)
    result = generate_mask_preview(frame, fish, image_sha256="source", sam_service=service)
    assert fish == before
    for record in result["fish"]:
        analysis = record["analysis"]
        assert "quality" not in record and "weighted_scores" not in analysis
        for key in ("fish_geometry", "body_width", "surface_damage"):
            assert analysis[key]["used_for_grading"] is False
        assert analysis["body_width"]["score_contributed"] is False
        damage = analysis["surface_damage"]
        assert damage["status"] == "unavailable" and damage["locations"] == []
        assert "reviewed" in damage["reason"] and "absence of cracks" in damage["reason"]


def test_same_still_frame_label_cannot_borrow_geometry_or_cracks_from_different_pixels():
    frame, service, fish = scene()
    provider, context = existing_provider(frame, service)
    fish[0]["analysis"] = {
        "fish_geometry": {"frame_id": provider.frame_id, "parent_track_id": 1,
                          "mask_metadata": {"candidate_provenance": {"frame_key": "different-pixels"}},
                          "status": "measured", "fish_length_px": 999,
                          "visualization": {"frame_id": provider.frame_id, "parent_track_id": 1,
                                            "coordinate_space": "original_frame", "frame_width_px": 640,
                                            "frame_height_px": 120, "principal_axis": [[50, 50], [200, 50]]}},
        "surface_damage": {"frame_id": provider.frame_id, "parent_track_id": 1, "status": "suspected",
                           "coordinate_space": "original_frame", "locations": [{"x": 50, "y": 50, "width": 10, "height": 2}]},
    }
    before = deepcopy(fish)
    result = generate_mask_preview(frame, fish, image_sha256="source", reused=True, mask_context=context)
    analysis = result["fish"][0]["analysis"]
    assert analysis["fish_geometry"]["candidate_measurements"]["fish_length_px"] == pytest.approx(241, abs=1)
    assert analysis["surface_damage"]["status"] == "unavailable" and analysis["surface_damage"]["locations"] == []
    assert fish == before and len(service.frames) == 1 and len(service.prompts) == 2


def test_exact_native_source_preserves_existing_geometry_width_fusion_and_crack_records(monkeypatch):
    frame, service, fish = scene()
    provider, context = existing_provider(frame, service)
    first = generate_mask_preview(frame, fish, image_sha256="source", reused=True, mask_context=context)
    saved = deepcopy(first["fish"][0]["analysis"])
    saved["body_width"] = {"score_contributed": True, "used_for_grading": True, "recorded_support": .03}
    saved["feature_fusion"] = {"recorded_final_grade": "Class B"}
    saved["surface_damage"].update(status="suspected", locations=[{"x": 60, "y": 50, "width": 12, "height": 2}])
    fish[0]["analysis"] = saved
    original_get = provider.get
    def guarded(identity, bounds):
        if identity == 1:
            raise AssertionError("Already source-bound geometry must be reused")
        return original_get(identity, bounds)
    monkeypatch.setattr(provider, "get", guarded)
    result = generate_mask_preview(frame, fish, image_sha256="source", reused=True, mask_context=context)
    actual = result["fish"][0]["analysis"]
    for key in ("fish_geometry", "body_width", "feature_fusion", "surface_damage"):
        assert actual[key] == saved[key]
    assert len(service.frames) == 1 and len(service.prompts) == 2


def test_rejected_native_ownership_never_receives_display_axes():
    frame, service, fish = scene("merged")
    result = generate_mask_preview(frame, fish, image_sha256="source", sam_service=service)
    for record in result["fish"]:
        assert record["segmentation"]["engineering_checks_passed"] is False
        geometry = record["analysis"]["fish_geometry"]
        assert geometry["fish_length_px"] is None and geometry["candidate_measurements"] == {}
        assert "mask_ownership_unreliable" in geometry["reasons"]
        assert not geometry.get("candidate_visualization", {}).get("length_path")


def test_neighbor_body_assignment_cannot_supply_this_fish_width_lines():
    frame, service, fish = scene()
    provider, context = existing_provider(frame, service)
    fish[0]["parts"][0]["parent_track_id"] = 2
    result = generate_mask_preview(frame, fish, image_sha256="source", reused=True, mask_context=context)
    geometry = result["fish"][0]["analysis"]["fish_geometry"]
    visual = geometry["candidate_visualization"]
    assert visual["length_path"] and visual["body_width_status"] == "unavailable"
    assert "width_axis" not in visual and "representative_width_axis" not in visual
    assert "associated_body_region_unavailable" in geometry["reasons"]


def test_same_source_wrong_parent_crack_locations_are_withheld():
    frame, service, fish = scene()
    provider, context = existing_provider(frame, service)
    fish[0]["analysis"] = {"segmentation": {"provenance": {"frame_key": provider.frame_key}},
                          "surface_damage": {"status": "suspected", "frame_id": provider.frame_id,
                                             "parent_track_id": 2, "locations": [{"x": 360, "y": 50, "width": 12, "height": 2}]}}
    result = generate_mask_preview(frame, fish, image_sha256="source", reused=True, mask_context=context)
    assert result["fish"][0]["analysis"]["surface_damage"]["locations"] == []
