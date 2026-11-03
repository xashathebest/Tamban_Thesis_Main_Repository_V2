"""Optional diagnostics never imply ownership or rerun an inference operation."""
from copy import deepcopy
import csv
from io import BytesIO, StringIO
import json
from pathlib import Path

from openpyxl import load_workbook
import pytest

from src.api.export import DEFAULT_EXPORT_FIELDS, EXPORT_FIELDS, inspection_row, make_csv, make_xlsx
from test_main_view_mask_toggle import MAIN, node, payload
from test_sam_preview_ui import INCLUDE
from test_qualitycheck_ui_exports import NODE as EXPORT_NODE


ROOT = Path(__file__).resolve().parents[1]
FIELDS = ("anatomical_association_diagnostics", "anatomical_part_decisions",
          "anatomical_inference_provenance", "model2_raw_detection_diagnostics")
DEBUG = MAIN + r'''
for(const name of ["anatomicalAssociationEvidence","anatomicalAssociationRows","anatomicalAssociationOverlay","renderAnatomicalAssociationDebug"])include(name);
for(const key of ["maskPreviewAssociation","maskPreviewAssociationStatus","maskPreviewAssociationLegend"])elements[key]=new Element();
elements.maskPreviewAssociation.checked=false;
const originalBox=context.strokeRect;context.strokeRect=function(...args){originalBox(...args);draws.push(["box_color",this.strokeStyle]);};
'''


def specimen():
    value = payload()
    parts = []
    for index, (region, status, owner, reason) in enumerate([
        ("Head", "ASSIGNED", 1, None), ("Body", "UNASSIGNED", None, "part_not_contained"),
        ("Tail", "AMBIGUOUS", None, "competing_parent_scores"),
        ("Head", "ASSIGNED", 2, None),
    ]):
        part = {"region": region, "source_class_id": index, "source_class_name": f"{region} Class A",
                "confidence": .8, "bbox": [20 + index * 40, 40, 45 + index * 40, 70]}
        parts.append({"part": part, "status": status, "track_id": owner, "reason": reason,
                      "candidate_parent_ids": [1, 2], "acceptance_thresholds": {"minimum_score": .25},
                      "candidates": [{"track_id": 1, "score": .55, "eligible": status == "ASSIGNED",
                                      "failed_checks": [reason] if reason else [],
                                      "orientation": {"axis": [1., .2], "source": "parent_bbox",
                                                      "longitudinal_position": .2, "reliable": True},
                                      "mask": {"provided": True, "center_support": .9, "provenance": "reviewed"}}]})
    provenance = {"coordinate_space": "original_frame", "frame_id": "native-source",
                  "frame_width_px": 500, "frame_height_px": 300}
    association = {**provenance, "parts": parts, "status": "AMBIGUOUS"}
    value["fish"][0]["analysis"] = {"quality_inference": {"association": association,
        "clipping": {"parent_box_frame_contact": False, "context_crop_frame_contact": True}},
        "model2_debug": {**provenance, "raw_detections": [deepcopy(row["part"]) for row in parts],
                         "selection_threshold": .2}}
    return value


def test_debug_control_is_optional_and_preserves_all_existing_controls():
    html = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
    control = html.split('id="upload-association-debug"', 1)[1].split(">", 1)[0]
    assert 'type="checkbox"' in control and "checked" not in control
    for name in ("upload-display-boxes", "upload-display-masks", "upload-mask-opacity", "upload-mask-fish",
                 "upload-mask-zoom", "upload-mask-model1", "upload-mask-model2", "upload-mask-show",
                 "upload-mask-cracks", "upload-mask-loading", "upload-mask-cancel", "upload-mask-legend"):
        assert f'id="{name}"' in html


def test_debug_is_off_by_default_and_requests_one_highlighted_fish():
    actual = node(DEBUG + r'''
uploadMaskPreview.data=JSON.parse(fs.readFileSync(0,"utf8"));uploadMaskPreview.image={};uploadMaskPreview.file=selectedUpload;
renderMaskPreview();const off=draws.splice(0);elements.maskPreviewAssociation.checked=true;renderMaskPreview();
console.log(JSON.stringify({off,on:draws,status:elements.maskPreviewAssociationStatus.textContent,networkCalls}));
''', specimen())
    assert not any("RAW" in row[1] for row in actual["off"] if row[0] == "text")
    assert not any("RAW" in row[1] for row in actual["on"] if row[0] == "text")
    assert "Highlight one Fish ID" in actual["status"] and actual["networkCalls"] == 0


def test_highlighted_debug_distinguishes_raw_owned_rejected_ambiguous_and_neighbor():
    actual = node(DEBUG + r'''
uploadMaskPreview.data=JSON.parse(fs.readFileSync(0,"utf8"));uploadMaskPreview.image={};uploadMaskPreview.file=selectedUpload;
const before=JSON.stringify(uploadMaskPreview.data);elements.maskPreviewAssociation.checked=true;elements.maskPreviewFish.value="1";
renderMaskPreview();console.log(JSON.stringify({draws,status:elements.maskPreviewAssociationStatus.textContent,networkCalls,unchanged:before===JSON.stringify(uploadMaskPreview.data)}));
''', specimen())
    texts = [row[1] for row in actual["draws"] if row[0] == "text"]
    assert sum("RAW; ownership unestablished" in text for text in texts) == 4
    assert sum("ACCEPTED for #1" in text for text in texts) == 1
    assert any("UNASSIGNED; candidate only" in text for text in texts)
    assert any("AMBIGUOUS; candidate only" in text for text in texts)
    assert any("owned by #2; candidate only for #1" in text for text in texts)
    assert {row[1] for row in actual["draws"] if row[0] == "box_color"}.issuperset({"#38bdf8", "#22c55e", "#fb7185", "#fbbf24"})
    assert actual["networkCalls"] == 0 and actual["unchanged"]


@pytest.mark.parametrize("fault", ["frame_id", "frame_width_px", "frame_height_px", "coordinate_space", "unknown_provenance", "invalid_bbox"])
def test_debug_withholds_stale_mismatched_or_unverified_coordinates(fault):
    value = specimen(); analysis = value["fish"][0]["analysis"]
    for metadata in (analysis["quality_inference"]["association"], analysis["model2_debug"]):
        if fault == "unknown_provenance":
            metadata.pop("frame_id")
        elif fault == "invalid_bbox":
            records = metadata.get("raw_detections", [row["part"] for row in metadata.get("parts", [])])
            for row in records: row["bbox"][2] = 501
        else:
            metadata[fault] = {"frame_id": "previous-frame", "frame_width_px": 1000,
                               "frame_height_px": 450, "coordinate_space": "crop_local"}[fault]
    actual = node(DEBUG + r'''
uploadMaskPreview.data=JSON.parse(fs.readFileSync(0,"utf8"));uploadMaskPreview.image={};uploadMaskPreview.file=selectedUpload;
elements.maskPreviewAssociation.checked=true;elements.maskPreviewFish.value="1";renderMaskPreview();
console.log(JSON.stringify({draws,status:elements.maskPreviewAssociationStatus.textContent}));
''', value)
    assert not any(row[0] == "text" and ("RAW" in row[1] or "candidate only" in row[1] or "ACCEPTED" in row[1]) for row in actual["draws"])
    assert "no source-matched" in actual["status"]


def test_debug_is_fish_scoped_and_does_not_borrow_another_fishs_candidates():
    actual = node(DEBUG + r'''
uploadMaskPreview.data=JSON.parse(fs.readFileSync(0,"utf8"));uploadMaskPreview.image={};uploadMaskPreview.file=selectedUpload;
elements.maskPreviewAssociation.checked=true;elements.maskPreviewFish.value="2";renderMaskPreview();
console.log(JSON.stringify({draws,status:elements.maskPreviewAssociationStatus.textContent,networkCalls}));
''', specimen())
    assert not any("RAW" in row[1] for row in actual["draws"] if row[0] == "text")
    assert "Fish #2: no source-matched" in actual["status"] and actual["networkCalls"] == 0


@pytest.mark.parametrize("mapping", [None, {"1": 2}, {"1": 2, "2": 1}])
def test_video_remapped_display_id_never_claims_coincidental_source_owner(mapping):
    value = specimen()
    value["fish"][0].update(id=2, source_parent_id=1)
    value["fish"][0]["segmentation"].update(parent_track_id=2, source_detection_id=1)
    value["fish"][1].update(id=1, source_parent_id=2)
    value["fish"][1]["segmentation"].update(parent_track_id=1, source_detection_id=2)
    if mapping is not None: value["source"]["fish_id_mapping"] = mapping
    actual = node(DEBUG + r'''
const value=JSON.parse(fs.readFileSync(0,"utf8"));const entry=maskPreviewEntries(value)[0];
console.log(JSON.stringify({rows:anatomicalAssociationOverlay(entry,maskPreviewSource(value)),mapping:entry.associationIdMap}));
''', value)
    rows = [row for row in actual["rows"] if row["kind"] != "raw"]
    assert rows[0]["label"] == "Head ACCEPTED for #2"
    neighbor = rows[3]
    assert neighbor["kind"] == "ambiguous" and "ACCEPTED" not in neighbor["label"]
    if mapping == {"1": 2, "2": 1}:
        assert "owned by #1; candidate only for #2" in neighbor["label"]
        assert actual["mapping"] == mapping
    else:
        assert "owned by source Fish #2; candidate only for #2" in neighbor["label"]
        assert actual["mapping"] is None


def test_legacy_video_without_source_parent_mapping_cannot_claim_owned_parts():
    value = specimen()
    value["fish"][0]["segmentation"]["source_detection_id"] = 2
    actual = node(DEBUG + r'''
const value=JSON.parse(fs.readFileSync(0,"utf8"));const entry=maskPreviewEntries(value)[0];
console.log(JSON.stringify(anatomicalAssociationOverlay(entry,maskPreviewSource(value))));
''', value)
    assert not any(row["kind"] == "accepted" for row in actual)
    assert any("display identity unverified" in row["label"] for row in actual)


def test_video_assigned_part_overlay_checks_source_ownership_before_display_ids():
    value = specimen(); fish = value["fish"][0]
    fish.update(id=2, source_parent_id=1)
    fish["segmentation"].update(parent_track_id=2, source_detection_id=1)
    fish["parts"] = [
        {"region": "Body source-owned", "bbox": [30, 40, 70, 70], "parent_track_id": 1},
        {"region": "Neighbor with colliding display ID", "bbox": [70, 40, 100, 70], "parent_track_id": 2},
        {"region": "Head mapped", "bbox": [30, 40, 70, 70], "source_parent_id": 1, "parent_track_id": 2},
        {"region": "Tail explicit display namespace", "bbox": [30, 40, 70, 70], "parent_id_space": "display", "parent_track_id": 2},
        {"region": "Unknown owner", "bbox": [30, 40, 70, 70]},
    ]
    actual = node(INCLUDE + r'''
const value=JSON.parse(fs.readFileSync(0,"utf8"));console.log(JSON.stringify(maskPreviewEntries(value)[0].parts));
''', value)
    assert [part["region"] for part in actual] == ["Body source-owned", "Head mapped", "Tail explicit display namespace"]


def test_debug_in_boxes_view_restores_original_and_preserves_other_preferences():
    actual = node(DEBUG + r'''
uploadMaskPreview.data=JSON.parse(fs.readFileSync(0,"utf8"));uploadMaskPreview.image={};uploadMaskPreview.file=selectedUpload;
elements.maskPreviewAssociation.checked=true;elements.maskPreviewFish.value="1";elements.maskPreviewOpacity.value="25";elements.maskPreviewZoom.value="2";
renderMaskPreview();const debugVisible=!elements.maskPreviewViewport.hidden;
elements.maskPreviewAssociation.checked=false;renderMaskPreview();
console.log(JSON.stringify({debugVisible,originalHidden:elements.uploadImage.hidden,src:elements.uploadImage.src,maskHidden:elements.maskPreviewViewport.hidden,
boxes:elements.maskPreviewBoxes.checked,masks:elements.maskPreviewMasks.checked,opacity:elements.maskPreviewOpacity.value,zoom:elements.maskPreviewZoom.value,fish:elements.maskPreviewFish.value,networkCalls}));
''', specimen())
    assert actual == {"debugVisible": True, "originalHidden": False, "src": "existing-annotated-image",
        "maskHidden": True, "boxes": True, "masks": False, "opacity": "25", "zoom": "2", "fish": "1", "networkCalls": 0}


def test_new_analysis_resets_debug_without_changing_opacity_and_never_draws_old_rows():
    actual = node(DEBUG + r'''
uploadMaskPreview.data=JSON.parse(fs.readFileSync(0,"utf8"));uploadMaskPreview.image={};uploadMaskPreview.file=selectedUpload;
elements.maskPreviewAssociation.checked=true;elements.maskPreviewFish.value="1";elements.maskPreviewOpacity.value="25";
renderMaskPreview();clearMaskPreview();draws.length=0;selectedUpload={name:"next.jpg"};renderMaskPreview();
console.log(JSON.stringify({enabled:elements.maskPreviewAssociation.checked,hidden:elements.maskPreviewAssociationStatus.hidden,draws,opacity:elements.maskPreviewOpacity.value,networkCalls}));
''', specimen())
    assert actual == {"enabled": False, "hidden": True, "draws": [], "opacity": "25", "networkCalls": 0}


def test_missing_source_explains_debug_unavailability_without_new_model_request():
    actual = node(DEBUG + r'''
elements.maskPreviewAssociation.checked=true;renderMaskPreview();const message=elements.maskPreviewAssociationStatus.textContent;
elements.maskPreviewAssociation.checked=false;renderMaskPreview();
console.log(JSON.stringify({message,hidden:elements.maskPreviewAssociationStatus.hidden,networkCalls}));
''')
    assert "current analysis source image is ready" in actual["message"]
    assert actual["hidden"] and actual["networkCalls"] == 0


def test_fish_local_table_explains_scores_rejection_mask_orientation_clipping_thresholds():
    fish = specimen()["fish"][0]
    actual = node(INCLUDE + r'''
for(const name of ["anatomicalAssociationEvidence","anatomicalAssociationRows"])include(name);
const fish=JSON.parse(fs.readFileSync(0,"utf8")),before=JSON.stringify(fish);
console.log(JSON.stringify({rows:anatomicalAssociationRows(fish),unchanged:before===JSON.stringify(fish)}));
''', fish)
    assert len(actual["rows"]) == 4 and actual["unchanged"]
    head = actual["rows"][0]
    assert head[1] == "0.8" and head[3] == "[1,2]" and head[4] == "Fish #1: 0.55"
    assert json.loads(head[5])["longitudinal_position"] == .2
    assert json.loads(head[6])["center_support"] == .9
    assert json.loads(head[7])["parent_box_frame_contact"] is False
    assert json.loads(head[8])["minimum_score"] == .25
    assert actual["rows"][1][10] == "part_not_contained"
    assert "candidate only here" in actual["rows"][3][9]


def test_legacy_table_reports_missing_diagnostics_without_fabricating_decisions():
    actual = node(INCLUDE + r'''
for(const name of ["anatomicalAssociationEvidence","anatomicalAssociationRows"])include(name);
console.log(JSON.stringify(anatomicalAssociationRows({id:1,analysis:{model2_debug:{raw_detections:[{region:"Head",confidence:.9,bbox:[1,2,3,4]}]}}})));
''')
    assert actual[0][9] == "RAW; ownership not established"
    assert actual[0][10] == "No association decision recorded for this raw detection"
    assert actual[0][3:7] == ["Not recorded"] * 4


def test_preassociation_rejection_keeps_recorded_reason_and_image_crop_distinction():
    fish = {"id": 1, "analysis": {"quality_inference": {"association": {
        "clipping": {"parent_box_frame_contact": False, "context_crop_frame_contact": True}}},
        "model2_debug": {"raw_detections": [{"region": "Head", "confidence": .19, "bbox": [1, 2, 3, 4]}],
                         "rejected_detections": [{"region": "Head", "confidence": .19, "bbox": [1, 2, 3, 4],
                                                  "reason": "detector_score_below_configured_threshold"}]}}}
    actual = node(INCLUDE + r'''
for(const name of ["anatomicalAssociationEvidence","anatomicalAssociationRows"])include(name);
console.log(JSON.stringify(anatomicalAssociationRows(JSON.parse(fs.readFileSync(0,"utf8")))));
''', fish)
    assert actual[0][9] == "NOT SELECTED for this fish; ownership not established"
    assert actual[0][10] == "detector_score_below_configured_threshold"
    assert json.loads(actual[0][7]) == {"parent_box_frame_contact": False, "context_crop_frame_contact": True}


def export_event():
    fish = specimen()["fish"][0]
    fish["quality"] = "Class B"
    fish["analysis"].update(final_grade="Class B", weighted_scores={"Class B": .8})
    return fish


def test_csv_xlsx_append_complete_association_and_raw_evidence_without_changing_grade():
    fish = export_event(); before = deepcopy(fish)
    assert DEFAULT_EXPORT_FIELDS[-4:] == FIELDS
    row = inspection_row(fish)
    assert row["grade"] == "Class B" and row["class_b_weighted_score"] == 80.
    expected = [fish["analysis"]["quality_inference"]["association"],
                fish["analysis"]["quality_inference"]["association"]["parts"],
                fish["analysis"]["quality_inference"], fish["analysis"]["model2_debug"]]
    csv_row = next(csv.DictReader(StringIO(make_csv([fish], FIELDS).decode("utf-8-sig"))))
    workbook = load_workbook(BytesIO(make_xlsx([fish], FIELDS, {})), data_only=True)
    excel = dict(zip(FIELDS, list(workbook["Fish Inspections"].values)[1]))
    for field, evidence in zip(FIELDS, expected):
        assert json.loads(row[field]) == json.loads(csv_row[EXPORT_FIELDS[field]]) == json.loads(excel[field]) == evidence
    assert fish == before


def test_legacy_export_keeps_missing_association_explicitly_empty():
    row = inspection_row({"id": 1, "quality": "Ungraded", "analysis": {}})
    assert [json.loads(row[field]) for field in FIELDS] == [{}, [], {}, {}]


def test_browser_csv_appends_diagnostics_after_existing_columns_and_keeps_raw_evidence():
    fish = export_event(); before = deepcopy(fish)
    actual = node(EXPORT_NODE, [fish])
    reader = csv.DictReader(StringIO(actual["csv"].lstrip("\ufeff")))
    rows = list(reader)
    titles = ["Anatomical association diagnostics", "Anatomical part decisions and candidate scores",
              "Anatomical inference and clipping provenance", "Raw Model 2 detection diagnostics"]
    assert reader.fieldnames[-4:] == titles
    assert reader.fieldnames[-5] == "Fish candidate segmentation evidence (previews omitted)"
    record = actual["rows"][0]["record"]
    assert rows[0]["Final classification"] == record["Final classification"] == "Class B"
    assert json.loads(rows[0][titles[0]]) == fish["analysis"]["quality_inference"]["association"]
    assert json.loads(rows[0][titles[1]]) == fish["analysis"]["quality_inference"]["association"]["parts"]
    assert json.loads(rows[0][titles[3]]) == fish["analysis"]["model2_debug"]
    assert json.loads(rows[0]["Complete fish event"])["analysis"] == before["analysis"]
    assert fish == before
