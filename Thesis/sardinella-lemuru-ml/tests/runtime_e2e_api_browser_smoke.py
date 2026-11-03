"""Actual CPU HTTP analysis, real mask/debug UI, and lossless export replay.

Uses the existing isolated real-model harness and adds native-part provenance,
normalization and download checks. The normal GPU service is untouched.
"""
from __future__ import annotations

from copy import deepcopy
import csv
import hashlib
from io import BytesIO, StringIO
import json
from pathlib import Path
import sys
import types
import zipfile

import sam_features_browser_smoke as features


browser = features.browser
ROOT = browser.ROOT
sys.path.insert(0, str(ROOT))
OUTPUT = ROOT / "results/qa/runtime_e2e/ui"


ADDITIONAL = r'''
const originalNativeSource=maskPreviewSource(payload);
const key=part=>JSON.stringify([part.source_class_id,part.bbox,part.confidence]);
const firstRaw=analysis.fish[0].analysis.model2_debug.raw_detections.map(key).sort();
checks.rawNativeDetectionsAgreeForEveryFish=analysis.fish.every(f=>JSON.stringify(f.analysis.model2_debug.raw_detections.map(key).sort())===JSON.stringify(firstRaw));
checks.nativeAssociationFrameMatchesPreview=analysis.fish.every(f=>{const a=f.analysis.quality_inference.association;
 return a.coordinate_space==='original_frame'&&a.frame_id===payload.source.frame_id&&a.frame_width_px===payload.source.frame_width_px&&a.frame_height_px===payload.source.frame_height_px;});
const alignment=[];
for(const fish of analysis.fish)for(const part of fish.parts){
 const recorded=fish.analysis.quality_inference.association.parts.find(row=>row.status==='ASSIGNED'&&row.track_id===fish.id&&row.part.region===part.region&&row.part.source_class_id===part.source_class_id);
 alignment.push(recorded?Math.max(...part.bbox.map((v,i)=>Math.abs(v-recorded.part.bbox[i]))):Infinity);
}
checks.acceptedPartsBelongToRecordedNativeParent=alignment.every(error=>error<=.011);
const overlayCounts=entries.map(entry=>{const recorded=entry.analysis.quality_inference.association.parts;
 return {fish_id:entry.id,accepted:anatomicalAssociationOverlay(entry,originalNativeSource).filter(row=>row.kind==='accepted').length,
 expected:recorded.filter(row=>row.status==='ASSIGNED'&&row.track_id===entry.id).length,
 rows:anatomicalAssociationRows(entry).length};});
checks.debugAcceptedOverlaysMatchOwnedParts=overlayCounts.every(row=>row.accepted===row.expected&&row.rows>0);
elements.maskPreviewAssociation.checked=true;selectInspectionFish(entries[0].id,{revealCard:true});renderMaskPreview();
checks.actualDebugUsesMainViewer=!elements.maskPreviewViewport.classList.contains('hidden')&&elements.uploadImage.classList.contains('hidden');
checks.actualDebugExplainsRecordedCandidates=/recorded diagnostic overlays/.test(elements.maskPreviewAssociationStatus.textContent);
elements.maskPreviewAssociation.checked=false;renderMaskPreview();
const normalizedResponse=await rawFetch('/api/inspection-results/normalize',{method:'POST',headers:{'Content-Type':'application/json'},
 body:JSON.stringify({fish:analysis.fish,source_metadata:{analyzed_at:analysis.analyzed_at,inspection_source:analysis.inspection_source}})});
const normalized=await normalizedResponse.json();
checks.httpNormalizationPreservesActualGrades=normalizedResponse.ok&&JSON.stringify(normalized.fish.map(f=>[f.quality,f.analysis.weighted_scores,f.analysis.final_score]))===JSON.stringify(analysis.fish.map(f=>[f.quality,f.analysis.weighted_scores,f.analysis.final_score]));
const originalCreate=URL.createObjectURL,originalAnchorClick=HTMLAnchorElement.prototype.click;
let csvBlob=null;
URL.createObjectURL=blob=>{if(blob.type==='text/csv;charset=utf-8')csvBlob=blob;return originalCreate.call(URL,blob);};
HTMLAnchorElement.prototype.click=function(){if(!this.download)return originalAnchorClick.call(this);};
try{await exportResultsCsv();}finally{URL.createObjectURL=originalCreate;HTMLAnchorElement.prototype.click=originalAnchorClick;}
const downloadedCsv=csvBlob?await csvBlob.text():null;
checks.browserCsvCaptured=typeof downloadedCsv==='string'&&downloadedCsv.includes('Anatomical association diagnostics');
const runtimeEvidence={source:originalNativeSource,raw_part_count:firstRaw.length,
 max_part_coordinate_error_px:alignment.length?Math.max(...alignment):null,overlay_counts:overlayCounts,
 normalization_status:normalizedResponse.status,browser_csv:downloadedCsv};
'''


def configure():
    browser.OUTPUT = OUTPUT
    marker = "const after=await (await rawFetch('/__qa/diagnostics')).json();"
    assert browser.EXERCISE.count(marker) == 1
    browser.EXERCISE = browser.EXERCISE.replace(marker, ADDITIONAL + "\n" + marker)
    browser.EXERCISE = browser.EXERCISE.replace("return {checks,payload,analysis,requests,loadingText,cardDebug:",
                                              "return {checks,payload,analysis,requests,loadingText,runtimeEvidence,cardDebug:")


def _reconstruct(workbook, value):
    try:
        reference = json.loads(value).get("xlsx_extended_evidence")
    except (ValueError, TypeError, AttributeError):
        return value
    if not reference:
        return value
    sheet = workbook[reference["sheet"]]
    records = [dict(zip(next(sheet.values), row)) for row in list(sheet.values)[1:]]
    chunks = sorted((row for row in records if row["Record key"] == reference["record_key"]), key=lambda row: row["Chunk number"])
    assert len(chunks) == reference["chunk_count"]
    result = "".join(row["Text chunk"] for row in chunks)
    assert len(result) == reference["character_count"]
    assert hashlib.sha256(result.encode("utf-8")).hexdigest() == reference["sha256"]
    return result


def verify_exports(result):
    from openpyxl import load_workbook
    from src.api import export
    events = result["analysis"]["fish"]
    before = deepcopy(events)
    expected = [export.inspection_row(event) for event in events]
    fields = export.DEFAULT_EXPORT_FIELDS
    actual_csv = export.make_csv(events, fields)
    actual_xlsx = export.make_xlsx(events, fields, {"Total Fish": len(events)})
    (OUTPUT / "actual_native_evidence.csv").write_bytes(actual_csv)
    (OUTPUT / "actual_native_evidence.xlsx").write_bytes(actual_xlsx)
    downloaded_csv = result["runtimeEvidence"].pop("browser_csv")
    (OUTPUT / "actual_browser_download.csv").write_text(downloaded_csv, encoding="utf-8")
    old_limit = csv.field_size_limit(30_000_000)
    try:
        csv_rows = list(csv.DictReader(StringIO(actual_csv.decode("utf-8-sig"))))
        browser_rows = list(csv.DictReader(StringIO(downloaded_csv.lstrip("\ufeff"))))
    finally:
        csv.field_size_limit(old_limit)
    workbook = load_workbook(BytesIO(actual_xlsx), data_only=True)
    xlsx_rows = [dict(zip(fields, row)) for row in list(workbook["Fish Inspections"].values)[1:]]
    checks = {"row_count_matches": len(events) == len(csv_rows) == len(xlsx_rows) == len(browser_rows),
              "csv_every_field_matches": True, "xlsx_every_field_reconstructs": True,
              "browser_grade_score_trace_matches": True, "source_events_unchanged": events == before}
    oversized = 0
    for source, csv_row, xlsx_row, browser_row in zip(expected, csv_rows, xlsx_rows, browser_rows):
        for field in fields:
            value = source[field]
            expected_text = str(value) if value is not None else ""
            checks["csv_every_field_matches"] &= csv_row[export.EXPORT_FIELDS[field]] == expected_text
            original = _reconstruct(workbook, xlsx_row[field])
            checks["xlsx_every_field_reconstructs"] &= (original in (None, "") if value == "" else original == value)
            oversized += int(isinstance(value, str) and len(value.encode("utf-16-le")) // 2 > 32767)
        checks["browser_grade_score_trace_matches"] &= (
            browser_row["Final classification"] == source["grade"]
            and json.loads(browser_row["Anatomical association diagnostics"]) == json.loads(source["anatomical_association_diagnostics"])
            and json.loads(browser_row["Raw Model 2 detection diagnostics"]) == json.loads(source["model2_raw_detection_diagnostics"]))
    baseline = types.ModuleType("runtime_e2e_baseline_export")
    with zipfile.ZipFile(OUTPUT.parent / "baseline_source.zip") as archive:
        exec(compile(archive.read("src/api/export.py"), "baseline_export.py", "exec"), baseline.__dict__)
    baseline_xlsx = baseline.make_xlsx(events, fields, {})
    baseline_workbook = load_workbook(BytesIO(baseline_xlsx), data_only=True)
    baseline_rows = [dict(zip(fields, row)) for row in list(baseline_workbook["Fish Inspections"].values)[1:]]
    losses = []
    for source, old in zip(expected, baseline_rows):
        for field in fields:
            value = source[field]
            if isinstance(value, str) and len(value) > 32767 and old[field] != value:
                losses.append({"fish_id": source["fish_id"], "field": field, "before_characters": len(old[field]),
                               "original_characters": len(value), "after_reconstructed_characters": len(_reconstruct(workbook, xlsx_rows[expected.index(source)][field]))})
    assert all(checks.values()), checks
    return {"checks": checks, "oversized_values_preserved": oversized, "before_truncated_cells": len(losses),
            "after_truncated_cells": 0, "loss_records": losses, "field_count": len(fields), "fish_count": len(events),
            "scope": "Actual HTTP model results through browser CSV and production backend CSV/XLSX helpers; XLSX chunks reassembled and checksum checked. Not a fish-accuracy measure."}


def main():
    configure()
    browser.main()
    path = OUTPUT / "actual_e2e.json"
    result = json.loads(path.read_text(encoding="utf-8"))
    result["export_validation"] = verify_exports(result)
    result["scope"] = "Actual unchanged CPU Model 1 + Model 2 + automatic MobileSAM, real HTTP and Chrome; native debug and lossless exports. No expert parent/grade truth."
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    (OUTPUT / "export_roundtrip.json").write_text(json.dumps(result["export_validation"], indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"checks": result["checks"], "export_validation": {key: value for key, value in result["export_validation"].items() if key != "loss_records"}}, indent=2))


if __name__ == "__main__":
    main()
