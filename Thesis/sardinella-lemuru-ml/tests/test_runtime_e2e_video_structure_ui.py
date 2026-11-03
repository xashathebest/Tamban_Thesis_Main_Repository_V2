"""Source fish ownership survives video display-ID remapping."""
import pytest

from test_sam_features_ui import AUTOMATIC, node, payload


@pytest.mark.parametrize("scope,expected", [
    ("own-source", 1), ("mapped-own-source", 1), ("neighbor-source", 0),
    ("mapped-neighbor-source", 0), ("old-frame", 0), ("unverified-source", 0),
])
def test_structural_overlay_uses_verified_source_parent_in_video(scope, expected):
    specimen = payload()
    first, second = specimen["fish"]
    first.update(id=2, source_parent_id=1)
    second.update(id=1, source_parent_id=2)
    first["segmentation"].update(parent_track_id=2, source_detection_id=1)
    second["segmentation"].update(parent_track_id=1, source_detection_id=2)
    damage = {"status": "suspected", "frame_id": "native-source", "parent_track_id": 1,
              "coordinate_space": "crop_local_native_pixels", "crop_bounds": [15, 30, 235, 120],
              "locations": [{"x": 70., "y": 30., "width": 40., "height": 3.}]}
    if scope == "mapped-own-source":
        damage.update(parent_track_id=2, source_parent_id=1)
    if scope == "neighbor-source":
        damage["parent_track_id"] = 2
    if scope == "mapped-neighbor-source":
        damage.update(parent_track_id=2, source_parent_id=2)
    if scope == "old-frame":
        damage["frame_id"] = "old-source"
    if scope == "unverified-source":
        first.pop("source_parent_id")
    first["analysis"] = {"surface_damage": damage}
    actual = node(AUTOMATIC + r'''
uploadMaskPreview.data=JSON.parse(fs.readFileSync(0,"utf8"));uploadMaskPreview.image={};uploadMaskPreview.file=selectedUpload;
elements.maskPreviewCracks.checked=true;elements.maskPreviewFish.value="2";renderMaskPreview();
console.log(JSON.stringify({draws,networkCalls}));
''', specimen)
    boxes = [row for row in actual["draws"] if row[0] == "box" and row[1] == 85.]
    assert len(boxes) == expected
    assert actual["networkCalls"] == 0
