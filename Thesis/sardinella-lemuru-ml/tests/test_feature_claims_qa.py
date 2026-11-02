"""Guard the distinction between grading evidence and image diagnostics."""

import csv
from io import BytesIO, StringIO
import json
from pathlib import Path
import shutil
import subprocess
import unittest

import numpy as np
from openpyxl import load_workbook

from src.api.export import EXPORT_FIELDS, make_csv, make_xlsx
from src.api.domain import FEATURE_CAPABILITIES
from src.inference.grading_engine import GradingConfig, WeightedGradingEngine
from src.inference.part_types import PartDetection


ROOT = Path(__file__).resolve().parents[1]


class FeatureClaimsTests(unittest.TestCase):
    def test_diagnostic_headers_are_standalone_and_field_keys_stable(self):
        fields = ("body_mean_value", "whole_fish_yellow_ratio", "grade_confidence")
        header = next(csv.reader(StringIO(make_csv([], fields).decode("utf-8-sig"))))
        self.assertEqual(header, [EXPORT_FIELDS[field] for field in fields])
        for title in header[:2]:
            self.assertIn("diagnostic only", title)
            self.assertIn("rectangular ROI", title)
        self.assertIn("Support", header[2])

    def test_feature_summary_counts_only_measured_fish(self):
        events = [
            {"analysis": {"color": {"Body": {"status": "measured", "mean_value": 0.5}}}},
            {"analysis": {"color": {"Body": {"status": "unavailable"}}}},
            {"analysis": {}},
        ]
        workbook = load_workbook(BytesIO(make_xlsx(events, ("fish_id",), {})), data_only=True)
        rows = list(workbook["Feature Summary"].values)
        color = next(row for row in rows if row[0].startswith("HSV colour metrics"))
        self.assertEqual(color[1:3], (1, 33.33))
        self.assertIn("not used for grading", color[3])
        empty = load_workbook(BytesIO(make_xlsx([], ("fish_id",), {})), data_only=True)
        self.assertEqual(list(empty["Feature Summary"].values)[4][1:3], (0, 0))

    def test_adjustment_switches_do_not_create_a_grading_rule(self):
        image = np.full((32, 32, 3), 160, dtype=np.uint8)
        parts = [PartDetection.from_source_class(0, 0.9, (0, 0, 32, 32))]
        baseline = WeightedGradingEngine(GradingConfig()).evaluate(1, image, parts, stabilize=False)
        switches = WeightedGradingEngine(GradingConfig(color_adjustments_enabled=True, defect_adjustments_enabled=True)).evaluate(1, image, parts, stabilize=False)
        self.assertEqual(baseline.weighted_scores, switches.weighted_scores)
        self.assertEqual(baseline.final_grade, switches.final_grade)
        self.assertEqual(switches.adjustments, ())
        self.assertTrue(any("scores remain unchanged" in line for line in switches.explanation))

    def test_interface_names_proxies_and_never_advertises_defect_capabilities(self):
        html = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
        javascript = (ROOT / "frontend/app.js").read_text(encoding="utf-8")
        self.assertIn("Diagnostic only", html)
        self.assertIn("do not affect grading", html)
        self.assertIn("calibrated probability of a correct grade", html)
        self.assertIn("not validated defect or shininess detection", javascript)
        self.assertIn("HSV value (brightness proxy)", javascript)
        self.assertEqual(set(FEATURE_CAPABILITIES), {"Head", "Body", "Tail"})

        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js is required for runtime feature-claim checks")
        # Exercise the current feature summary rather than requiring retired
        # explanatory copy. Crack-like evidence must not become a model part
        # capability or a validated defect/grade statement.
        script = r'''
const fs = require("fs"); const vm = require("vm");
const source = fs.readFileSync("frontend/app.js", "utf8");
function include(name) {
  const start = source.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`Missing renderer: ${name}`);
  const next = source.slice(start + 1).search(/\n(?:async )?function /);
  vm.runInThisContext(source.slice(start, next < 0 ? source.length : start + 1 + next));
}
for (const name of ["titleCase", "formatPercent", "analysisFor", "finiteNumber", "asFraction",
  "scoreText", "partFor", "partStatus", "surfaceDamageEvidence", "latestFeatureRows", "surfaceDamageRows"]) include(name);
const inputs = [
  {},
  {analysis: {color: {"Whole Fish": {mean_value: .5}}, surface_damage: {status: "not_detected"}}},
  {analysis: {surface_damage: {status: "suspected", locations: []}}},
  {analysis: {surface_damage: {status: "suspected", locations: [{}], evidence_state: "Validated Damage"}}},
  {analysis: {surface_damage: {status: "suspected", locations: [{x: 1, y: 2, width: 3, height: 4}], evidence_state: "Validated Damage"}}},
];
console.log(JSON.stringify(inputs.map(event => ({features: latestFeatureRows(event), damage: surfaceDamageRows(event)}))));
'''
        result = subprocess.run([node, "-e", script], cwd=ROOT, capture_output=True, text=True, check=True)
        rendered = json.loads(result.stdout)
        for index, item in enumerate(rendered):
            self.assertEqual([row[0] for row in item["features"]], ["Body", "Head", "Tail", "Brightness", "Cracks"])
            self.assertEqual(item["features"][-1][1], "Suspected Damage" if index == 4 else "No reliable evidence")
            damage = dict(item["damage"])
            self.assertEqual(damage["Validation"], "Not validated for crack classification")
            self.assertEqual(damage["Automatic grade effect"], "None; supporting diagnostic evidence")
            self.assertNotEqual(damage["Evidence state"], "Validated Damage")
        self.assertIn("HSV value", rendered[1]["features"][-2][1])


if __name__ == "__main__":
    unittest.main()
