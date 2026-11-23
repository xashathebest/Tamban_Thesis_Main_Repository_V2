"""Controlled pixel ground truth, ownership, serialization and display contracts.

Synthetic defects verify engineering behavior, not biological crack accuracy.
"""
from copy import deepcopy
import csv
from io import BytesIO, StringIO
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import cv2
import numpy as np
from openpyxl import load_workbook
import pytest

from src.api.export import DEFAULT_EXPORT_FIELDS, inspection_row, make_csv, make_surface_csv, make_xlsx
from src.features.fish_surface import analyze_owned_surface, measure_brightness, pixel_runs
from src.features.surface_export import CANDIDATE_FIELDS, surface_candidate_rows, surface_export_record
from src.inference.association import ParentAnchor
from src.inference.surface_evidence import measure_owned_surface

ROOT = Path(__file__).resolve().parents[1]


def scene(kind="clean", *, brightness=180, contrast=145, shape=(160, 320)):
    mask = np.zeros(shape, np.uint8)
    cv2.ellipse(mask, (160, 80), (145, 55), 0, 0, 360, 1, -1)
    image = np.full((*shape, 3), brightness, np.uint8)
    truth = np.zeros(shape, np.uint8)
    color = (max(0, brightness-contrast),)*3
    if kind == "straight": cv2.line(truth, (75, 80), (240, 80), 1, 3)
    elif kind == "branch":
        for a, b in [((160, 100), (160, 45)), ((160, 72), (110, 45)), ((160, 72), (210, 45))]:
            cv2.line(truth, a, b, 1, 3)
    elif kind == "curve":
        cv2.polylines(truth, [np.array([[75,80],[100,60],[135,88],[165,60],[205,95],[240,75]])], False, 1, 3)
    elif kind == "tip": cv2.line(truth, (10, 80), (60, 80), 1, 2)
    elif kind == "spot": cv2.circle(image, (160, 80), 16, color, -1)
    elif kind == "ring": cv2.circle(image, (160, 80), 22, color, 2)
    elif kind == "discoloration": cv2.ellipse(image, (160, 80), (50,24), 0, 0, 360, (100,65,20), -1)
    elif kind == "shadow": image[:,140:] = 60
    elif kind == "texture":
        for y in (60, 80, 100): cv2.line(image, (85,y), (235,y), (65,)*3, 1)
    image[truth > 0] = color
    return image, mask.astype(bool), (truth > 0) & mask.astype(bool)


def decode(encoded):
    mask = np.zeros(encoded["shape"], bool)
    for row, start, length in encoded["runs"]: mask[row, start:start+length] = True
    return mask


def provider(image, masks, *, boxes=None, reports=None):
    boxes = boxes or {identity: (0, 0, image.shape[1], image.shape[0]) for identity in masks}
    return SimpleNamespace(frame=cv2.cvtColor(image, cv2.COLOR_RGB2BGR), frame_id="source-frame",
        frame_key="source-key", candidates={identity: {"mask": mask} for identity, mask in masks.items()},
        ownership=reports or {identity: {"status": "checks_passed_unvalidated", "reasons": []} for identity in masks},
        reviewed_instances={}, reviewed_ownership={}, parents=[ParentAnchor(identity, tuple(box)) for identity, box in boxes.items()],
        is_current=lambda: True)


def measured_event(kind="straight"):
    image, mask, _ = scene(kind)
    evidence = measure_owned_surface(provider(image, {7: mask}), 7)
    evidence["surface_damage"].pop("overlay_mask")
    return {"id": 7, "track_id": 7, "quality": "Class B", "quality_confidence": .82, "analysis": evidence}


def test_exact_brightness_uses_every_owned_tip_pixel_and_distribution_agrees():
    image, mask, _ = scene()
    image[:, :85] = (20, 45, 70)
    result = measure_brightness(image, mask, metadata={"complete_mask_pixel_count": int(mask.sum())})
    expected = cv2.cvtColor(image, cv2.COLOR_RGB2HSV)[..., 2][mask].astype(float)*100/255
    assert result["mean_brightness"] == pytest.approx(expected.mean())
    assert result["median_brightness"] == pytest.approx(np.median(expected))
    assert result["brightness_std"] == pytest.approx(expected.std())
    assert result["brightness_pixel_count"] == sum(result["distribution"]["counts"]) == int(mask.sum())
    assert result["brightness_mask_coverage"] == 1
    assert result["brightness_percentiles"]["p5"] == pytest.approx(np.percentile(expected, 5))
    assert result["brightness_level"] is result["thresholds"] is None
    assert result["calibrated_measurements"] is None and not result["used_for_grading"]
    assert result["mean_brightness"] != measure_brightness(image[:,85:240], mask[:,85:240])["mean_brightness"]


def test_brightness_is_value_not_hue_or_yellowing():
    image = np.array([[[100,100,100],[100,70,10],[10,10,100]]], np.uint8)
    result = measure_brightness(image, np.ones((1,3), bool))
    assert result["brightness_std"] == 0 and result["mean_brightness"] == pytest.approx(10000/255)


@pytest.mark.parametrize("kind", ["straight", "branch", "curve", "tip"])
@pytest.mark.parametrize("brightness,contrast", [(180,145), (85,60), (240,120)])
def test_continuous_irregular_branching_and_tip_cracks_are_retained(kind, brightness, contrast):
    image, mask, truth = scene(kind, brightness=brightness, contrast=contrast)
    result = analyze_owned_surface(image, mask, metadata={"parent_track_id": 7})
    prediction = result["overlay_mask"] > 0
    assert result["status"] == "suspected"
    assert np.count_nonzero(prediction & truth)/truth.sum() >= .85
    assert np.count_nonzero(prediction & ~truth)/max(1, prediction.sum()) <= .05
    assert not (prediction & ~mask).any()
    assert result["confirmed_count"] == 0 and result["used_for_grading"] is False
    assert np.array_equal(decode(result["binary_mask"]), prediction)
    assert result["crack_area_px"] == int(prediction.sum())
    assert result["crack_density"] == pytest.approx(prediction.sum()/mask.sum())
    assert all(c["owner_fish_id"] == 7 and c["skeleton_length_px"] > 0 for c in result["locations"])


@pytest.mark.parametrize("kind,category", [("spot", "dark_spot"), ("ring", "dark_spot"),
    ("discoloration", "discoloration"), ("shadow", "shadow_or_lighting_artifact"), ("texture", "natural_fish_texture"), ("clean", None)])
def test_darkness_alone_does_not_become_a_crack(kind, category):
    image, mask, _ = scene(kind)
    result = analyze_owned_surface(image, mask, metadata={"parent_track_id": 7})
    assert not result["overlay_mask"].any()
    if category:
        assert category in {candidate["candidate_type"] for candidate in result["candidates"]}
        assert result["rejected_count"] > 0
        assert all(candidate["exclusion_reason"] for candidate in result["candidates"])


def test_all_outside_pixels_and_shadows_are_irrelevant_to_every_retained_measurement():
    image, mask, _ = scene("tip")
    changed = image.copy()
    changed[~mask] = np.random.default_rng(71).integers(0, 256, (int((~mask).sum()),3), dtype=np.uint8)
    first = analyze_owned_surface(image, mask, metadata={"parent_track_id": 7})
    second = analyze_owned_surface(changed, mask, metadata={"parent_track_id": 7})
    np.testing.assert_array_equal(first.pop("overlay_mask"), second.pop("overlay_mask"))
    assert first == second
    assert measure_brightness(image, mask) == measure_brightness(changed, mask)


def test_a_crack_touching_a_spot_does_not_turn_the_whole_spot_into_crack_pixels():
    image, mask, truth = scene("straight")
    cv2.circle(image, (160,80), 16, (35,35,35), -1)
    result = analyze_owned_surface(image, mask, metadata={"parent_track_id":7})
    prediction = result["overlay_mask"] > 0
    assert np.count_nonzero(prediction & ~truth) < 30
    assert np.count_nonzero(prediction & truth)/truth.sum() > .8
    assert result["suspected_crack_count"] == 1
    assert result["candidates"][0]["excluded_broad_or_unsupported_pixels"] > 700
    assert result["total_crack_length_px"] == result["candidates"][0]["skeleton_length_px"]


def test_candidate_limit_is_reported_as_limited_detection_not_complete_coverage():
    image, mask, _ = scene()
    for y in range(30,132,6):
        for x in range(20,304,6):
            if mask[y,x]: cv2.circle(image,(x,y),1,(20,20,20),-1)
    result = analyze_owned_surface(image,mask,metadata={"parent_track_id":7})
    assert len(result["candidates"]) == result["candidate_limit"] == 256
    assert result["candidates_omitted"] > 0
    assert result["detection_reliability"] == "candidate_limit_reached"
    assert result["raw_measurements"]["candidates_omitted"] == result["candidates_omitted"]
    assert result["used_for_grading"] is False


def test_owned_full_native_extent_is_independent_of_partial_body_and_prompt_boxes():
    image, mask, _ = scene("tip")
    instance = provider(image, {7: mask}, boxes={7: (85,40,240,120)})
    result = measure_owned_surface(instance, 7)
    x, y, w, h = cv2.boundingRect(mask.astype(np.uint8))
    assert result["brightness"]["crop_bounds"] == [x,y,x+w,y+h]
    assert result["brightness"]["brightness_pixel_count"] == int(mask.sum())
    assert result["surface_damage"]["boundary_exclusion_px"] == 0
    assert result["surface_damage"]["crack_area_px"] > 0
    # Copies prevent a display/export consumer from mutating cached evidence.
    result["brightness"]["mean_brightness"] = -1
    assert measure_owned_surface(instance, 7)["brightness"]["mean_brightness"] >= 0


def test_a_crack_processing_failure_preserves_brightness_and_abstains_on_damage(monkeypatch):
    image,mask,_ = scene("straight")
    def fail(*args,**kwargs): raise RuntimeError("simulated optional detector failure")
    monkeypatch.setattr("src.inference.surface_evidence.analyze_owned_surface",fail)
    result = measure_owned_surface(provider(image,{7:mask}),7)
    assert result["brightness"]["status"] == "measured"
    assert result["brightness"]["mean_brightness"] == pytest.approx(image.max(axis=2)[mask].mean()*100/255)
    assert result["surface_damage"]["status"] == "unavailable"
    assert result["surface_damage"]["crack_area_px"] is None
    assert result["surface_damage"]["reason"] == "surface_diagnostics_failed"


def test_crowded_shared_pixels_have_no_owner_and_no_brightness_contamination():
    image, first, _ = scene("straight")
    second = np.roll(first, 95, axis=0)
    instance = provider(image, {7: first, 8: second})
    evidence = [measure_owned_surface(instance, identity) for identity in (7,8)]
    full_owned = []
    for result, native in zip(evidence, (first,second)):
        brightness, damage = result["brightness"], result["surface_damage"]
        x,y,right,bottom = brightness["crop_bounds"]
        owned = decode(brightness["owned_mask"])
        lifted = np.zeros_like(first); lifted[y:bottom,x:right] = owned; full_owned.append(lifted)
        assert not (lifted & first & second).any()
        assert brightness["brightness_mask_coverage"] == pytest.approx(lifted.sum()/native.sum())
        if lifted.any(): assert brightness["mean_brightness"] == pytest.approx(image.max(axis=2)[lifted].mean()*100/255)
        assert not (decode(damage["binary_mask"]) & ~owned).any()
        assert all(c["owner_fish_id"] is None for c in damage["candidates"] if c["ambiguous_pixel_count"])
    assert not (full_owned[0] & full_owned[1]).any()


def test_identical_masks_retain_uncertain_candidates_without_assigning_either_fish():
    image, mask, _ = scene("straight")
    instance = provider(image, {7: mask, 8: mask})
    for identity in (7,8):
        evidence = measure_owned_surface(instance, identity)
        assert evidence["brightness"]["status"] == "unavailable"
        assert evidence["brightness"]["brightness_pixel_count"] == 0
        damage = evidence["surface_damage"]
        assert damage["candidates"] and not damage["overlay_mask"].any()
        assert all(c["candidate_type"] == "uncertain_defect" and c["owner_fish_id"] is None for c in damage["candidates"])
        assert all(c["area_px"] > 0 and c["owned_area_px"] == 0 and c["crack_density"] is None for c in damage["candidates"])


def test_missing_neighbor_mask_leaves_potential_shared_pixels_unassigned():
    image, mask, _ = scene("straight")
    instance = provider(image, {7:mask}, boxes={7:(15,25,305,135),8:(140,20,310,140)})
    result = measure_owned_surface(instance,7)
    brightness = result["brightness"]
    assert 0 < brightness["brightness_mask_coverage"] < 1
    assert brightness["measurement_reliability"] == "limited_ownership"
    assert 8 in brightness["mask_metadata"]["possible_owner_fish_ids"]
    x,y,_,_ = brightness["crop_bounds"]
    owned = decode(brightness["owned_mask"])
    assert not owned[max(0,20-y):140-y,max(0,140-x):310-x].any()


@pytest.mark.parametrize("fault", ["stale", "wrong_identity", "empty", "rectangle", "nonbinary"])
def test_unusable_masks_abstain_instead_of_reporting_a_zero_measurement(fault):
    image, mask, _ = scene("straight")
    instance = provider(image, {7: mask})
    if fault == "stale": instance.is_current = lambda: False
    elif fault == "wrong_identity": instance.ownership[7]["reasons"] = ["candidate_parent_identity_mismatch"]
    elif fault == "empty": instance.candidates[7]["mask"] = np.zeros_like(mask)
    elif fault == "rectangle": instance.candidates[7]["mask"] = np.ones_like(mask)
    else: instance.candidates[7]["mask"] = np.full(mask.shape, 127, np.uint8)
    evidence = measure_owned_surface(instance, 7)
    assert evidence["brightness"]["mean_brightness"] is None
    assert evidence["surface_damage"]["crack_area_px"] is None
    assert evidence["surface_damage"]["used_for_grading"] is False


def test_lossless_pixel_runs_preserve_single_pixels_and_holes():
    source = np.array([[1,0,1,1],[0,1,0,1],[1,1,1,1]], bool)
    assert np.array_equal(decode({"shape": list(source.shape), "runs": pixel_runs(source)}), source)


def test_offline_replay_preserves_uncalibrated_fusion_and_requires_artifact_for_calibrated_scores():
    from src.evaluation.fish_level_validation import EvaluationRules, FishLevelValidationError
    from src.inference.decision_fusion import DecisionFusionConfig
    config = {**DecisionFusionConfig().to_dict(), "calibration_id": None}
    rules = EvaluationRules.from_mapping({"decision_fusion": config})
    assert rules.to_dict()["decision_fusion"] == config
    with pytest.raises(FishLevelValidationError, match="frozen artifact"):
        EvaluationRules.from_mapping({"decision_fusion": {**config,"calibration_id":"independent-study"}})


def test_backend_fish_and_candidate_csv_and_xlsx_match_raw_measurements():
    event = measured_event()
    before = deepcopy(event)
    row = inspection_row(event)
    candidate = event["analysis"]["surface_damage"]["candidates"][0]
    assert row["mean_brightness"] == event["analysis"]["brightness"]["mean_brightness"]
    assert json.loads(row["crack_candidate_id"])[0] == candidate["candidate_id"]
    fish_csv = list(csv.DictReader(StringIO(make_csv([event], DEFAULT_EXPORT_FIELDS).decode("utf-8-sig"))))[0]
    assert float(fish_csv["mean_brightness"]) == row["mean_brightness"]
    candidates = list(csv.DictReader(StringIO(make_surface_csv([event]).decode("utf-8-sig"))))
    assert float(candidates[0]["crack_skeleton_length"]) == candidate["skeleton_length_px"]
    assert candidates[0]["crack_owner_fish_id"] == "7"
    workbook = load_workbook(BytesIO(make_xlsx([event], DEFAULT_EXPORT_FIELDS, {})))
    values = list(workbook["Surface Candidates"].values)
    xlsx = dict(zip(values[0], values[1]))
    assert xlsx["mean_brightness"] == pytest.approx(row["mean_brightness"])
    assert xlsx["crack_candidate_type"] == candidate["candidate_type"]
    assert json.loads(candidates[0]["surface_calibrated_measurements"]) == {"brightness": None, "cracks": None}
    assert event == before


def test_history_surface_csv_endpoint_exports_actual_candidate_values(monkeypatch):
    import importlib
    from fastapi.testclient import TestClient
    app = importlib.import_module("src.api.app")
    event = measured_event()
    monkeypatch.setattr(app,"_durable_events",lambda **kwargs:[event])
    monkeypatch.setattr(app,"_require_drained_event_persistence",lambda *args:None)
    response = TestClient(app.app).post("/api/export",json={"format":"surface_csv"})
    assert response.status_code == 200
    exported = list(csv.DictReader(StringIO(response.content.decode("utf-8-sig"))))
    assert exported[0]["fish_id"] == "7"
    assert float(exported[0]["mean_brightness"]) == event["analysis"]["brightness"]["mean_brightness"]
    assert exported[0]["crack_candidate_type"] == "crack_or_split"


def test_browser_and_python_export_records_have_identical_fields_values_and_raw_evidence():
    event = measured_event("discoloration")
    script = r'''
const fs=require('fs'),vm=require('vm'),source=fs.readFileSync('frontend/app.js','utf8');
for(const name of ['surfaceFeatureExport','surfaceEvidenceExportRows']){
 const start=source.indexOf(`function ${name}(`),next=source.slice(start+1).search(/\n(?:async )?function /);
 vm.runInThisContext(source.slice(start,next<0?source.length:start+1+next));
}
const event=JSON.parse(fs.readFileSync(0,'utf8'));
console.log(JSON.stringify({fish:surfaceFeatureExport(event),candidates:surfaceEvidenceExportRows([event])}));
'''
    run = subprocess.run(["node", "-e", script], input=json.dumps(event), cwd=ROOT,
                         text=True, encoding="utf-8", capture_output=True, check=True)
    browser = json.loads(run.stdout)
    expected = surface_export_record(event)
    for key, value in expected.items():
        if key in {"brightness_percentiles","brightness_distribution","surface_raw_measurements","surface_calibrated_measurements",*CANDIDATE_FIELDS}:
            assert json.loads(browser["fish"][key]) == json.loads(value)
        else: assert browser["fish"][key] == value
    for actual, expected in zip(browser["candidates"], surface_candidate_rows([event])):
        assert set(actual) == set(expected)
        for key in expected:
            try: value = json.loads(expected[key])
            except (TypeError, ValueError): assert actual[key] == expected[key]
            else: assert json.loads(actual[key]) == value
