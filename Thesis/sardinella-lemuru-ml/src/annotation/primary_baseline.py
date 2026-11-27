"""Read-only, resumable import of the user-selected local COCO ZIP baseline.

The original archive and COCO metadata are immutable artifacts. Dataset selection
is registry metadata, so selecting a baseline never rewrites older documents.
"""
from __future__ import annotations

from copy import deepcopy
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import zipfile

import numpy as np

from src.annotation.masks import coco_segmentation_to_mask, mask_to_rle
from src.preprocessing.audit_v7_exports import SOURCE_NAME_TO_ID

LEGACY_DATASET_ID = "v2-coco-v7"
PRIMARY_META = "primary_learning_dataset"
REGISTRY_META = "annotation_datasets"
# Explicit source-taxonomy aliases. Numeric COCO IDs are never semantic IDs.
CATEGORY_ALIASES = {f"Class_C_{part}": f"Grade_C_{part}" for part in ("Body", "Head", "Tail")}


def dataset_id(document):
    """Resolve a document's dataset without changing historical revisions."""
    return (document.get("dataset_id") or (document.get("baseline") or {}).get("dataset_id")
            or (document.get("metadata") or {}).get("dataset_id")
            or (LEGACY_DATASET_ID if document.get("baseline") else None))


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _meta(db, key, default=None):
    row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def primary_profile(store):
    with store.connection() as db:
        return _meta(db, PRIMARY_META)


def datasets(store):
    """Return the canonical dataset registry and current baseline selection."""
    with store.connection() as db:
        entries = _meta(db, REGISTRY_META, [])
        profile = _meta(db, PRIMARY_META)
        has_legacy = False
        for (serialized,) in db.execute("SELECT document FROM images"):
            if dataset_id(json.loads(serialized)) == LEGACY_DATASET_ID:
                has_legacy = True
                break
    if has_legacy and not any(e["id"] == LEGACY_DATASET_ID for e in entries):
        entries.append({"id": LEGACY_DATASET_ID, "name": "V2 COCO v7 (secondary)",
                        "source_type": "coco_directory", "source_path": str(store.manual_source),
                        "source_sha256": None, "training_certified": False,
                        "reference_eligible": True, "status": "ready"})
    selected = profile.get("dataset_id") if profile else (LEGACY_DATASET_ID if has_legacy else None)
    return {"datasets": [{**deepcopy(e), "primary": e["id"] == selected} for e in entries],
            "primary_dataset_id": selected}


def _set_profile(store, profile):
    with store.connection(write=True) as db:
        entries = _meta(db, REGISTRY_META, [])
        entry = {"id": profile["dataset_id"], **{k: deepcopy(v) for k, v in profile.items() if k != "dataset_id"}}
        entries = [e for e in entries if e["id"] != entry["id"]] + [entry]
        db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (REGISTRY_META, _json(entries)))
        db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (PRIMARY_META, _json(profile)))


def _sha_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _archive_artifact(store, source, digest):
    """Publish a complete fsynced archive without reading it all into memory."""
    destination = store.root / "baselines" / f"{digest}.zip"
    if destination.exists():
        if _sha_file(destination) != digest:
            raise ValueError("The immutable baseline ZIP snapshot is corrupt.")
        return destination.relative_to(store.root).as_posix()
    descriptor, temporary = tempfile.mkstemp(prefix=".writing-zip-", dir=destination.parent)
    try:
        with source.open("rb") as input_handle, os.fdopen(descriptor, "wb") as output:
            shutil.copyfileobj(input_handle, output, length=1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        if _sha_file(Path(temporary)) != digest:
            raise ValueError("The source archive changed while being snapshotted.")
        try:
            os.link(temporary, destination)
        except FileExistsError:
            if _sha_file(destination) != digest:
                raise ValueError("The immutable baseline ZIP snapshot is corrupt.")
    finally:
        Path(temporary).unlink(missing_ok=True)
    return destination.relative_to(store.root).as_posix()


def _member_name(value):
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError("ZIP member paths must be nonempty relative POSIX paths.")
    path = PurePosixPath(value)
    if path.is_absolute() or any(p in {"..", "."} or ":" in p for p in path.parts):
        raise ValueError("ZIP member path leaves its dataset.")
    return path.as_posix()


def _members(archive):
    result, total = {}, 0
    for member in archive.infolist():
        name = _member_name(member.filename)
        if stat.S_ISLNK(member.external_attr >> 16) or member.flag_bits & 1:
            raise ValueError("Encrypted ZIP members and symbolic links are unsupported.")
        if name in result:
            raise ValueError("The ZIP contains duplicate member paths.")
        if member.file_size > 128 * 1024 * 1024:
            raise ValueError("A ZIP member exceeds the 128 MiB safety limit.")
        total += member.file_size
        if total > 8 * 1024 * 1024 * 1024 or len(result) >= 100_000:
            raise ValueError("The ZIP exceeds dataset import safety limits.")
        result[name] = member
    return result


def _source(archive, members):
    matches = [name for name in members if PurePosixPath(name).name == "clean_segmentation.json"]
    if len(matches) != 1:
        raise ValueError("Expected exactly one clean_segmentation.json COCO source.")
    name = matches[0]
    raw = archive.read(members[name])
    source = json.loads(raw)
    if not isinstance(source, dict) or any(not isinstance(source.get(k), list) for k in ("images", "annotations", "categories")):
        raise ValueError("The COCO source requires images, annotations, and categories lists.")
    for key in ("images", "annotations", "categories"):
        ids = [item.get("id") for item in source[key] if isinstance(item, dict)]
        if len(ids) != len(source[key]) or any(isinstance(i, bool) or not isinstance(i, (int, str)) for i in ids) or len(set(ids)) != len(ids):
            raise ValueError(f"COCO {key} IDs must be unique integers or strings.")
    if not source["images"]:
        raise ValueError("The primary dataset has no images.")
    image_ids = {i["id"] for i in source["images"]}
    category_ids = {c["id"] for c in source["categories"]}
    if any(a.get("image_id") not in image_ids or a.get("category_id") not in category_ids for a in source["annotations"]):
        raise ValueError("A COCO annotation references an absent image or category.")
    return name, raw, source


def _category_mapping(store, categories):
    """Match source names to immutable model mappings; retain source IDs apart."""
    from src.annotation.store import AnnotationError, COLORS
    result, mappings = {}, []
    with store.connection(write=True) as db:
        entries = [json.loads(r[0]) for r in db.execute("SELECT document FROM classes ORDER BY id")]
        changed = False
        for category in categories:
            name = category.get("name")
            semantic = CATEGORY_ALIASES.get(name, name)
            if semantic not in SOURCE_NAME_TO_ID:
                raise AnnotationError(f"Unsupported primary source category {name!r}; configure an explicit semantic mapping.")
            model_id = SOURCE_NAME_TO_ID[semantic]
            matches = [c for c in entries if c.get("model_class_id") == model_id and c.get("source_name") == semantic]
            if len(matches) > 1:
                raise AnnotationError("The class registry contains an ambiguous model class mapping.")
            if matches:
                entry = matches[0]
            else:
                next_row = db.execute("SELECT value FROM meta WHERE key='next_class_id'").fetchone()
                class_id = max(max((c["id"] for c in entries), default=-1) + 1,
                               int(next_row[0]) if next_row else 0)
                db.execute("INSERT OR REPLACE INTO meta VALUES ('next_class_id',?)", (str(class_id + 1),))
                parts = semantic.split("_")
                entry = {"id": class_id, "name": name, "source_name": semantic, "kind": "anatomy",
                         "color": COLORS[class_id % len(COLORS)], "active": True, "region": parts[-1].lower(),
                         "quality_grade": "_".join(parts[:-1]), "model_class_id": model_id}
                entries.append(entry)
                changed = True
            if not entry.get("active") or entry.get("kind") != "anatomy":
                raise AnnotationError("Primary source taxonomy maps to an inactive or incompatible registry class.")
            if name in CATEGORY_ALIASES and entry["name"] == semantic:
                if any(c["id"] != entry["id"] and c["name"].casefold() == name.casefold() for c in entries):
                    raise AnnotationError("Primary source class alias conflicts with an existing class name.")
                entry["name"] = name
                changed = True
            db.execute("INSERT OR REPLACE INTO classes VALUES (?,?)", (entry["id"], _json(entry)))
            result[category["id"]] = entry["id"]
            mappings.append({"source_category_id": category["id"], "source_name": name,
                             "semantic_name": semantic, "registry_class_id": entry["id"], "model_class_id": model_id})
        if changed:
            db.execute("UPDATE meta SET value=CAST(value AS INTEGER)+1 WHERE key='classes_revision'")
    return result, mappings


def _auxiliary(archive, members, source_name, store):
    directory = PurePosixPath(source_name).parent
    values, artifacts = {}, {}
    for name in ("provenance.json", "cleaning_report.json", "near_duplicate_candidates.csv", "README.txt", "issues.csv"):
        relative = (directory / name).as_posix()
        if relative not in members:
            continue
        raw = archive.read(members[relative])
        artifacts[name] = store._artifact("baselines", raw, "." + name)
        if name.endswith(".json"):
            values[name] = json.loads(raw)
        elif name == "near_duplicate_candidates.csv":
            values[name] = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    provenance = values.get("provenance.json", [])
    if not isinstance(provenance, list) or any(not isinstance(p, dict) for p in provenance):
        raise ValueError("Source provenance must be a list of image records.")
    return values, artifacts


def _group_metadata(images, provenance, pairs, zip_digest):
    """Conservatively keep declared near duplicates/capture variants together."""
    by_path = {i["file_name"]: i for i in images}
    provenance_by_path = {p.get("image"): p for p in provenance}
    parents = {path: path for path in by_path}
    def find(path):
        while parents[path] != path:
            parents[path] = parents[parents[path]]
            path = parents[path]
        return path
    def union(a, b):
        if a in parents and b in parents:
            first, second = find(a), find(b)
            parents[max(first, second)] = min(first, second)
    captures = {}
    splits = {}
    for path in by_path:
        p = provenance_by_path.get(path, {})
        raw_splits = p.get("original_splits", [])
        if not isinstance(raw_splits, list):
            raise ValueError("Provenance original_splits must be a list.")
        normalized = {"valid" if s in {"val", "validation", "valid"} else s for s in raw_splits}
        if normalized - {"train", "valid", "test"}:
            raise ValueError("Provenance contains an unsupported original split.")
        splits[path] = next((s for s in ("test", "valid", "train") if s in normalized), None)
        for original in p.get("sources", []):
            if not isinstance(original, str):
                raise ValueError("Provenance image sources must be strings.")
            capture = re.sub(r"\.rf\.[^.]+(?=\.[^.]+$)", "", PurePosixPath(original).name)
            capture = re.sub(r"_(jpg|jpeg|png)(?=\.)", "", capture, flags=re.I)
            if capture in captures:
                union(path, captures[capture])
            else:
                captures[capture] = path
    for pair in pairs:
        union(pair.get("image_1"), pair.get("image_2"))
    grouped = {}
    for path in by_path:
        grouped.setdefault(find(path), []).append(path)
    result = {}
    for members in grouped.values():
        group_id = "primary-" + hashlib.sha256((zip_digest + ":" + min(members)).encode()).hexdigest()[:24]
        holdout = next((s for s in ("test", "valid", "train") if s in {splits[p] for p in members}), None)
        for path in members:
            result[path] = {"source_provenance": deepcopy(provenance_by_path.get(path, {})),
                            "leakage_group_id": group_id, "dataset_group_id": group_id,
                            "protected_split": holdout, "original_split": splits[path],
                            "near_duplicate_or_capture_group_size": len(members)}
    return result


def import_primary_zip(store, path, *, dataset_id=None, name="Fish Annotations Cleaned"):
    """Index a local manual baseline, retaining every original byte and revision.

    Returns imported/skipped counts, image IDs, source mappings, per-image errors,
    split counts and the final primary profile. Interrupted imports are resumable.
    """
    from src.annotation.store import AnnotationError
    path = Path(path).resolve()
    store._initialize()
    if not path.is_file():
        raise AnnotationError("Primary baseline ZIP does not exist.")
    digest = _sha_file(path)
    selected_id = dataset_id or "fish-annotations-cleaned-" + digest[:12]
    if not isinstance(selected_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}", selected_id):
        raise AnnotationError("Dataset ID must be a safe nonempty identifier.")
    profile = {"dataset_id": selected_id, "name": name, "source_type": "coco_zip", "source_path": str(path),
               "source_sha256": digest, "training_certified": False, "reference_eligible": False, "status": "importing"}
    imported, skipped, errors, counts = [], [], [], {}
    reference_classes = {}

    def reference_examples(document):
        if (document.get("split") != "train" or document.get("status") != "manual_verified" or
                document.get("metadata", {}).get("protected_split") in {"valid", "test"}):
            return
        for annotation in document["annotations"]:
            category = annotation.get("source_category", {})
            source_name = category.get("name")
            semantic = CATEGORY_ALIASES.get(source_name, source_name)
            if semantic not in SOURCE_NAME_TO_ID:
                continue
            reference_classes.setdefault(semantic, []).append({
                "annotation_id": annotation.get("source_annotation_id"), "image_id": document["id"],
                "area_fraction": annotation["area"] / (document["width"] * document["height"]), "split": "train"})
    selected = False
    try:
        # All subsequent reads use one immutable snapshot, even if a separate
        # process changes the user-owned source ZIP during a lengthy import.
        archive_path = _archive_artifact(store, path, digest)
        with zipfile.ZipFile(store.root / archive_path) as archive:
            members = _members(archive)
            source_name, raw, source = _source(archive, members)
            # Reject unknown semantics before changing the selected baseline.
            if any(CATEGORY_ALIASES.get(c.get("name"), c.get("name")) not in SOURCE_NAME_TO_ID for c in source["categories"]):
                raise AnnotationError("Primary source includes an unknown class; no numeric-ID remapping is permitted.")
            # Invalid paths fail the whole archive before any annotation is indexed.
            for image in source["images"]:
                _member_name(image.get("file_name"))
            with store.connection() as db:
                registered = next((e for e in _meta(db, REGISTRY_META, []) if e["id"] == selected_id), None)
                if registered and registered.get("source_sha256") != digest:
                    raise AnnotationError("Dataset ID already belongs to a different immutable source; select a new dataset ID.")
            _set_profile(store, profile)
            selected = True
            baseline_path = store._artifact("baselines", raw, ".coco.json")
            baseline_hash = hashlib.sha256(raw).hexdigest()
            auxiliary, auxiliary_paths = _auxiliary(archive, members, source_name, store)
            mapping, mappings = _category_mapping(store, source["categories"])
            groups = _group_metadata(source["images"], auxiliary.get("provenance.json", []),
                                     auxiliary.get("near_duplicate_candidates.csv", []), digest)
            source_categories = {c["id"]: c for c in source["categories"]}
            annotations_by_image = {}
            for annotation in source["annotations"]:
                annotations_by_image.setdefault(annotation["image_id"], []).append(annotation)
            source_directory = PurePosixPath(source_name).parent
            for image in source["images"]:
                key = f"primary-zip:{digest}:{image['id']}"
                image_id = "manual-zip-" + hashlib.sha256(key.encode()).hexdigest()[:24]
                try:
                    with store.connection(write=True) as db:
                        old = db.execute("SELECT image_id FROM imports WHERE import_key=?", (key,)).fetchone()
                        if old:
                            existing = store._get(db, old[0])
                            if (existing.get("baseline") or {}).get("source_zip_sha256") != digest:
                                raise AnnotationError("Import identity conflicts with another immutable baseline.")
                            skipped.append(old[0])
                            errors.extend({"image_id": existing["id"], "filename": existing["filename"], **e}
                                          for e in existing.get("metadata", {}).get("source_validation_errors", []))
                            reference_examples(existing)
                            split = existing.get("split")
                            counts[split or "unspecified"] = counts.get(split or "unspecified", 0) + 1
                            continue
                        member_name = (source_directory / image["file_name"]).as_posix()
                        if member_name not in members:
                            raise AnnotationError("COCO references an image missing from the source ZIP.")
                        document = store._image_document(archive.read(members[member_name]), image["file_name"], image_id)
                        if [document["width"], document["height"]] != [image.get("width"), image.get("height")]:
                            raise AnnotationError("Image dimensions disagree with original COCO metadata.")
                        metadata = groups[image["file_name"]]
                        document.update({"dataset_id": selected_id, "source_record": deepcopy(image),
                                         "metadata": {"dataset_id": selected_id, **metadata},
                                         "split": metadata["original_split"], "status": "manual_verified"})
                        document["baseline"] = {"path": baseline_path, "sha256": baseline_hash, "source_image_id": image["id"],
                                                "revision": 1, "source_path": str(path), "dataset_id": selected_id,
                                                "source_zip_sha256": digest, "source_zip_path": archive_path,
                                                "source_entry": source_name, "auxiliary_artifacts": auxiliary_paths}
                        annotation_records, image_errors = [], []
                        for original in annotations_by_image.get(image["id"], []):
                            annotation = {"id": f"manual-{original['id']}", "class_id": mapping[original["category_id"]],
                                          "parent_id": None, "confidence": None, "bbox": deepcopy(original.get("bbox")),
                                          "flags": [], "source_annotation_id": original["id"],
                                          "source_category": deepcopy(source_categories[original["category_id"]]),
                                          "original_annotation": deepcopy(original)}
                            try:
                                mask = coco_segmentation_to_mask(original.get("segmentation"), document["height"], document["width"])
                                if not np.any(mask):
                                    raise ValueError("Segmentation mask has no foreground pixels.")
                                bbox = original.get("bbox")
                                if (not isinstance(bbox, list) or len(bbox) != 4 or
                                    any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in bbox) or
                                    min(bbox) < 0 or min(bbox[2:]) <= 0 or bbox[0] + bbox[2] > document["width"] + 1e-6 or bbox[1] + bbox[3] > document["height"] + 1e-6):
                                    raise ValueError("Original source bounding box is invalid or outside the image.")
                                annotation["segmentation"] = mask_to_rle(mask)
                                annotation_records.append(annotation)
                            except (TypeError, ValueError) as error:
                                image_errors.append({"annotation_id": original["id"], "message": str(error)})
                        if not annotation_records:
                            image_errors.append({"message": "Image has no valid source instance masks."})
                        document["annotations"] = store._normal_annotations(annotation_records, document, trusted_source="manual")
                        if image_errors:
                            document["status"] = "unreviewed"
                            document["metadata"]["source_validation_errors"] = image_errors
                            errors.extend({"image_id": image_id, "filename": image["file_name"], **e} for e in image_errors)
                        document["metadata"]["source_annotation_count"] = len(annotations_by_image.get(image["id"], []))
                        store._persist(db, document)
                        db.execute("INSERT INTO imports VALUES (?,?)", (key, image_id))
                        imported.append(image_id)
                        reference_examples(document)
                        split = document.get("split")
                        counts[split or "unspecified"] = counts.get(split or "unspecified", 0) + 1
                except (OSError, AnnotationError, KeyError, TypeError, ValueError) as error:
                    errors.append({"image_id": image_id, "filename": image.get("file_name"), "message": str(error)})
            # Certification means structurally valid manual part labels, not fish
            # ownership, model quality, or an independent evaluation claim.
            reference_descriptor = {"schema_version": "manual-anatomy-reference-v1", "dataset_id": selected_id,
                                    "annotation_unit": "fish_part", "whole_fish_ground_truth_available": False,
                                    "source_splits": ["train"], "sources": [{"path": baseline_path, "sha256": baseline_hash}],
                                    "classes": reference_classes}
            reference_path = store._artifact("baselines", _json(reference_descriptor).encode("utf-8"), ".reference.json")
            profile.update({"status": "ready" if not errors else "needs_review", "reference_eligible": not errors,
                            "training_certified": not errors, "source_entry": source_name,
                            "source_image_count": len(source["images"]), "source_annotation_count": len(source["annotations"]),
                            "indexed_image_count": len(imported) + len(skipped), "split_counts": counts,
                            "category_mapping": mappings, "source_zip_artifact": archive_path,
                            "baseline_path": baseline_path, "baseline_sha256": baseline_hash,
                            "auxiliary_artifacts": auxiliary_paths, "source_validation_error_count": len(errors),
                            "reference_profile_path": reference_path,
                            "annotation_scope": "manual_anatomical_parts; whole_fish_ownership_unverified"})
            _set_profile(store, profile)
    except (OSError, zipfile.BadZipFile, KeyError, TypeError, ValueError) as error:
        if selected:
            profile.update({"status": "failed", "error": str(error), "reference_eligible": False, "training_certified": False})
            _set_profile(store, profile)
        if isinstance(error, AnnotationError):
            raise
        raise AnnotationError(f"Primary dataset import failed: {error}") from error
    return {"imported": len(imported), "skipped": len(skipped), "image_ids": imported,
            "errors": errors, "root": str(store.root), "dataset_id": selected_id, "profile": profile}
