# Silver fish beside the brown fish: head-integrity audit

The latest screenshot (`Screenshot 2026-11-10 225419.png`, with the preceding full view at `225355.png`) shows `WIN_20261105_14_14_54_Pro.jpg`. The circled silver fish is fourth from the left, detector Fish 6. The adjacent brown fish is Fish 1. The screenshot highlights only Fish 4, so its color overlay alone does not establish the silver fish's grade. A fresh request to the running Analyze Media API confirmed Fish 6 was Ungraded.

The active application uses **Faster R-CNN ResNet-50 FPN v2**, not the YOLO26m used by the earlier comparison. The reproduction uses the same system Python 3.14 executable as the running application, PyTorch 2.11.0+cu128, CUDA 12.8, GPU FP32 detectors and the unchanged configured CPU FP32 MobileSAM backend. These standalone validation runs do not restart the application or change its active model selection.

## Exact failure

Model 1 detects the silver fish as a separate instance. Its native mask has 347,392 foreground pixels and passes the native geometry checks. Only 278 pixels intersect the brown fish mask (0.0800% of the silver mask); this passes the existing pair-overlap gate. The failure is not a merged fish silhouette.

One real Faster R-CNN Body detection (`Grade_B_Body`, confidence 0.661646) competes between Fish 6 and Fish 1. The native-support association scores are 0.844270 and 0.772781; their margin, 0.071489, is below the unchanged required 0.12. The Body is correctly left AMBIGUOUS. Previously that Body-only ownership uncertainty was also treated as a general overlap veto for the independent head-integrity pathway.

No accepted, foreign or unassigned Head detection intersects the silver fish in this reproduction. Faster R-CNN does not supply an accepted Head on the brown fish either; its visible Head must not be described as an accepted detection or borrowed by the silver fish. Model 2 supplies a Tail on each of these fish.

The silver fish's own silhouette already confirms an anterior slanted cut: centerline length 1624.5685 px, axis 118.672 degrees, normalized terminal width 0.3460, rise fraction 0.1954, slope persistence 0.6210 and end asymmetry 0.2837. Its opposite endpoint has posterior geometry. The existing geometric torso check is eligible.

## Repair

The Body detection remains AMBIGUOUS for normal quality grading. Only the separate head-integrity pathway can proceed, and only when the ambiguity is explicitly Body-only, independent torso geometry passes, and a fresh source-bound native-mask check proves that the entire anterior endpoint region is clear of neighboring foreground. Actual Head ambiguity, endpoint contamination, clipping, occlusion, uncertain polarity and unreliable segmentation continue to withhold rejection. No detector assignment is fabricated and no association/confidence threshold is lowered.

## Checkpoint-backed comparison

| Model 2 | Scene | Before grades | After grades |
|---|---|---|---|
| fasterrcnn_r50fpn_v2 | six_crowded | {'Rejected': 1, 'Ungraded': 5} | {'Rejected': 2, 'Ungraded': 4} |
| fasterrcnn_r50fpn_v2 | four_previous | {'Class A': 1, 'Rejected': 3} | {'Class A': 1, 'Rejected': 3} |
| fasterrcnn_r50fpn_v2 | intact_isolated | {'Ungraded': 1} | {'Ungraded': 1} |
| fasterrcnn_r50fpn_v2 | intact_rotated | {'Ungraded': 1} | {'Ungraded': 1} |
| fasterrcnn_r50fpn_v2 | natural_overlap | {'Class C': 1, 'Ungraded': 5} | {'Class C': 1, 'Ungraded': 5} |
| fasterrcnn_r50fpn_v2 | partially_clipped | {'Ungraded': 1} | {'Ungraded': 1} |
| yolo26m_partdet | six_crowded | {'Rejected': 2, 'Ungraded': 4} | {'Rejected': 2, 'Ungraded': 4} |
| yolo26m_partdet | four_previous | {'Rejected': 2, 'Ungraded': 2} | {'Rejected': 2, 'Ungraded': 2} |
| yolo26m_partdet | intact_isolated | {'Ungraded': 1} | {'Ungraded': 1} |
| yolo26m_partdet | intact_rotated | {'Class A': 1} | {'Class A': 1} |
| yolo26m_partdet | natural_overlap | {'Class C': 1, 'Ungraded': 5} | {'Class C': 1, 'Ungraded': 5} |
| yolo26m_partdet | partially_clipped | {'Ungraded': 1} | {'Ungraded': 1} |

**Result:** the silver Fish 6 changes from Ungraded to Rejected with the active Faster R-CNN model. Brown Fish 1 remains Ungraded. The previously successful Faster R-CNN rejections (three in the four-fish image and the rightmost fish in the six-fish image) remain Rejected. YOLO26m's successful results remain preserved.

The fresh native proof covers 102,038 anterior foreground pixels in the existing 30% terminal window. Exactly 0 of these pixels are shared with any neighboring mask. Neighbor source identity is verified for the overlapping brown Fish 1 and Fish 5; their small whole-mask intersections lie outside this anterior region. The Body remains AMBIGUOUS for normal grading and no Body assignment is created.

All compared native MobileSAM masks are byte-identical before and after, so the change is a corrected evidence gate rather than pixel reassignment or segmentation chosen to force a verdict. Both models use unchanged checkpoint, detector, association, calibration and grade settings. The active model-selection file hash is unchanged.

Final relevant inference, association, segmentation, anatomy, upload, export and grading checks passed: 452 tests plus 21 subtests. Real checkpoint validation covered six source scenes with both Faster R-CNN and YOLO26m; all 24 after-runs (two diagnostic modes per model/scene) were invariant to the diagnostic flag.

The final JSON stores every before/after fish record and the complete fresh endpoint-ownership proof, including the per-neighbor anterior-region measurements. These user-confirmed examples and qualitative/synthetic controls are development regressions, not an independently adjudicated head-integrity calibration cohort. No population-level recall or false-rejection estimate is claimed.

## Verification in the running application

The idle backend was reloaded after confirming inspection was stopped, the camera was disconnected, no durable session was active, and event persistence was drained. It retained the same system Python, Faster R-CNN checkpoint SHA-256, Model 1 checksum, 0.25 quality threshold and CUDA devices. No model-selection or grading configuration was changed.

A fresh request through the actual `/api/analyze-image` endpoint then returned Fish 6 as **Rejected / confirmed_absent**, with Body ownership still **AMBIGUOUS**, a verified clear anterior endpoint and zero shared anterior pixels. Brown Fish 1 remained **Ungraded**; rightmost Fish 4 remained Rejected. The resulting image totals were two Rejected and four Ungraded. Live payloads and reload checks are saved as `results/qa/silver_neighbor/before_api.json`, `after_api.json` and `backend_reload_*.json`.

The browser retains its previous analysis until Run analysis is clicked again. Selecting Fish 6 or All fish in the Highlight control reveals the silver fish's updated overlay and individual evidence.

Reproduction (from the project root, using the running dashboard's system Python):

```powershell
& 'C:/Users/User/AppData/Local/Python/pythoncore-3.14-64/python.exe' -B results/qa/silver_neighbor/validate_pipeline.py --phase before
& 'C:/Users/User/AppData/Local/Python/pythoncore-3.14-64/python.exe' -B results/qa/silver_neighbor/validate_pipeline.py --phase after --debug-modes 0 1
& 'C:/Users/User/AppData/Local/Python/pythoncore-3.14-64/python.exe' -B results/qa/silver_neighbor/compare_results.py
```
