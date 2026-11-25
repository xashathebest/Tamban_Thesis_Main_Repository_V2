"""Human dataset labels and feature calibration are separate evidence sources."""
import json

import pytest

from src.evaluation.calibrate_decision_fusion import audit_existing


def write_dataset(root, *, declaration=True, directory="reference", part_identity=False):
    annotations = [{"id": 1, "image_id": 1, "category_id": 5, "bbox": [2, 3, 8, 6],
                    "segmentation": [[2, 3, 10, 3, 10, 9, 2, 9, 2, 3]]}]
    if part_identity:
        annotations[0]["fish_id"] = "declared-fish-1"
    data = {"images": [{"id": 1, "file_name": "annotated.jpg", "width": 20, "height": 20}],
            "categories": [{"id": 5, "name": "Grade_A_Body"}], "annotations": annotations}
    path = root / directory / "train/_annotations.coco.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    if declaration:
        config = root / "configs/dataset_class_reference.json"
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({"schema_version": "dataset_class_reference_v1",
            "dataset_directory": "reference", "user_confirmed_label_reference": True,
            "class_source": "expert_provided_fish_classes"}), encoding="utf-8")
    return path


def test_expert_dataset_labels_exist_without_application_manual_reviews(tmp_path):
    path = write_dataset(tmp_path)
    before = path.read_bytes()
    report = audit_existing(tmp_path)
    assert report["dataset_label_reference_available"] is True
    assert report["class_label_reference_count"] == 1
    assert report["human_review_count"] == 0
    assert report["runtime_manual_reviews_required_for_dataset_labels"] is False
    assert report["datasets"][0]["user_confirmed_class_reference"] is True
    assert report["datasets"][0]["grade_annotation_counts"]["Class A"] == 1
    assert path.read_bytes() == before


def test_label_provenance_does_not_approve_rectangles_or_manufacture_calibration(tmp_path):
    write_dataset(tmp_path)
    report = audit_existing(tmp_path)
    dataset = report["datasets"][0]
    assert dataset["all_part_annotations_are_rectangles"] is True
    assert dataset["rectangular_part_annotation_count"] == 1
    assert dataset["part_annotations_with_fish_identity"] == 0
    assert dataset["whole_fish_feature_reference_records"] == 0
    assert dataset["missing_reference_grades"] == ["Class B", "Class C", "Rejected"]
    assert report["source_bound_feature_records"] == 0 and report["calibration_ready"] is False
    assert not (tmp_path / "configs/decision_fusion_calibration.json").exists()


@pytest.mark.parametrize("declaration,directory", [(False, "reference"), (True, "another-dataset")])
def test_provenance_is_never_inferred_or_applied_to_a_different_dataset(tmp_path, declaration, directory):
    write_dataset(tmp_path, declaration=declaration, directory=directory)
    report = audit_existing(tmp_path)
    assert report["dataset_label_reference_available"] is True
    assert report["datasets"][0]["user_confirmed_class_reference"] is False


def test_explicit_fish_links_are_counted_without_substituting_annotation_ids(tmp_path):
    write_dataset(tmp_path, part_identity=True)
    dataset = audit_existing(tmp_path)["datasets"][0]
    assert dataset["part_annotations_with_fish_identity"] == 1
    assert dataset["specimen_ids_present"] is False


def test_different_part_grades_in_one_image_remain_independent_references(tmp_path):
    path = write_dataset(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["categories"] = [{"id": 1, "name": "Grade_A_Head"},
                          {"id": 2, "name": "Grade_B_Body"},
                          {"id": 3, "name": "Grade_C_Tail"}]
    original = data["annotations"][0]
    data["annotations"] = [{**original, "id": identity, "category_id": identity} for identity in (1, 2, 3)]
    path.write_text(json.dumps(data), encoding="utf-8")
    dataset = audit_existing(tmp_path)["datasets"][0]
    assert dataset["reference_unit"] == "fish_part"
    assert dataset["part_grade_reference_counts"] == {
        "Head": {"Class A": 1, "Class B": 0, "Class C": 0, "Rejected": 0},
        "Body": {"Class A": 0, "Class B": 1, "Class C": 0, "Rejected": 0},
        "Tail": {"Class A": 0, "Class B": 0, "Class C": 1, "Rejected": 0},
    }
    assert dataset["whole_fish_annotation_reference_count"] == 0
