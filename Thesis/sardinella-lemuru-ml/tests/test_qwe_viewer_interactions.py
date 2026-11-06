"""Fish-focused native-coordinate viewing and grade colors stay presentation-only."""
from colorsys import rgb_to_hsv
from copy import deepcopy

import pytest

from src.api.presentation import GRADE_COLORS_BGR, grade_mask_color
from test_sam_preview_ui import INCLUDE, node, payload


@pytest.mark.parametrize("bbox,viewport", [
    ([100, 300, 800, 450], {"width": 1100, "height": 600}),  # horizontal
    ([700, 100, 900, 900], {"width": 1100, "height": 600}),  # vertical
    ([560, 100, 1120, 700], {"width": 800, "height": 900}),  # diagonal extent
    ([0, 0, 500, 300], {"width": 320, "height": 480}),       # image edge
    ([1600, 800, 1920, 1080], {"width": 1366, "height": 700}),
    ([-10, -20, 200, 250], {"width": 900, "height": 600}),   # clipped detection
    ([0, 0, 1920, 1080], {"width": 390, "height": 650}),
])
def test_fish_focus_keeps_padded_native_bounds_visible_without_distortion(bbox, viewport):
    source = {"width": 1920, "height": 1080}
    result = node(INCLUDE + r'''
include('fishZoomBox');include('fishFocusPlan');
const data=JSON.parse(fs.readFileSync(0,'utf8')),before=JSON.stringify(data);
global.fetch=()=>{throw new Error('Focusing fish must never request inference');};
const plan=fishFocusPlan(data.source,data.bbox,data.viewport);
console.log(JSON.stringify({plan,unchanged:before===JSON.stringify(data)}));
''', {"source": source, "bbox": bbox, "viewport": viewport})
    plan = result["plan"]
    assert result["unchanged"]
    assert 1 <= plan["zoom"] <= 16
    left, top, right, bottom = plan["bounds"]
    assert 0 <= left < right <= source["width"]
    assert 0 <= top < bottom <= source["height"]
    assert left <= max(0, bbox[0]) and top <= max(0, bbox[1])
    assert right >= min(source["width"], bbox[2]) and bottom >= min(source["height"], bbox[3])
    # The same uniform scale and pan must fit both image axes. This also
    # verifies edge clamping never pushes the selected fish out of view.
    scale = min(viewport["width"] / source["width"], viewport["height"] / source["height"]) * plan["zoom"]
    transformed = [
        (left - source["width"] / 2) * scale + plan["x"] + viewport["width"] / 2,
        (top - source["height"] / 2) * scale + plan["y"] + viewport["height"] / 2,
        (right - source["width"] / 2) * scale + plan["x"] + viewport["width"] / 2,
        (bottom - source["height"] / 2) * scale + plan["y"] + viewport["height"] / 2,
    ]
    assert transformed[0] >= -1e-6 and transformed[1] >= -1e-6
    assert transformed[2] <= viewport["width"] + 1e-6
    assert transformed[3] <= viewport["height"] + 1e-6


def test_fish_focus_caps_tiny_fish_magnification_and_rejects_invalid_targets():
    result = node(INCLUDE + r'''
include('fishZoomBox');include('fishFocusPlan');
const nativeSource={width:3840,height:2160},viewport={width:1366,height:768};
const small=fishFocusPlan(nativeSource,[1900,1000,1902,1002],viewport);
const invalid=[null,[],[4,5,4,9],[4,9,8,5],[5000,5000,5100,5100]].map(box=>fishFocusPlan(nativeSource,box,viewport));
invalid.push(fishFocusPlan({width:0,height:2160},[10,10,30,30],viewport));
invalid.push(fishFocusPlan(nativeSource,[10,10,30,30],{width:0,height:768}));
console.log(JSON.stringify({small,invalid}));
''')
    assert result["small"]["zoom"] == 16
    assert all(value is None for value in result["invalid"])


@pytest.mark.parametrize("grade", list(GRADE_COLORS_BGR))
def test_frontend_and_live_mask_shades_match_actual_final_grade_palette(grade):
    identities = [0, 1, 2, 3, 4, 5, -7, "Fish #7"]
    colors = node(INCLUDE + r'''
const input=JSON.parse(fs.readFileSync(0,'utf8'));
console.log(JSON.stringify(input.ids.map(id=>maskPreviewColor(id,input.grade))));
''', {"ids": identities, "grade": grade})
    base = tuple(reversed(GRADE_COLORS_BGR[grade]))
    base_hue = rgb_to_hsv(*(channel / 255 for channel in base))[0]
    for identity, color in zip(identities, colors, strict=True):
        rgb = tuple(int(color[offset:offset + 2], 16) for offset in (1, 3, 5))
        assert rgb == tuple(reversed(grade_mask_color(identity, grade)))
        hue = rgb_to_hsv(*(channel / 255 for channel in rgb))[0]
        difference = abs(base_hue - hue)
        assert min(difference, 1 - difference) < .01
        assert all(original <= shaded <= original + 62 for original, shaded in zip(base, rgb, strict=True))
    assert len(set(colors[:5])) == 5
    assert len(set(colors[:6])) == 6, "Neighboring same-grade masks must not repeat a five-color cycle"


def test_ungraded_stays_gray_independent_of_mask_reliability_and_stale_grade_hint():
    candidate = payload()
    candidate["fish"][0].update(quality="Class A", analysis={"final_grade": "Ungraded"})
    reviewed = deepcopy(candidate)
    reviewed["fish"][0]["segmentation"].update(ownership_status="checks_passed_unvalidated", engineering_checks_passed=True)
    result = node(INCLUDE + r'''
const values=JSON.parse(fs.readFileSync(0,'utf8'));
console.log(JSON.stringify(values.map(data=>{const row=maskPreviewEntries(data)[0];return {grade:row.grade,color:row.color,outline:row.gradeColor,review:row.review};})));
''', [candidate, reviewed])
    assert result[0]["grade"] == result[1]["grade"] == "Ungraded"
    assert result[0]["color"] == result[1]["color"]
    assert result[0]["outline"] == result[1]["outline"] == "#546c7a"
    assert result[0]["review"] and not result[1]["review"]
