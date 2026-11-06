"""The viewer and result cards share engine grades without promoting mask evidence."""
import pytest

from test_sam_preview_ui import HARNESS, INCLUDE, node, payload


@pytest.mark.parametrize("fish, expected", [
    ({"quality": "Class A", "analysis": {"final_grade": "Ungraded"}}, "Ungraded"),
    ({"quality": "Class B", "manual_grade": "Class A"}, "Class B"),
    ({"quality": "Class A", "analysis": {"feature_fusion": {"schema_version": "feature_fusion_v1", "final_grade": "Class C"}}}, "Class C"),
    ({"quality": "Class A", "final_grade": "unvalidated"}, "Ungraded"),
    ({"analysis": {"segmentation": {"ownership_validated": True}}, "confidence": .99}, "Ungraded"),
])
def test_engine_grade_is_primary_and_manual_or_mask_state_cannot_invent_grade(fish, expected):
    actual = node(INCLUDE + r'''
include("resultGrade");global.sessionGradeBuckets=["Class A","Class B","Class C","Rejected","Ungraded"];
const fish=JSON.parse(fs.readFileSync(0,"utf8")),before=JSON.stringify(fish);
console.log(JSON.stringify({ai:aiFinalGrade(fish),zoom:fishZoomGrade(fish),group:resultGrade(fish),unchanged:before===JSON.stringify(fish)}));
''', fish)
    assert actual == {"ai": expected, "zoom": expected, "group": expected, "unchanged": True}


@pytest.mark.parametrize("grade, color", [
    ("Class A", "#087664"), ("Class B", "#175cba"), ("Class C", "#b54d0a"),
    ("Rejected", "#b52e40"), ("Ungraded", "#546c7a"),
])
def test_canvas_labels_and_outlines_use_grade_with_separate_review_warning(grade, color):
    specimen = payload()
    for fish in specimen["fish"]:
        fish["analysis"] = {"final_grade": grade}
    actual = node(INCLUDE + HARNESS + r'''
const value=JSON.parse(fs.readFileSync(0,"utf8")),before=JSON.stringify(value),fills=[],outlines=[];
uploadMaskPreview.data=value;uploadMaskPreview.image={};uploadMaskPreview.file=selectedUpload;
context.fill=()=>fills.push(context.fillStyle);context.stroke=()=>outlines.push(context.strokeStyle);
renderMaskPreview();
console.log(JSON.stringify({labels:draws.filter(row=>row[0]==="text").map(row=>row[1]),fills,outlines,
 entries:maskPreviewEntries(value).map(row=>({grade:row.grade,color:row.color,gradeColor:row.gradeColor})),unchanged:before===JSON.stringify(value)}));
''', specimen)
    assert actual["labels"] == [f"Fish #1 · {grade}", "⚠", f"Fish #2 · {grade}", "⚠"]
    assert actual["outlines"] == [color, color]
    assert actual["fills"][0] != actual["fills"][1]
    assert all(entry["grade"] == grade and entry["gradeColor"] == color for entry in actual["entries"])
    assert actual["unchanged"]


def test_preview_joins_recorded_grade_by_identity_and_keeps_latest_source_diagnostics():
    specimen = payload()
    specimen["fish"][0]["analysis"] = {"fish_geometry": {"frame_id": "native-source", "candidate_measurements": {"fish_length_px": 188}}}
    actual = node(INCLUDE + HARNESS + r'''
const value=JSON.parse(fs.readFileSync(0,"utf8")),before=JSON.stringify(value);
global.resultDatasets={upload:{rows:[{id:2,quality:"Rejected",analysis:{final_grade:"Rejected"}},
 {id:1,quality:"Class A",analysis:{final_grade:"Class B",fish_geometry:{frame_id:"older-preview"}}}]}};
const recordsBefore=JSON.stringify(resultDatasets);
uploadMaskPreview.data=value;uploadMaskPreview.file=selectedUpload;
const entries=maskPreviewEntries(value);
console.log(JSON.stringify({grades:entries.map(row=>row.grade),geometry:entries[0].analysis.fish_geometry,
 unchanged:before===JSON.stringify(value)&&recordsBefore===JSON.stringify(resultDatasets)}));
''', specimen)
    assert actual["grades"] == ["Class B", "Rejected"]
    assert actual["geometry"] == {"frame_id": "native-source", "candidate_measurements": {"fish_length_px": 188}}
    assert actual["unchanged"]


@pytest.mark.parametrize("width,height,viewport_width,viewport_height,expected", [
    (1000, 2000, 800, 400, (200, 400)),
    (2000, 1000, 800, 400, (800, 400)),
    (500, 300, 420, 180, (300, 180)),
])
def test_fit_image_contains_entire_native_image_before_zoom(width, height, viewport_width, viewport_height, expected):
    specimen = payload()
    specimen["source"].update(frame_width_px=width, frame_height_px=height)
    for fish in specimen["fish"]:
        fish["segmentation"]["mask_overlay"].update(frame_width_px=width, frame_height_px=height)
    actual = node(INCLUDE + HARNESS + r'''
const input=JSON.parse(fs.readFileSync(0,"utf8"));uploadMaskPreview.data=input.data;uploadMaskPreview.image={};uploadMaskPreview.file=selectedUpload;
elements.maskPreviewViewport=new Element();elements.maskPreviewViewport.clientWidth=input.width;elements.maskPreviewViewport.clientHeight=input.height;
renderMaskPreview();const fit={...elements.maskPreviewCanvas.style};
elements.maskPreviewZoom.value="2";renderMaskPreview();
console.log(JSON.stringify({fit,zoom:elements.maskPreviewCanvas.style}));
''', {"data": specimen, "width": viewport_width, "height": viewport_height})
    fit_width, fit_height = expected
    assert actual["fit"] == {
        "width": f"{fit_width}px", "height": f"{fit_height}px",
        "left": f"{(viewport_width - fit_width) // 2}px", "top": f"{(viewport_height - fit_height) // 2}px",
    }
    assert actual["zoom"] == {
        "width": f"{fit_width * 2}px", "height": f"{fit_height * 2}px",
        "left": f"{(viewport_width - fit_width * 2) // 2}px", "top": f"{(viewport_height - fit_height * 2) // 2}px",
    }


def test_mask_validation_requires_reviewed_ownership_and_never_changes_engine_grade():
    actual = node(INCLUDE + r'''
include("maskReliabilitySummary");const fish={quality:"Class B",analysis:{segmentation:{ownership_validated:true}}};
const states=[maskReliabilitySummary(fish).status];
fish.analysis.segmentation={engineering_checks_passed:true,ownership_status:"checks_passed_unvalidated"};states.push(maskReliabilitySummary(fish).status);
fish.analysis.segmentation={ownership_validated:true,validation_provenance:{reviewer:"fixture"}};states.push(maskReliabilitySummary(fish).status);
console.log(JSON.stringify({states,grade:aiFinalGrade(fish)}));
''')
    assert actual == {"states": ["Requires Review", "Estimated", "Validated"], "grade": "Class B"}


def test_selecting_lazy_result_reveals_its_group_and_preserves_cached_results():
    specimen = payload()
    actual = node(INCLUDE + HARNESS + r'''
include("resultGrade");include("selectInspectionFish");global.sessionGradeBuckets=["Class A","Class B","Class C","Rejected","Ungraded"];
const input=JSON.parse(fs.readFileSync(0,"utf8"));uploadMaskPreview.data=input;uploadMaskPreview.file=selectedUpload;
global.resultDatasets={upload:{rows:[{id:2,quality:"Class B"}]}};const before=JSON.stringify(resultDatasets);
global.resultsSource="upload";global.resultsFilter="Class A";let rendered=0,redraws=0,scrolled=0;
global.renderResultsDashboard=()=>rendered++;global.renderMaskPreview=()=>redraws++;
const cards=[],group={dataset:{grade:"Class B"},ensureFishCard(id){cards.push({dataset:{inspectionFishId:id},open:false,
 classList:{toggle(_key,value){this.selected=value;}},setAttribute(){},scrollIntoView(){scrolled++;}});}};
elements.resultsGroups={querySelectorAll:selector=>selector.includes("result-grade-group")?[group]:cards};
global.fetch=()=>{throw new Error("Selection cannot run inference");};
selectInspectionFish(2,{revealCard:true});
console.log(JSON.stringify({filter:resultsFilter,selected:elements.maskPreviewFish.value,cardOpen:cards[0].open,
 highlighted:cards[0].classList.selected,rendered,redraws,scrolled,unchanged:before===JSON.stringify(resultDatasets)}));
''', specimen)
    assert actual == {"filter": "All", "selected": "2", "cardOpen": True, "highlighted": True,
                      "rendered": 1, "redraws": 1, "scrolled": 1, "unchanged": True}


def test_repetitive_evidence_list_is_empty_and_cards_refresh_once_per_cached_preview():
    actual = node(INCLUDE + HARNESS + r'''
include("renderMaskInspectionEvidence");elements.maskPreviewEvidence=new Element();elements.maskPreviewEvidence.children=[new Element()];
uploadMaskPreview.data={fish:[]};global.resultsSource="upload";global.recentHistoryKey="old";
let renders=0;global.renderResultsDashboard=()=>renders++;
renderMaskInspectionEvidence([],null);renderMaskInspectionEvidence([],null);
console.log(JSON.stringify({children:elements.maskPreviewEvidence.children.length,hidden:elements.maskPreviewEvidence.hidden,renders,key:recentHistoryKey}));
''')
    assert actual == {"children": 0, "hidden": True, "renders": 1, "key": None}

