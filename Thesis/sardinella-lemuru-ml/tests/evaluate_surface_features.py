"""Reproducible detector confusion metrics with exact synthetic pixel truth.

Optionally --manifest accepts {cases:[{id,image_path,fish_mask_path,
crack_mask_path,fish_id}]} relative to the manifest. It never labels specimens,
changes thresholds, calibrates grading, or trains a model.
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter
import json
from pathlib import Path
import sys
from time import perf_counter

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.features.damage import analyze_surface_damage
from src.features.fish_surface import analyze_owned_surface, measure_brightness
from test_fish_surface import scene


def confusion(prediction, truth, mask):
    tp = int(np.count_nonzero(prediction & truth))
    fp = int(np.count_nonzero(prediction & ~truth))
    fn = int(np.count_nonzero(~prediction & truth))
    return {"tp_pixels": tp, "fp_pixels": fp, "fn_pixels": fn,
            "tn_pixels": int(np.count_nonzero(mask & ~prediction & ~truth)),
            "precision": tp/(tp+fp) if tp+fp else None,
            "recall": tp/(tp+fn) if tp+fn else None,
            "iou": tp/(tp+fp+fn) if tp+fp+fn else None,
            "truth_present": bool(truth.any()), "prediction_present": bool(prediction.any()),
            "missed_positive_image": bool(truth.any() and not prediction.any()),
            "false_positive_image": bool(not truth.any() and prediction.any())}


def aggregate(records):
    summed = {key: sum(record[key] for record in records) for key in ("tp_pixels", "fp_pixels", "fn_pixels", "tn_pixels")}
    tp, fp, fn = (summed[key] for key in ("tp_pixels", "fp_pixels", "fn_pixels"))
    return {**summed, "pixel_precision": tp/(tp+fp) if tp+fp else None,
        "pixel_recall": tp/(tp+fn) if tp+fn else None,
        "pixel_iou": tp/(tp+fp+fn) if tp+fp+fn else None,
        "positive_images": sum(record["truth_present"] for record in records),
        "negative_images": sum(not record["truth_present"] for record in records),
        "missed_positive_images": sum(record["missed_positive_image"] for record in records),
        "false_positive_images": sum(record["false_positive_image"] for record in records)}


def synthetic_cases():
    for lighting, brightness, contrast in (("moderate",180,145),("dim",85,60),("bright",240,120)):
        for kind in ("straight","branch","curve","tip","spot","ring","discoloration","shadow","texture","clean"):
            image, mask, truth = scene(kind, brightness=brightness, contrast=contrast)
            yield f"{kind}_{lighting}", image, mask, truth, "controlled"
    for kind in ("straight", "branch", "curve", "tip"):
        image, mask, truth = scene(kind, brightness=130, contrast=8)
        yield f"{kind}_low_contrast", image, mask, truth, "below_contrast_filter"
    rng = np.random.default_rng(905)
    image, mask, truth = scene("straight")
    cv2.circle(image,(160,80),16,(35,35,35),-1)
    yield "crack_touching_dark_spot", image, mask, truth, "touching_spot"
    for kind in ("straight","branch","curve","tip","spot","clean","texture"):
        image, mask, truth = scene(kind, brightness=170, contrast=45)
        image = np.clip(image.astype(float)+rng.normal(0,3,image.shape[:2])[...,None],0,255).astype(np.uint8)
        yield f"{kind}_noisy", image, mask, truth, "noise_sigma_3"


def manifest_cases(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    for record in data["cases"]:
        image = cv2.imread(str(path.parent/record["image_path"]))
        mask = cv2.imread(str(path.parent/record["fish_mask_path"]), cv2.IMREAD_GRAYSCALE)
        truth = cv2.imread(str(path.parent/record["crack_mask_path"]), cv2.IMREAD_GRAYSCALE)
        if image is None or mask is None or truth is None or image.shape[:2] != mask.shape or mask.shape != truth.shape:
            raise ValueError(f"Missing or unaligned native pixels: {record['id']}")
        if np.any((truth > 0) & (mask == 0)):
            raise ValueError(f"Crack truth lies outside its owned fish mask: {record['id']}")
        yield record["id"], cv2.cvtColor(image,cv2.COLOR_BGR2RGB), mask>0, truth>0, record.get("condition","supplied"), record.get("fish_id",1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT/"results/qa/surface_features")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    cases, brightness_errors = [], []
    source = manifest_cases(args.manifest) if args.manifest else synthetic_cases()
    for case in source:
        identity, image, mask, truth, condition, *owner = case
        started = perf_counter()
        after = analyze_owned_surface(image, mask, metadata={"parent_track_id": owner[0] if owner else 1})
        elapsed_ms = (perf_counter()-started)*1000
        before = analyze_surface_damage(image, mask)
        brightness = measure_brightness(image,mask)
        expected = image.max(axis=2)[mask].astype(float)*100/255
        brightness_errors.append(abs(brightness["mean_brightness"]-expected.mean()))
        record = {"id":identity,"condition":condition,"before":confusion(before["overlay_mask"]>0,truth,mask),
            "after":confusion(after["overlay_mask"]>0,truth,mask),"processing_ms":elapsed_ms,
            "categories":dict(Counter(item["candidate_type"] for item in after["candidates"])),
            "candidate_count":len(after["candidates"]), "confirmed_count":after["confirmed_count"]}
        cases.append(record)
        if condition == "controlled" and identity.endswith("moderate"):
            folder = args.output/identity; folder.mkdir(exist_ok=True)
            for name,array in (("original",cv2.cvtColor(image,cv2.COLOR_RGB2BGR)),("owned_fish",mask.astype(np.uint8)*255),
                ("crack_truth",truth.astype(np.uint8)*255),("before_cracks",before["overlay_mask"]),("after_cracks",after["overlay_mask"])):
                cv2.imwrite(str(folder/f"{name}.png"),array)
    result = {"scope":"Supplied labeled masks" if args.manifest else "Synthetic pixel ground truth only; no biological crack labels",
        "input_manifest":str(args.manifest) if args.manifest else None,
        "segmentation_scope":"Input fish masks are supplied; this benchmark does not measure MobileSAM segmentation accuracy",
        "case_count":len(cases),"before":aggregate([case["before"] for case in cases]),
        "after":aggregate([case["after"] for case in cases]),
        "controlled_after":aggregate([case["after"] for case in cases if case["condition"]=="controlled"]),
        "brightness_max_absolute_error_percentage_points":max(brightness_errors,default=0.),
        "unvalidated_candidates_influence_grading":False,"cases":cases}
    (args.output/"detection_metrics.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    with (args.output/"detection_cases.csv").open("w",newline="",encoding="utf-8") as stream:
        fields = ["case","condition","tp_pixels","fp_pixels","fn_pixels","precision","recall","iou","missed_positive_image","false_positive_image"]
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
        for case in cases: writer.writerow({"case":case["id"],"condition":case["condition"],**{key:case["after"][key] for key in fields[2:]}})
    print(json.dumps({key:value for key,value in result.items() if key!="cases"},indent=2))


if __name__ == "__main__": main()
