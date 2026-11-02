"""Rendered class counts partition the counted fish, with no extra graded bucket."""
from __future__ import annotations

import csv
import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_session_totals_show_one_exclusive_bucket_per_counted_fish() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for rendered session-count checks")
    with (ROOT / "tests/fixtures/fish-inspection-upload-all.csv").open(encoding="utf-8-sig", newline="") as source:
        historical = [json.loads(row["Complete fish event"]) for row in csv.DictReader(source)]
    cases = [
        {"rows": [], "expected": [0, 0, 0, 0, 0, 0]},
        {"rows": historical, "expected": [7, 0, 2, 0, 0, 5]},
        {"rows": [
            {"id": 1, "quality": "Class A"},
            {"id": 2, "analysis": {"final_grade": "Class B"}},
            {"id": 3, "quality": "Class C"},
            {"id": 4, "quality": "Rejected"},
            {"id": 5, "quality": "Ungraded"},
            {"id": 6, "quality": "Unexpected grade"},
            {"id": 7, "quality": "Class B", "manual_grade": "Class A"},
            {"id": 8},
        ], "expected": [8, 2, 1, 1, 1, 3]},
    ]
    script = r'''
const fs = require("fs"); const vm = require("vm");
const source = fs.readFileSync("frontend/app.js", "utf8");
const cases = JSON.parse(fs.readFileSync(0, "utf8"));
vm.runInThisContext(source.match(/^const sessionGradeBuckets = .*;$/m)[0]);
function include(name) {
  const start = source.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`Missing renderer: ${name}`);
  const next = source.slice(start + 1).search(/\n(?:async )?function /);
  vm.runInThisContext(source.slice(start, next < 0 ? source.length : start + 1 + next));
}
for (const name of ["analysisFor", "eventValue", "aiFinalGrade", "manualGrade", "resultGrade", "renderResultsDashboard", "renderKpis"]) include(name);
class Element {
  constructor(tag = "div") { this.tag = tag; this.children = []; this.dataset = {}; this.attributes = {}; this.classList = {toggle() {}}; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener() {}
  querySelector() { return null; }
  get childElementCount() { return this.children.length; }
}
global.document = {createElement: tag => new Element(tag)};
global.rememberResultsDisclosures = () => {};
global.formatPercent = value => `${Number(value).toFixed(1)}%`;
global.kpiCards = new Map(); global.secondaryKpiCards = new Map();
global.$ = () => new Element();
global.kpiCard = () => {};
let primaryCards = [];
global.reconcileCards = (container, cache, cards) => { if (cache === kpiCards) primaryCards = cards; };
const results = cases.map(({rows}) => {
  global.resultsSource = "live"; global.resultsFilter = "All"; global.recentHistoryKey = null;
  global.resultsRenderedFilter = null; global.renderedResultsSource = null; global.resultsEvents = [];
  global.resultDatasets = {live: {rows, scope: "fixture", metadata: {source_name: "Fixture"}}};
  global.resultDisclosureStates = new Map();
  global.elements = {resultsCounts: new Element(), resultsGroups: new Element(), resultsSource: new Element(), resultsSummary: new Element(), kpiGrid: new Element(), threshold: new Element()};
  renderResultsDashboard(null, {renderOnly: true});
  const cards = elements.resultsCounts.children.map(card => ({category: card.dataset.resultsFilter, label: card.children[0].textContent, count: Number(card.children[1].textContent)}));
  const groups = elements.resultsGroups.children.filter(group => group.tag === "details").map(group => ({category: group.dataset.grade, count: Number(group.children[0].children[1].textContent)}));
  renderKpis({counters: {total: rows.length}, quality_counters: {"Unexpected grade": 1000, "Graded fish": 1000}, detection_confidence_threshold: .5});
  return {cards, groups, primaryCards};
});
console.log(JSON.stringify(results));
'''
    process = subprocess.run([node, "-e", script], input=json.dumps(cases), cwd=ROOT, capture_output=True, text=True, check=True)
    for actual, case in zip(json.loads(process.stdout), cases):
        assert [card["category"] for card in actual["cards"]] == ["All", "Class A", "Class B", "Class C", "Rejected", "Ungraded"]
        counts = [card["count"] for card in actual["cards"]]
        assert counts == case["expected"]
        assert sum(counts[1:]) == counts[0] == len(case["rows"])
        assert {group["category"]: group["count"] for group in actual["groups"]} == {
            card["category"]: card["count"] for card in actual["cards"][1:] if card["count"]
        }
        assert actual["primaryCards"][0][:2] == ["Fish detected", len(case["rows"])]
        assert all(card[0] not in {"Graded fish", "Unexpected grade"} for card in actual["primaryCards"])

