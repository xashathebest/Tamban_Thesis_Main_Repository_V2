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
             "decisionFusionFeatureRows", "decisionFusionBadge", "appendDecisionFusionPanel")
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
