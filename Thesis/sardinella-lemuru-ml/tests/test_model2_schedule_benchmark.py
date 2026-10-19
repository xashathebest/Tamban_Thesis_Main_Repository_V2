from __future__ import annotations

import json

import pytest

from src.evaluation.model2_schedule_benchmark import read_manifest


def test_manifest_resolves_and_hashes_clip_without_inventing_truth(tmp_path):
    (tmp_path / "clip.mp4").write_bytes(b"fixture")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"resolution": [640, 480], "clips": [{"id": "sample", "path": "clip.mp4"}]}))
    clips, resolution = read_manifest(manifest)
    assert resolution == (640, 480)
    assert clips[0]["path"] == str(tmp_path / "clip.mp4")
    assert len(clips[0]["sha256"]) == 64
    assert clips[0].get("expert_crossings") is None


def test_manifest_requires_blind_provenance_for_expert_counts(tmp_path):
    (tmp_path / "clip.mp4").write_bytes(b"fixture")
    manifest = tmp_path / "manifest.json"
    clip = {"id": "sample", "path": "clip.mp4", "expert_crossings": 2}
    manifest.write_text(json.dumps({"resolution": [640, 480], "clips": [clip]}))
    with pytest.raises(ValueError, match="reviewer"):
        read_manifest(manifest)
    clip.update(expert_reviewer="reviewer", truth_reference="independent-annotation", system_prediction_visible=False)
    manifest.write_text(json.dumps({"resolution": [640, 480], "clips": [clip]}))
    assert read_manifest(manifest)[0][0]["expert_crossings"] == 2


def test_manifest_rejects_duplicate_ids(tmp_path):
    (tmp_path / "clip.mp4").write_bytes(b"fixture")
    manifest = tmp_path / "manifest.json"
    clip = {"id": "sample", "path": "clip.mp4"}
    manifest.write_text(json.dumps({"resolution": [640, 480], "clips": [clip, clip]}))
    with pytest.raises(ValueError, match="unique"):
        read_manifest(manifest)
