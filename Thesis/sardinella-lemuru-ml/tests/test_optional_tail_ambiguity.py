"""Only required-region ambiguity vetoes the versioned optional-Tail policy."""
from pathlib import Path

import numpy as np
import pytest

from src.inference.association import ParentAnchor, associate_parts_to_parents
from src.inference.grading_engine import GradingConfig, WeightedGradingEngine
from src.inference.part_types import PartDetection
from src.inference.preprocessing import RuntimeMaskContext
from src.inference.yolo_quality_model import YoloQualityModel


PARENTS = (ParentAnchor(1, (20, 40, 260, 100), .99), ParentAnchor(2, (160, 40, 400, 100), .99))


def fixture(ambiguous_region="Tail", *, mode="tail_optional_v1"):
    boxes = {"Body": (90, 50, 135, 90), "Head": (35, 54, 68, 84), "Tail": (190, 58, 225, 82)}
    boxes[ambiguous_region] = (190, 58, 225, 82)
    parts = (PartDetection.from_source_class(0, .87, boxes["Body"]),
             PartDetection.from_source_class(1, .79, boxes["Head"]),
             PartDetection.from_source_class(11, .99, boxes["Tail"]))
    # The real association scorer, not a hand-authored ambiguity flag, creates
    # the competing-parent result. Both required regions otherwise belong to 1.
    rows = associate_parts_to_parents(parts, PARENTS)
    assert any(row.part.region == ambiguous_region and row.status == "AMBIGUOUS" for row in rows)
    model = YoloQualityModel(Path("recorded-parts-only.pt"), device="cpu",
                             model_id="optional-tail-ambiguity-test", quality_inference_mode="full_frame",
                             grading_engine=WeightedGradingEngine(GradingConfig(
                                 grading_mode=mode, image_diagnostics_enabled=False)))
    model.model = object()
    model._infer_parts = lambda _: (list(parts), list(parts))
    frame = np.random.default_rng(3).integers(30, 220, size=(160, 440, 3), dtype=np.uint8)
    return model, frame, parts


def observe(model, frame, *, stabilize=False, frame_id="tail-ambiguity-1"):
    masks = RuntimeMaskContext(frame, frame_id=frame_id, backend="geometry_only")
    result = model.predict_full_frame(frame, PARENTS, stabilize=stabilize,
                                      frame_id=frame_id, mask_context=masks)[1][0]
    assert masks.diagnostics()["grabcut_executions"] == 0
    return result


@pytest.mark.parametrize("stabilize", [False, True])
def test_ambiguous_optional_tail_preserves_required_evidence_and_redistributes(stabilize):
    model, frame, raw = fixture()
    first = observe(model, frame, stabilize=stabilize)
    result = observe(model, frame, stabilize=True, frame_id="tail-ambiguity-2") if stabilize else first
    assert result.quality == "Class A"
    assert result.quality_confidence == pytest.approx(.84)
    assert result.analysis["weighted_scores"]["Class A"] == pytest.approx(.84)
    assert result.analysis["weighted_scores"]["Rejected"] == 0
    assert result.analysis["effective_weights"]["Body"] == pytest.approx(.625)
    assert result.analysis["effective_weights"]["Head"] == pytest.approx(.375)
    assert result.analysis["effective_weights"]["Tail"] == 0
    assert result.analysis["quality_inference"]["association"]["ambiguous"] is True
    assert "UG_ASSOCIATION_AMBIGUOUS" not in result.analysis["reason_codes"]
    assert [part.region for part in result.parts] == ["Body", "Head"]
    assert [part.confidence for part in result.parts] == [raw[0].confidence, raw[1].confidence]
    if stabilize:
        assert first.analysis["final_grade"] == "Ungraded"  # Existing distinct-frame evidence gate.


@pytest.mark.parametrize("region", ["Head", "Body"])
def test_required_region_ambiguity_still_prevents_a_tail_optional_verdict(region):
    model, frame, _ = fixture(region)
    result = observe(model, frame)
    assert result.analysis["final_grade"] == "Ungraded"
    assert "UG_ASSOCIATION_AMBIGUOUS" in result.analysis["reason_codes"]
    assert result.analysis["quality_inference"]["association"]["ambiguous"] is True


@pytest.mark.parametrize("mode", ["strict", "standard", "two_part_v1"])
def test_legacy_modes_retain_global_association_ambiguity_safeguard(mode):
    model, frame, _ = fixture(mode=mode)
    result = observe(model, frame)
    assert result.analysis["final_grade"] == "Ungraded"
    assert "UG_ASSOCIATION_AMBIGUOUS" in result.analysis["reason_codes"]
