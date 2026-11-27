"""Read-only end-to-end verification of the selected cleaned COCO ZIP.

Run explicitly with ``python tests/annotation_primary_integrity.py`` after the
primary import finishes. No importer, model inference, dataset mutation, or
application startup is invoked. Only the ignored JSON QA report is written.
The official pycocotools decoder is a QA dependency, not an application one.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import contextmanager
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import sqlite3
import sys
from time import monotonic, sleep
import zipfile

import cv2
import numpy as np
from pycocotools import mask as official

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.annotation.masks import coco_segmentation_to_mask, mask_bbox, segmentation_to_mask, yolo_polygon
from src.annotation.store import AnnotationStore
from src.preprocessing.audit_v7_exports import SOURCE_NAME_TO_ID

OUTPUT = ROOT / "results/qa/annotation_workflow/primary_integrity.json"
WORKSPACE = ROOT / "dataset/annotation_workspace"
SECONDARY = ROOT / "Dried Fish Quality Grading.v7i.coco-segmentation"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_digest(path):
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


class ReadOnlyStore(AnnotationStore):
    @contextmanager
    def _db(self, write=False):
        if write:
            raise AssertionError("Integrity QA cannot mutate the annotation store.")
        connection = sqlite3.connect((self.root / "annotations.sqlite3").as_uri() + "?mode=ro", uri=True)
        try:
            connection.execute("PRAGMA query_only=ON")
            yield connection
        finally:
            connection.close()


def read_profile(store):
    with store._db() as connection:
        row = connection.execute("SELECT value FROM meta WHERE key='primary_learning_dataset'").fetchone()
    return json.loads(row[0]) if row else None


def ready_profile(store, wait_seconds):
    deadline = monotonic() + wait_seconds
    while True:
        profile = read_profile(store)
        state = profile.get("status") if profile else "not_selected"
        if state == "ready":
            return profile
        if state != "importing" or monotonic() >= deadline:
            raise RuntimeError(f"Primary import is {state!r}; no incomplete dataset was verified.")
        print("Primary import is still running; integrity verification is waiting read only.", flush=True)
        sleep(min(30., max(0., deadline - monotonic())))


def official_mask(segmentation, height, width):
    if isinstance(segmentation, list):
        encoded = official.merge(official.frPyObjects(segmentation, height, width))
    elif isinstance(segmentation, dict) and isinstance(segmentation.get("counts"), list):
        encoded = official.frPyObjects(segmentation, height, width)
    else:
        encoded = segmentation
    mask = official.decode(encoded)
    if mask.ndim == 3:
        mask = np.any(mask, axis=2)
    return mask != 0


def semantic_name(name):
    # Explicit textual aliases; original numeric ZIP category IDs are unrelated
    # to the existing registry/model IDs and must never be copied as mappings.
    aliases = {f"Class_C_{part}": f"Grade_C_{part}" for part in ("Body", "Head", "Tail")}
    return aliases.get(name, name)


def rectangle_like_source(segmentation):
    if not isinstance(segmentation, list) or len(segmentation) != 1:
        return False
    ring = segmentation[0]
    if len(ring) < 8 or len(ring) % 2:
        return False
    points = [tuple(ring[index:index + 2]) for index in range(0, len(ring), 2)]
    while len(points) > 1 and points[-1] == points[0]:
        points.pop()
    unique = set(points)
    if len(unique) != 4 or len({point[0] for point in unique}) != 2 or len({point[1] for point in unique}) != 2:
        return False
    area = abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1]))) / 2
    width = max(point[0] for point in unique) - min(point[0] for point in unique)
    height = max(point[1] for point in unique) - min(point[1] for point in unique)
    return width * height > 0 and np.isclose(area, width * height, rtol=0, atol=1e-8)


def source_groups(images, provenance, near_pairs, zip_sha256):
    """Independently reconstruct transitive graph components from raw ZIP data."""
    paths = {image["file_name"] for image in images}
    by_path = {record["image"]: record for record in provenance}
    graph = {path: set() for path in paths}
    captures, original_splits = defaultdict(set), {}
    for path in paths:
        record = by_path[path]
        splits = {"valid" if split in {"val", "valid", "validation"} else split for split in record["original_splits"]}
        if splits - {"train", "valid", "test"}:
            raise AssertionError("Unexpected original source split.")
        original_splits[path] = next((split for split in ("test", "valid", "train") if split in splits), None)
        for source in record["sources"]:
            capture = re.sub(r"\.rf\.[^.]+(?=\.[^.]+$)", "", PurePosixPath(source).name)
            capture = re.sub(r"_(jpg|jpeg|png)(?=\.)", "", capture, flags=re.I)
            captures[capture].add(path)
    capture_edges = 0
    for members in captures.values():
        ordered = sorted(members)
        for path in ordered[1:]:
            graph[ordered[0]].add(path)
            graph[path].add(ordered[0])
            capture_edges += 1
    for pair in near_pairs:
        first, second = pair["image_1"], pair["image_2"]
        if first not in paths or second not in paths:
            raise AssertionError("Near-duplicate report references an absent source image.")
        graph[first].add(second)
        graph[second].add(first)
    unseen, components, details = set(paths), [], {}
    while unseen:
        stack, members = [min(unseen)], set()
        while stack:
            path = stack.pop()
            if path in members:
                continue
            members.add(path)
            stack.extend(graph[path] - members)
        unseen -= members
        splits = {original_splits[path] for path in members}
        protected = next((split for split in ("test", "valid", "train") if split in splits), None)
        group_id = "primary-" + digest((zip_sha256 + ":" + min(members)).encode())[:24]
        components.append({"group_id": group_id, "size": len(members), "source_splits": sorted(s for s in splits if s),
                           "protected_split": protected, "images": sorted(members)})
        for path in members:
            details[path] = {"group_id": group_id, "size": len(members), "protected_split": protected,
                             "original_split": original_splits[path], "provenance": by_path[path]}
    return details, {"groups": len(components), "near_duplicate_pairs": len(near_pairs), "capture_edges": capture_edges,
                     "multi_image_groups": sum(component["size"] > 1 for component in components),
                     "cross_source_split_groups": [component for component in components if len(component["source_splits"]) > 1],
                     "protected_split_image_counts": dict(Counter(value["protected_split"] for value in details.values())),
                     "original_split_image_counts": dict(Counter(value["original_split"] for value in details.values()))}


def self_tests():
    images = [{"file_name": name} for name in ("a.jpg", "b.jpg", "c.jpg")]
    provenance = [
        {"image": "a.jpg", "original_splits": ["train"], "sources": ["source/train/capture_jpg.rf.a.jpg"]},
        {"image": "b.jpg", "original_splits": ["valid"], "sources": ["source/valid/capture_jpg.rf.b.jpg"]},
        {"image": "c.jpg", "original_splits": ["test"], "sources": ["source/test/other_jpg.rf.c.jpg"]}]
    groups, summary = source_groups(images, provenance, [{"image_1": "b.jpg", "image_2": "c.jpg"}], "qa")
    assert summary["groups"] == 1 and summary["capture_edges"] == 1
    assert all(group["protected_split"] == "test" and group["size"] == 3 for group in groups.values())
    assert summary["original_split_image_counts"] == {"train": 1, "valid": 1, "test": 1}
    assert rectangle_like_source([[0, 0, 5, 0, 5, 3, 0, 3]])
    assert rectangle_like_source([[0, 0, 5, 0, 5, 3, 0, 3, 0, 0]])
    assert not rectangle_like_source([[0, 0, 5, 3, 5, 0, 0, 3, 0, 0]])
    return {"passed": True, "assertions": 6, "scope": "transitive capture/near graph, protected holdout priority, preserved original splits, closed rectangle counting"}


def verify_primary(store, profile, documents, classes, errors):
    started = monotonic()
    dataset_id = profile["dataset_id"]
    selected = [document for document in documents if document.get("dataset_id") == dataset_id]
    zip_path = Path(profile["source_path"])
    before_sha = file_digest(zip_path)
    counts = Counter()
    topology, component_counts, hole_counts, yolo_failures = Counter(), Counter(), Counter(), []
    yolo_compatible_images = 0
    def check(condition, message, image_id=None, annotation_id=None):
        if not condition:
            errors.append({"scope": "primary", "image_id": image_id, "annotation_id": annotation_id, "message": message})
    check(profile.get("reference_eligible") is True and profile.get("training_certified") is True and profile.get("source_validation_error_count") == 0,
          "Ready primary profile is not structurally certified for manual references.")
    check(before_sha == profile["source_sha256"], "Original ZIP digest differs from selected immutable source.")
    check(file_digest(store.root / profile["source_zip_artifact"]) == before_sha, "Preserved ZIP artifact differs from original ZIP.")
    with zipfile.ZipFile(zip_path) as archive:
        source_name = profile["source_entry"]
        source_raw = archive.read(source_name)
        source = json.loads(source_raw)
        directory = PurePosixPath(source_name).parent
        provenance = json.loads(archive.read((directory / "provenance.json").as_posix()))
        pairs = list(csv.DictReader(io.StringIO(archive.read((directory / "near_duplicate_candidates.csv").as_posix()).decode("utf-8-sig"))))
        groups, group_summary = source_groups(source["images"], provenance, pairs, before_sha)
        check(len(source["images"]) == 345 and len(source["annotations"]) == 4867, "Selected source count differs from the requested 345/4867 baseline.")
        check(len(selected) == len(source["images"]), "Stored primary image count differs from source.")
        check(sum(len(document["annotations"]) for document in selected) == len(source["annotations"]), "Stored primary annotation count differs from source.")
        check(group_summary["original_split_image_counts"] == {"train": 277, "valid": 45, "test": 23}, "Original source split counts were not 277/45/23.")
        check((store.root / profile["baseline_path"]).read_bytes() == source_raw, "COCO baseline bytes differ from original ZIP entry.")
        check(digest(source_raw) == profile["baseline_sha256"], "COCO baseline digest differs from profile.")
        for filename, artifact in profile.get("auxiliary_artifacts", {}).items():
            check((store.root / artifact).read_bytes() == archive.read((directory / filename).as_posix()), "Auxiliary provenance artifact differs from original ZIP: " + filename)
        source_images = {image["id"]: image for image in source["images"]}
        source_categories = {category["id"]: category for category in source["categories"]}
        source_annotations = defaultdict(dict)
        class_coverage = {split: Counter() for split in ("train", "valid", "test")}
        for annotation in source["annotations"]:
            source_annotations[annotation["image_id"]][annotation["id"]] = annotation
            image = source_images[annotation["image_id"]]
            split = groups[image["file_name"]]["protected_split"]
            class_coverage[split][semantic_name(source_categories[annotation["category_id"]]["name"])] += 1
        declared_mapping = {entry["source_category_id"]: entry for entry in profile["category_mapping"]}
        check(set(declared_mapping) == set(source_categories), "Category mapping omits original ZIP category IDs.")
        expected_references = Counter()
        expected_reference_area = {}
        selected_by_id = {document["id"]: document for document in selected}
        check(len({document["baseline"]["source_image_id"] for document in selected}) == len(source_images), "Source images are missing or duplicated in primary store.")
        for number, document in enumerate(selected, 1):
            identifier, baseline = document["id"], document["baseline"]
            image = source_images[baseline["source_image_id"]]
            group = groups[image["file_name"]]
            metadata = document.get("metadata") or {}
            check(document["revision"] == 1 and document["status"] == "manual_verified", "Imported primary original lost revision-one manual provenance.", identifier)
            check(document["source_record"] == image, "Original COCO image metadata changed.", identifier)
            check(document["width"] == image["width"] and document["height"] == image["height"], "Stored original image dimensions changed.", identifier)
            check(baseline["source_zip_sha256"] == before_sha and baseline["source_entry"] == source_name, "Baseline ZIP association changed.", identifier)
            check(document.get("split") == group["original_split"] and metadata.get("original_split") == group["original_split"], "Original split provenance was altered.", identifier)
            check(metadata.get("protected_split") == group["protected_split"], "Transitive holdout protection is incorrect.", identifier)
            check(metadata.get("leakage_group_id") == group["group_id"] == metadata.get("dataset_group_id"), "Capture/near-duplicate component ID is incorrect.", identifier)
            check(metadata.get("near_duplicate_or_capture_group_size") == group["size"], "Transitive group size is incorrect.", identifier)
            check(metadata.get("source_provenance") == group["provenance"], "Original source provenance changed.", identifier)
            image_bytes = archive.read((directory / image["file_name"]).as_posix())
            check(digest(image_bytes) == document["image_sha256"], "Image digest differs from raw source ZIP.", identifier)
            check((store.root / document["original_path"]).read_bytes() == image_bytes, "Preserved original image bytes differ from raw source ZIP.", identifier)
            frame = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)
            canonical = cv2.imread(str(store.root / document["pixels_path"]), cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)
            check(frame is not None and canonical is not None and frame.shape[:2] == (image["height"], image["width"]) and np.array_equal(frame, canonical), "Canonical image pixels/dimensions differ from source image.", identifier)
            counts["images"] += 1
            image_yolo_compatible = True
            check({annotation["source_annotation_id"] for annotation in document["annotations"]} == set(source_annotations[image["id"]]), "Source annotations are missing or duplicated.", identifier)
            for annotation in document["annotations"]:
                original = source_annotations[image["id"]][annotation["source_annotation_id"]]
                category = source_categories[original["category_id"]]
                semantic = semantic_name(category["name"])
                registry = classes.get(annotation["class_id"], {})
                mapping = declared_mapping[original["category_id"]]
                check(annotation.get("status") == "manual_verified" and annotation.get("source") == "manual" and annotation.get("confidence") is None,
                      "Original manual annotation lost its verified manual provenance.", identifier, annotation["id"])
                check(annotation["original_annotation"] == original and annotation["source_category"] == category, "Original annotation/category metadata changed.", identifier, annotation["id"])
                check(registry.get("model_class_id") == SOURCE_NAME_TO_ID[semantic] and registry.get("source_name") == semantic and registry.get("kind") == "anatomy", "Source class semantics were mapped by numeric ID or to the wrong registry class.", identifier, annotation["id"])
                check(mapping["registry_class_id"] == annotation["class_id"] and mapping["model_class_id"] == SOURCE_NAME_TO_ID[semantic] and mapping["semantic_name"] == semantic and mapping["source_name"] == category["name"], "Published class mapping disagrees with saved annotation semantics.", identifier, annotation["id"])
                expected = official_mask(original["segmentation"], image["height"], image["width"])
                stored = segmentation_to_mask(annotation["segmentation"], image["height"], image["width"])
                png_path = store.root / annotation["mask_path"]
                png = cv2.imread(str(png_path), cv2.IMREAD_GRAYSCALE)
                check(np.array_equal(stored != 0, expected), "Stored segmentation pixels differ from official source COCO raster.", identifier, annotation["id"])
                check(png is not None and np.array_equal(png != 0, expected), "Saved PNG mask pixels differ from official source COCO raster.", identifier, annotation["id"])
                check(file_digest(png_path) == png_path.stem, "Immutable PNG mask digest is invalid.", identifier, annotation["id"])
                check(annotation["bbox"] == mask_bbox(stored) and annotation["area"] == int(np.count_nonzero(expected)), "Saved mask bounding box/area does not describe actual source pixels.", identifier, annotation["id"])
                counts["masks_vs_official_COCO"] += 1
                counts["PNG_masks_vs_official_COCO"] += 1
                counts["original_annotation_category_metadata"] += 1
                topology["rectangle_like_source_rings" if rectangle_like_source(original["segmentation"]) else "nonrectangular_source_segmentations"] += 1
                topology["masks_touching_image_border"] += int(np.any(expected[0]) or np.any(expected[-1]) or np.any(expected[:, 0]) or np.any(expected[:, -1]))
                topology["parts_without_whole_fish_association"] += int(annotation.get("parent_id") is None)
                # Exercise the actual lossless YOLO polygon helper. Successful
                # conversion establishes one component and no hole; inspect
                # failed masks separately without rerasterizing source polygons.
                try:
                    yolo_polygon(stored)
                    components, holes = 1, 0
                    topology["actual_yolo_single_ring_helper_passes"] += 1
                except ValueError as error:
                    image_yolo_compatible = False
                    _, hierarchy = cv2.findContours(stored.astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
                    parents = hierarchy[0, :, 3] if hierarchy is not None else np.array([], dtype=np.int32)
                    components, holes = int(np.count_nonzero(parents == -1)), int(np.count_nonzero(parents >= 0))
                    yolo_failures.append({"image_id": identifier, "source_annotation_id": original["id"], "annotation_id": annotation["id"],
                                          "components": components, "holes": holes, "reason": str(error)})
                component_counts[str(components)] += 1
                hole_counts[str(holes)] += 1
                topology["masks_with_disconnected_components"] += int(components > 1)
                topology["masks_with_holes"] += int(holes > 0)
                if document["split"] == "train" and group["protected_split"] == "train":
                    key = (semantic, identifier, annotation["source_annotation_id"])
                    expected_references[key] += 1
                    expected_reference_area[key] = annotation["area"] / (image["width"] * image["height"])
            yolo_compatible_images += int(image_yolo_compatible)
            if number % 25 == 0:
                print(f"Primary source parity: {number}/{len(selected)} images, {counts['masks_vs_official_COCO']} masks.", flush=True)
        descriptor_path = store.root / profile["reference_profile_path"]
        descriptor = json.loads(descriptor_path.read_bytes())
        check(file_digest(descriptor_path) == descriptor_path.name.split(".", 1)[0], "Training reference descriptor digest is invalid.")
        check(descriptor.get("dataset_id") == dataset_id and descriptor.get("source_splits") == ["train"] and descriptor.get("annotation_unit") == "fish_part" and descriptor.get("whole_fish_ground_truth_available") is False, "Training reference scope is incorrect.")
        check(descriptor.get("sources") == [{"path": profile["baseline_path"], "sha256": profile["baseline_sha256"]}], "Training reference descriptor points to a different immutable COCO source.")
        actual_references, leakage = Counter(), []
        for semantic, references in descriptor["classes"].items():
            for reference in references:
                key = (semantic, reference["image_id"], reference["annotation_id"])
                actual_references[key] += 1
                image = selected_by_id.get(reference["image_id"])
                if not image or image["split"] != "train" or image["metadata"]["protected_split"] != "train" or reference.get("split") != "train":
                    leakage.append(reference)
                check(key in expected_reference_area and reference["area_fraction"] == expected_reference_area.get(key), "Training reference area/annotation association is incorrect.", reference["image_id"])
        check(not leakage, "Training references contain validation/test protected images.")
        check(actual_references == expected_references, "Training reference descriptor omits or adds eligible source annotations.")
    after_sha = file_digest(zip_path)
    check(after_sha == before_sha, "Original source ZIP changed during read-only QA.")
    return {"dataset_id": dataset_id, "counts": dict(counts), "source_images": len(source_images),
            "source_annotations": sum(len(values) for values in source_annotations.values()),
            "source_categories": len(source_categories), "source_zip_sha256_before": before_sha,
            "source_zip_sha256_after": after_sha, "group_protection": group_summary,
            "class_coverage_by_protected_split": {split: dict(values) for split, values in class_coverage.items()},
            "missing_model_classes_by_protected_split": {split: sorted(set(SOURCE_NAME_TO_ID) - set(values)) for split, values in class_coverage.items()},
            "source_mask_topology": {**dict(topology), "foreground_component_distribution": dict(component_counts),
                "hole_distribution": dict(hole_counts), "method": "official source raster; actual yolo_polygon helper; RETR_CCOMP hierarchy for failed conversions",
                "source_geometry_policy": "Self-touching source rings retain official COCO pixel semantics; topology is reported without declaring source annotations invalid."},
            "yolo_segmentation_suitability": {"annotations_passed": topology["actual_yolo_single_ring_helper_passes"],
                "annotations_requiring_COCO": len(yolo_failures), "images_with_all_annotations_suitable": yolo_compatible_images,
                "all_primary_images_losslessly_representable": not yolo_failures,
                "failure_reasons": dict(Counter(failure["reason"] for failure in yolo_failures)), "failures": yolo_failures,
                "scope": "Actual per-mask conversion helper exercised; no export archive is written by this read-only check."},
            "reference_descriptor": {"source_splits": descriptor["source_splits"], "eligible_examples": sum(expected_references.values()),
                "actual_examples": sum(actual_references.values()), "eligible_images": len({key[1] for key in expected_references}),
                "holdout_leaks": leakage}, "elapsed_seconds": round(monotonic() - started, 3)}


def verify_secondary(store, documents, revisions, errors):
    secondary = [document for document in documents if document.get("baseline") and not document["baseline"].get("source_zip_sha256")]
    sources = {split: json.loads((SECONDARY / split / "_annotations.coco.json").read_bytes()) for split in ("train", "valid", "test")}
    annotations = {split: {annotation["id"]: annotation for annotation in source["annotations"]} for split, source in sources.items()}
    checked = 0
    def check(condition, message, document):
        if not condition:
            errors.append({"scope": "secondary", "image_id": document["id"], "message": message})
    if len(secondary) != 910:
        errors.append({"scope": "secondary", "message": "Secondary dataset image count differs from original 910."})
    for number, document in enumerate(secondary, 1):
        check(document["revision"] == 1 and document["status"] == "manual_verified", "Secondary original revision/status changed.", document)
        old = revisions.get((document["id"], 1))
        check(old is not None and json.loads(old) == document, "Current secondary document differs from immutable revision one.", document)
        check(sum(key[0] == document["id"] for key in revisions) == 1, "Secondary original acquired another revision.", document)
        for annotation in document["annotations"]:
            original = annotations[document["split"]][annotation["source_annotation_id"]]
            expected = coco_segmentation_to_mask(original["segmentation"], document["height"], document["width"]) != 0
            current = segmentation_to_mask(annotation["segmentation"], document["height"], document["width"])
            png = cv2.imread(str(store.root / annotation["mask_path"]), cv2.IMREAD_GRAYSCALE)
            check(annotation["original_annotation"] == original and annotation["class_id"] == original["category_id"], "Secondary original annotation/class metadata changed.", document)
            check(np.array_equal(expected, current != 0) and png is not None and np.array_equal(expected, png != 0), "Secondary original mask pixels changed.", document)
            checked += 1
        if number % 200 == 0:
            print(f"Secondary preservation: {number}/{len(secondary)} images.", flush=True)
    source_snapshot = json.loads((ROOT / "results/qa/annotation_workflow/source_integrity_before.json").read_bytes())
    changed = [entry["path"] for entry in source_snapshot["files"] if not (ROOT / entry["path"]).is_file() or file_digest(ROOT / entry["path"]) != entry["sha256"]]
    if changed:
        errors.append({"scope": "secondary", "message": "Original secondary source files changed.", "paths": changed})
    if checked != 9723:
        errors.append({"scope": "secondary", "message": "Secondary annotation count differs from original 9723."})
    return {"images_checked": len(secondary), "masks_and_PNGs_checked": checked, "source_files_checked": len(source_snapshot["files"]),
            "changed_source_files": changed, "revision_one_document_comparisons": len(secondary)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wait-seconds", type=int, default=0, help="Wait read only for an already-running import, without starting one.")
    arguments = parser.parse_args()
    cv2.setNumThreads(1)
    tests = self_tests()
    store = ReadOnlyStore(WORKSPACE, SECONDARY)
    profile = ready_profile(store, max(0, arguments.wait_seconds))
    print("Primary import ready; beginning official COCO pixel parity and source protection checks.", flush=True)
    with store._db() as connection:
        raw_documents = connection.execute("SELECT id,document FROM images ORDER BY id").fetchall()
        documents = [json.loads(serialized) for _, serialized in raw_documents]
        revisions = {(image_id, revision): serialized for image_id, revision, serialized in connection.execute("SELECT image_id,revision,document FROM revisions")}
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        classes = {class_id: json.loads(serialized) for class_id, serialized in connection.execute("SELECT id,document FROM classes")}
    errors = []
    revision_artifacts_checked = 0
    for (image_id, revision), serialized in revisions.items():
        data = serialized.encode("utf-8")
        artifact = store.root / "revisions" / (digest(data) + ".json")
        if not artifact.is_file() or artifact.read_bytes() != data:
            errors.append({"scope": "workspace", "image_id": image_id, "revision": revision,
                           "message": "Immutable revision JSON artifact is missing or corrupt."})
        revision_artifacts_checked += 1
    primary = verify_primary(store, profile, documents, classes, errors)
    secondary = verify_secondary(store, documents, revisions, errors)
    with store._db() as connection:
        after_documents = connection.execute("SELECT id,document FROM images ORDER BY id").fetchall()
        after_revisions = {(image_id, revision): serialized for image_id, revision, serialized in connection.execute("SELECT image_id,revision,document FROM revisions")}
    if raw_documents != after_documents or revisions != after_revisions:
        errors.append({"scope": "workspace", "message": "Documents/revisions changed while read-only QA ran."})
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "verification_mode": "SQLite mode=ro plus query_only; source ZIP and source directories read only",
              "official_mask_reference": "installed pycocotools; QA-only dependency", "sqlite_integrity": integrity,
              "workspace_image_count": len(documents), "workspace_revision_count": len(revisions), "primary": primary, "secondary": secondary,
              "self_tests": tests,
              "immutable_revision_JSON_artifacts_checked": revision_artifacts_checked,
              "documents_and_revisions_unchanged_during_QA": raw_documents == after_documents and revisions == after_revisions,
              "errors": errors, "passed": integrity == "ok" and not errors,
              "limitations": ["Manual part-mask fidelity is verified; whole-fish ownership remains unverified because no such source ground truth exists.",
                              "Protected split grouping is conservative and preserves original source split provenance separately.",
                              "Structural source certification does not establish full-class training/evaluation coverage; consult the reported missing classes for every protected split.",
                              "COCO retains all original mask pixels. YOLO single-ring suitability is reported separately and can be incomplete even when source parity passes.",
                              "No model accuracy improvement, inference performance, or human correction-rate claim is made."]}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "primary": primary["counts"], "secondary": secondary, "errors": errors}, indent=2), flush=True)
    assert report["passed"], "Primary integrity verification failed; inspect report."


if __name__ == "__main__":
    main()
