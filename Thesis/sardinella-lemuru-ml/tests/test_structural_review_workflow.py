"""Reference-artifact QA never creates expert labels or enables grading."""
from copy import deepcopy
import hashlib
import json

import cv2
import numpy as np
import pytest

from src.evaluation.review_structural_features import reference_template, validate_reference_package


@pytest.fixture
def package(tmp_path):
    records=[]
    for index, split in enumerate(("calibration", "validation")):
        image=np.full((60,100,3),80+index,np.uint8)
        whole=np.zeros((60,100),np.uint8);whole[5:55,5:95]=255
        body=np.zeros_like(whole);body[15:45,25:75]=255
        for name,value in (("image",image),("whole",whole),("body",body)):
            assert cv2.imwrite(str(tmp_path/f"{name}{index}.png"),value)
        digest=hashlib.sha256(image.tobytes()).hexdigest()
        provenance={"reviewer":"synthetic-artifact-test", "review_id":f"fixture-{index}","reference_set_id":"fixture-reference"}
        record={"fish_id":7,"source_id":f"fixture-{index}","frame_pixels_sha256":digest,
                "original_image_path":f"image{index}.png","whole_mask_path":f"whole{index}.png",
                "body_mask_path":f"body{index}.png","validation_provenance":provenance,"split":split}
        record["structural_evidence"]={"parent_track_id":7,"source_id":record["source_id"],
            "frame_pixels_sha256":digest,"frame_id":"fixture-review-frame","region":"Body",
            "status":"confirmed","reviewed":True,"severity":"minor","severity_reviewed":True,
            "ownership_validated":True,"body_mask_validated":True,"measurement_validated":True,
            "coordinate_space":"original_frame","locations":[{"x":35,"y":25,"width":20,"height":3}],
            "validation_provenance":provenance}
        records.append(record)
    return {"schema_version":"reviewed_feature_records_v1","reference_set_id":"fixture-reference","records":records},tmp_path


def test_empty_template_has_no_approved_records_or_grading_activation(tmp_path):
    template=reference_template()
    assert template["records"] == []
    assert template["record_example_not_approved"]["structural_evidence"]["reviewed"] is False
    result=validate_reference_package(template,base_dir=tmp_path)
    assert result["artifact_checks_passed"] is False
    assert result["automatic_activation_performed"] is result["scientific_accuracy_validated"] is False


def test_matching_native_artifacts_pass_integrity_without_claiming_accuracy(package):
    value,base=package;before=deepcopy(value)
    result=validate_reference_package(value,base_dir=base)
    assert result["artifact_checks_passed"]
    assert result["split_counts"] == {"calibration":1,"validation":1}
    assert result["automatic_activation_performed"] is result["scientific_accuracy_validated"] is False
    assert value == before
    json.dumps(result,allow_nan=False)


@pytest.mark.parametrize("fault",["wrong_digest","mask_dimensions","body_leak","missing_review","wrong_review_set",
    "cross_fish","missing_localization","outside_body","outside_frame","split_leak"])
def test_artifact_errors_are_explicit_and_do_not_enable_policy(package,fault):
    value,base=package
    record=value["records"][0]
    if fault == "wrong_digest":record["frame_pixels_sha256"]="b"*64
    elif fault == "mask_dimensions":cv2.imwrite(str(base/"body0.png"),np.ones((10,10),np.uint8))
    elif fault == "body_leak":
        body=cv2.imread(str(base/"body0.png"),cv2.IMREAD_GRAYSCALE);body[0,0]=255;cv2.imwrite(str(base/"body0.png"),body)
    elif fault == "missing_review":record["validation_provenance"]={}
    elif fault == "wrong_review_set":record["structural_evidence"]["validation_provenance"]={"reviewer":"fixture","review_id":"fixture","reference_set_id":"wrong"}
    elif fault == "cross_fish":record["structural_evidence"]["parent_track_id"]=8
    elif fault == "missing_localization":record["structural_evidence"]["locations"]=[]
    elif fault == "outside_body":record["structural_evidence"]["locations"]=[{"x":1,"y":1,"width":3,"height":3}]
    elif fault == "outside_frame":record["structural_evidence"]["locations"]=[{"x":95,"y":25,"width":20,"height":3}]
    else:
        value["records"][1]["original_image_path"]="image0.png"
        value["records"][1]["frame_pixels_sha256"]=record["frame_pixels_sha256"]
        value["records"][1]["structural_evidence"]["frame_pixels_sha256"]=record["frame_pixels_sha256"]
    result=validate_reference_package(value,base_dir=base)
    assert result["artifact_checks_passed"] is False and result["issues"]
    assert result["automatic_activation_performed"] is False
