"""Automatic inspection, reviewed artifacts, and adaptive sampling integration."""
import asyncio
from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path
from threading import RLock
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from src.api.image_analysis import StillImageAnalyzer
from src.api.segmentation_preview import PreviewSnapshotCache
from src.inference.feature_fusion import StructuralFusionConfig
from src.inference.preprocessing import RuntimeMaskContext
from src.inference.reviewed_features import load_reviewed_instances
from src.inference.segmentation_schedule import AdaptiveSegmentationSchedule
from src.inference.yolo_fish_detector import FishDetection
from test_experimental_segmentation_pipeline import PARENTS, Service, model


@pytest.fixture
def setup(monkeypatch):
    frame = np.random.default_rng(8).integers(30, 220, (120,640,3), dtype=np.uint8)
    service = Service()
    service.status = lambda: {"loaded": True, "device": "cpu", "ownership_validated": False}
    monkeypatch.setattr("src.inference.mobilesam_backend.get_mobilesam_service", lambda: service)
    calls = []
    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError("Automatic SAM cannot run GrabCut as an extra feature pass")
    monkeypatch.setattr("src.inference.preprocessing.generate_runtime_fish_mask", forbidden)
    monkeypatch.setattr("src.inference.fish_geometry_pipeline.generate_runtime_fish_mask", forbidden)
    return frame, service, calls


def test_run_analysis_automatically_embeds_masks_once_and_preserves_grades(setup, monkeypatch):
    frame, service, grabcut = setup
    app = importlib.import_module("src.api.app")
    count = []
    detector = SimpleNamespace(model=object(), weights_path=Path("synthetic.pt"), confidence_threshold=.5,
        detect=lambda _: (count.append(1) or [FishDetection(p.bbox,p.confidence) for p in PARENTS]))
    quality = model()
    baseline = model().predict_full_frame(frame, PARENTS, stabilize=False, mask_context=RuntimeMaskContext(frame,backend="geometry_only"))
    monkeypatch.setattr(app,"model",detector);monkeypatch.setattr(app,"quality_model",quality)
    monkeypatch.setattr(app,"image_analyzer",StillImageAnalyzer(detector,quality))
    monkeypatch.setattr(app,"service",SimpleNamespace(_processing_lock=RLock()))
    monkeypatch.setattr(app,"mask_preview_snapshots",PreviewSnapshotCache())
    monkeypatch.delenv("SEGMENTATION_BACKEND", raising=False)
    ok, encoded = cv2.imencode(".png",frame);assert ok
    async def stream():yield encoded.tobytes()
    result=asyncio.run(app.analyze_image(SimpleNamespace(headers={"x-filename":"fixture.png"},query_params={},stream=stream)))
    preview=result["segmentation_preview"]
    assert preview["generated_masks"]==2 and len(service.frames)==1 and len(service.prompts)==2
    assert preview["source"]["image_sha256"]==hashlib.sha256(encoded.tobytes()).hexdigest()
    assert len(count)==1 and not grabcut
    for fish in result["fish"]:
        assert fish["quality"]==baseline[fish["id"]][0].quality=="Class A"
        assert fish["analysis"]["feature_fusion"]["contributions_applied"]==[]
        assert fish["analysis"]["fish_geometry"]["fish_length_cm"] is None


def catalog(tmp_path, frame):
    whole=np.zeros(frame.shape[:2],np.uint8);cv2.ellipse(whole,(150,60),(120,22),0,0,360,255,-1)
    body=np.zeros_like(whole);body[44:76,100:200]=255
    cv2.imwrite(str(tmp_path/"whole.png"),whole);cv2.imwrite(str(tmp_path/"body.png"),body)
    provenance={"reviewer":"synthetic-software-fixture","review_id":"fixture","reference_set_id":"fixture-set"}
    digest=hashlib.sha256(frame.tobytes()).hexdigest()
    flags={"reviewed":True,"ownership_validated":True,"measurement_validated":True,"body_mask_validated":True,
           "clipped":False,"overlapping":False,"ownership_ambiguous":False,"partial_silhouette":False}
    structural={**flags,"fish_id":1,"source_id":"fixture-source","frame_pixels_sha256":digest,
        "frame_id":"original-reviewed-frame","status":"confirmed","region":"Body","severity":"major",
        "severity_reviewed":True,"validation_provenance":provenance,"coordinate_space":"original_frame",
        "locations":[{"x":125,"y":55,"width":20,"height":3}]}
    row={**flags,"fish_id":1,"source_id":"fixture-source","frame_pixels_sha256":digest,
        "whole_mask_path":"whole.png","body_mask_path":"body.png","body_region_validated":True,
        "orientation_reliable":True,"validation_provenance":provenance,"structural_evidence":structural}
    location=tmp_path/"review.json"
    def save(value):location.write_text(json.dumps({"schema_version":"reviewed_feature_records_v1","records":[value]}))
    save(row)
    return row,location,save,provenance


def test_reviewed_native_catalog_reaches_geometry_and_major_crack_eligibility(setup,tmp_path,monkeypatch):
    frame,service,_=setup
    row,path,_,provenance=catalog(tmp_path,frame)
    monkeypatch.setenv("FISH_REVIEWED_FEATURES_PATH",str(path))
    quality=model()
    quality._grading_engine.structural_config=StructuralFusionConfig(enabled=True,calibration_validated=True,
        policy_id="synthetic-only",reference_set_id="fixture-set",validation_sample_count=1,policy_review_provenance=provenance)
    context=RuntimeMaskContext(frame,frame_id="current-frame",backend="mobilesam_experimental")
    result=quality.predict_full_frame(frame,PARENTS,stabilize=False,frame_id="current-frame",mask_context=context,
                                     source_context={"source_id":"fixture-source"})[1][0]
    assert result.analysis["feature_fusion"]["primary_anatomical"]["grade"]=="Class A"
    assert (result.quality or "Ungraded")=="Ungraded"  # No independently supported eligible alternative is invented.
    assert result.analysis["feature_fusion"]["eligibility"]["class_a_eligible"] is False
    geometry=result.analysis["fish_geometry"]
    assert geometry["measurement_validated"] and geometry["body_region_validated"]
    assert geometry["fish_length_px"]>0 and geometry["representative_body_width_px"]>0
    assert geometry["fish_length_cm"] is None
    assert row["structural_evidence"]["frame_id"]=="original-reviewed-frame"


@pytest.mark.parametrize("corruption",["pixels","source","fish","unreviewed","nested_neighbor","outside_body"])
def test_artifacts_cannot_promote_wrong_source_or_neighbor_structural_evidence(setup,tmp_path,monkeypatch,corruption):
    frame,_,_=setup;row,path,save,_=catalog(tmp_path,frame)
    if corruption=="pixels":row["frame_pixels_sha256"]="0"*64
    elif corruption=="source":row["source_id"]="another-camera"
    elif corruption=="fish":row["fish_id"]=99
    elif corruption=="unreviewed":row["reviewed"]=False
    elif corruption=="nested_neighbor":row["structural_evidence"]["fish_id"]=2
    else:row["structural_evidence"]["locations"][0]["x"]=300
    save(row);monkeypatch.setenv("FISH_REVIEWED_FEATURES_PATH",str(path))
    reviewed,_=load_reviewed_instances(frame,PARENTS,{"source_id":"fixture-source"})
    if corruption in {"nested_neighbor","outside_body"}:
        assert reviewed[1]["structural_evidence"] is None
    else:assert reviewed=={}


def test_adaptive_schedule_uses_identity_motion_overlap_and_observed_latency():
    clock=[0.];schedule=AdaptiveSegmentationSchedule(minimum_frame_interval=2,refresh_frame_interval=10,clock=lambda:clock[0])
    assert schedule.choose(PARENTS,0)=="mobilesam_experimental"
    schedule.record(1000)
    moved=[type(PARENTS[0])(7,PARENTS[0].bbox,.9)]
    clock[0]=.2
    assert schedule.choose(moved,2)=="geometry_only"
    assert "latency_budget" in schedule.last_reason
    clock[0]=2.1
    assert schedule.choose(moved,3)=="mobilesam_experimental"
    assert schedule.last_reason=="fish_identity_changed"
    schedule.record(20)
    clock[0]=3.
    assert schedule.choose(moved,5)=="geometry_only"
    assert schedule.choose(moved,13)=="mobilesam_experimental"
    assert schedule.last_reason=="periodic_refresh"
    assert schedule.diagnostics()["masks_reused_across_frames"] is False
