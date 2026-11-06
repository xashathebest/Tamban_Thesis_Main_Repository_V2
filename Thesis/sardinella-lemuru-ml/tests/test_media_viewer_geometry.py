"""Fit/Fill hit testing and canvas placement preserve source coordinates."""
import pytest

from test_sam_preview_ui import HARNESS, INCLUDE, node, payload


@pytest.mark.parametrize("mode,rect,expected", [
    ("contain", [0, 0, 1200, 600], {"scale": 1.25, "left": 200, "top": 0}),
    ("cover", [0, 0, 1200, 600], {"scale": 1.875, "left": 0, "top": -150}),
    # A 200% view translated left by 80px and down by 50px. These are
    # browser bounding rects after the CSS transform, in a 1200x600 stage.
    ("contain", [-680, -250, 2400, 1200], {"scale": 2.5, "left": -280, "top": -250}),
    ("cover", [-680, -250, 2400, 1200], {"scale": 3.75, "left": -680, "top": -550}),
])
def test_native_hit_coordinates_follow_fit_fill_and_transformed_media(mode, rect, expected):
    result = node(INCLUDE + r'''
include("fishZoomGeometry");include("fishZoomPoint");
const input=JSON.parse(fs.readFileSync(0,"utf8"));
global.getComputedStyle=()=>({objectFit:input.mode});
const [left,top,width,height]=input.rect;
const media={naturalWidth:640,naturalHeight:480,getBoundingClientRect:()=>({left,top,width,height})};
const stage={getBoundingClientRect:()=>({left:0,top:0,width:1200,height:600})};
const geometry=fishZoomGeometry(media,stage);
const point=fishZoomPoint({clientX:geometry.left+320*geometry.scale,clientY:geometry.top+240*geometry.scale},media,stage);
console.log(JSON.stringify({geometry,point}));
''', {"mode": mode, "rect": rect})
    assert result["geometry"] == {"width": 640, "height": 480, **expected}
    assert result["point"] == [320, 240]


@pytest.mark.parametrize("mode,zoom,pan,expected", [
    ("contain", 1, [900, -900], [0, 0, 60, 0, 300, 180]),
    ("contain", 2, [900, -900], [90, -90, 0, -180, 600, 360]),
    ("cover", 1, [900, -900], [0, -36, 0, -72, 420, 252]),
    ("cover", 2, [-900, 900], [-210, 162, -420, 0, 840, 504]),
])
def test_canvas_pan_reaches_source_edges_without_stretching_or_internal_scroll(mode, zoom, pan, expected):
    result = node(INCLUDE + HARNESS + r'''
const input=JSON.parse(fs.readFileSync(0,"utf8"));
uploadMaskPreview.data=input.data;uploadMaskPreview.image={};uploadMaskPreview.file=selectedUpload;
elements.maskPreviewViewport=new Element();
elements.maskPreviewViewport.clientWidth=420;elements.maskPreviewViewport.clientHeight=180;
elements.maskPreviewZoom.value=String(input.zoom);
global.viewerFitMode=()=>input.mode;global.viewerTransforms={upload:{x:input.pan[0],y:input.pan[1]}};
const before=JSON.stringify(uploadMaskPreview.data);
global.fetch=()=>{throw new Error("Display transforms must not request inference");};
renderMaskPreview();
const css=elements.maskPreviewCanvas.style;
console.log(JSON.stringify({position:[viewerTransforms.upload.x,viewerTransforms.upload.y,...["left","top","width","height"].map(key=>parseFloat(css[key]))],unchanged:before===JSON.stringify(uploadMaskPreview.data)}));
''', {"data": payload(), "mode": mode, "zoom": zoom, "pan": pan})
    assert result["position"] == pytest.approx(expected)
    assert result["unchanged"]
