"""Execute the dashboard's explanation functions without models or a browser."""
from pathlib import Path
import re
import shutil
import subprocess

import pytest


def test_explanation_shows_fallback_conflicts_weights_and_anatomical_hold():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable for the dashboard logic check")
    source = (Path(__file__).resolve().parents[1] / "frontend/app.js").read_text(encoding="utf-8")
    names = ("anatomicalReviewHeld", "decisionFusionEvidence", "decisionFusionState", "decisionFusionSummaryRows",
             "decisionFusionFeatureRows", "decisionFusionClassRows", "decisionFusionBadge", "appendDecisionFusionPanel")
    functions = []
    for name in names:
        match = re.search(r"function " + name + r"\([^\n]*\)[ \t]*\{[\s\S]*?(?=\nfunction |\Z)", source)
        assert match, name
        functions.append(match.group(0))
    script = "\n".join(functions) + r'''
const assert = require("node:assert/strict");
function analysisFor(event) { return event.analysis || {}; }
function scoreText(value) { return typeof value === "number" && Number.isFinite(value) ? `${Math.round(value * 100)}%` : "Unavailable"; }
function element() { return {children: [], append(...items) { this.children.push(...items); }}; }
const document = {createElement: element};
function appendResultTable(parent, headers, rows) { parent.append({headers, rows}); }
const fallback = {analysis: {feature_fusion: {decision_fusion: {
  mode: "model2_only", model_only_prediction: "Class A", final_fused_prediction: "Class A",
  decision_state: "AGREEMENT", agreement_validated: false, review_required: false,
  configured_weights: {model2:.7,size:.15,cracks:.05,color:.05,texture:.05},
  effective_weights: {model2:.7,size:0,cracks:0,color:0,texture:0}, unallocated_supporting_weight:.3,
  features: {size:{eligible:false,reliability:0,reasons:["annotator_verified_reference_unavailable"]}},
}}}};
assert.equal(decisionFusionState(decisionFusionEvidence(fallback)).label, "Model 2-only fallback");
const rows = decisionFusionFeatureRows(fallback);
assert.equal(rows[0][3], "15%"); assert.equal(rows[0][4], "0%");
assert.match(rows[0][6], /annotator_verified_reference_unavailable/);
const summary = decisionFusionSummaryRows(fallback);
assert.match(summary.find(row => row[0] === "Evidence Agreement")[1], /Unavailable/);
const panel = element(); appendDecisionFusionPanel(panel, fallback);
assert.equal(panel.children.length, 1);
const contributing = JSON.parse(JSON.stringify(fallback));
Object.assign(contributing.analysis.feature_fusion.decision_fusion, {
  mode:"calibrated_fusion", contribution_target_grade:"Class B", review_required:true,
  model2_class_probabilities:{"Class A":.4,"Class B":.5,"Class C":.05,"Rejected":.05},
  feature_only_class_support:{"Class A":.2,"Class B":.7,"Class C":.05,"Rejected":.05},
  per_class_combined_support:{"Class A":.34,"Class B":.56,"Class C":.05,"Rejected":.05},
  features:{size:{eligible:true,assessment:"Class B",used_for_grading:true,reliability:.8,
    weighted_class_contributions:{"Class B":.21},class_support_delta:{"Class B":.06}}},
});
assert.equal(decisionFusionFeatureRows(contributing)[0][5], "21.00 support points to Class B; +6.00 points vs Model 2");
assert.equal(decisionFusionClassRows(contributing)[1][2], "+6.00");
assert.equal(decisionFusionClassRows(contributing)[1][3], "No contribution");
assert.equal(decisionFusionClassRows(contributing)[0][2], "Not recorded");
assert.equal(decisionFusionClassRows(contributing)[1][1], "50.00");
assert.equal(decisionFusionClassRows(contributing)[1][6], "70.00");
assert.equal(decisionFusionClassRows(contributing)[1][7], "56.00");
const recovered = JSON.parse(JSON.stringify(contributing));
Object.assign(recovered.analysis.feature_fusion.decision_fusion, {model_only_prediction:"Ungraded", review_required:false,
  baseline_score_review_reasons:["UG_LOW_MARGIN"], resolved_score_review_reasons:["UG_LOW_MARGIN"]});
assert.equal(decisionFusionSummaryRows(recovered).find(row=>row[0]==="Original score uncertainty")[1], "Close class tie");
assert.match(decisionFusionSummaryRows(recovered).find(row=>row[0]==="Score uncertainty resolved by features")[1], /^Yes;/);
assert.equal(decisionFusionSummaryRows(fallback).find(row=>row[0]==="Score uncertainty resolved by features")[1], "None resolved");
contributing.analysis.feature_fusion.decision_fusion.features.size.class_support_delta["Class A"] = -.06;
assert.equal(decisionFusionClassRows(contributing)[0][2], "-6.00");
const classTable = element(); appendDecisionFusionPanel(classTable, contributing);
assert.deepEqual(classTable.children[0].children.find(child => child.headers?.[0] === "Class").rows, decisionFusionClassRows(contributing));
assert.equal(decisionFusionClassRows(fallback)[0][1], "Not calibrated");
assert.equal(decisionFusionClassRows(fallback)[0][2], "No contribution");
assert.match(decisionFusionSummaryRows(contributing).find(row=>row[0]==="Score contribution target")[1], /automatic acceptance withheld/);
delete contributing.analysis.feature_fusion.decision_fusion.features.size.weighted_class_contributions;
assert.equal(decisionFusionFeatureRows(contributing)[0][5], "Contributed; amount not recorded");
assert.equal(decisionFusionFeatureRows(fallback)[0][5], "No contribution");
const tied = JSON.parse(JSON.stringify(contributing));
Object.assign(tied.analysis.feature_fusion.decision_fusion, {
  model2_leading_grades:["Class A","Class B"], feature_only_prediction:null,
  feature_only_leading_grades:["Class B","Class C"], tie_resolving_features:["size"],
});
tied.analysis.feature_fusion.decision_fusion.features.size.leading_grades = ["Class B","Class C"];
assert.equal(decisionFusionSummaryRows(tied).find(row=>row[0]==="Model 2 calibrated leading grades")[1], "Tied: Class A / Class B");
assert.equal(decisionFusionSummaryRows(tied).find(row=>row[0]==="Feature-only supporting prediction")[1], "Tied: Class B / Class C");
assert.equal(decisionFusionSummaryRows(tied).find(row=>row[0]==="Features distinguishing tied Model 2 grades")[1], "size");
assert.equal(decisionFusionFeatureRows(tied)[0][1], "Tied: Class B / Class C");
tied.analysis.feature_fusion.decision_fusion.combined_leading_grades = ["Class A","Class B"];
tied.analysis.feature_fusion.decision_fusion.contribution_target_grade = null;
tied.analysis.feature_fusion.decision_fusion.features.size.weighted_class_contributions = {"Class A":.15,"Class B":.15};
assert.match(decisionFusionSummaryRows(tied).find(row=>row[0]==="Score contribution target")[1], /^Tied: Class A \/ Class B;/);
assert.equal(decisionFusionFeatureRows(tied)[0][5], "Contributed; see class support table");
const major = JSON.parse(JSON.stringify(fallback));
Object.assign(major.analysis.feature_fusion.decision_fusion, {mode:"calibrated_fusion",agreement_validated:true,
  decision_state:"MAJOR_DISAGREEMENT",review_required:true,final_fused_prediction:"Ungraded",
  disagreement_reasons:["size and color strongly contradict Model 2"],evidence_agreement_score:.3});
assert.equal(decisionFusionBadge(major).className, "fusion-state fusion-state-major");
assert.equal(decisionFusionSummaryRows(major).find(row=>row[0]==="Automatic or human review")[1], "Human review required");
fallback.analysis.structural_evidence = {regions:{Head:{state:"confirmed_absent",conflict:false}}};
assert.equal(decisionFusionBadge(fallback).className, "fusion-state fusion-state-critical");
assert.equal(decisionFusionSummaryRows(fallback).find(row=>row[0]==="Automatic or human review")[1], "Human review required");
assert.equal(fallback.analysis.feature_fusion.decision_fusion.model_only_prediction, "Class A");
console.log("Fusion explanation logic passed");
'''
    result = subprocess.run([node, "-e", script], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


def test_export_headers_include_reliability_weights_and_per_class_support():
    from src.api.export import EXPORT_FIELDS
    assert "evidence_agreement_score" in EXPORT_FIELDS
    assert "fusion_feature_reliability" in EXPORT_FIELDS
    assert "fusion_configured_weights" in EXPORT_FIELDS and "fusion_effective_weights" in EXPORT_FIELDS
    assert "fusion_class_support" in EXPORT_FIELDS
    assert "fusion_source_contributions" in EXPORT_FIELDS
    assert "fusion_feature_class_deltas" in EXPORT_FIELDS
    assert "fusion_resolved_score_reasons" in EXPORT_FIELDS
    assert "fusion_model2_leading_grades" in EXPORT_FIELDS
    assert "fusion_feature_leading_grades" in EXPORT_FIELDS
    assert "fusion_combined_leading_grades" in EXPORT_FIELDS
    assert "fusion_tie_resolving_features" in EXPORT_FIELDS
