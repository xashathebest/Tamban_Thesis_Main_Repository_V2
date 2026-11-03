# Non-model anatomical association repair

Executed `docs/additional.md` on November 3, 2026. The fixes address association, contextual cropping, native coordinates, clipping diagnostics, reviewed-mask provenance, grading diagnostics, exports, and the existing viewer. Both trained checkpoints and their inference methods remain unchanged. No retraining, annotation edits, detector-threshold changes, anatomical calibration, or automatic width grading were introduced.

## Confirmed causes and implemented behavior

| Confirmed defect | Resulting behavior |
|---|---|
| An alternative parent that failed acceptance gates still counted toward competing-parent ambiguity. | Only eligible alternatives compete; rejected alternatives retain every score and failed gate. |
| Global optimization could send a duplicate part to its second-choice neighbor to increase total score. | Global one-to-one selection uses independently supported ownership edges. Duplicates remain unassigned rather than being borrowed. |
| An inconsistent optional Tail could demote an independently supported Head. | With distinct reliable Head/Body support, only the conflicting optional Tail is withheld. Required-part uncertainty still causes Ungraded. |
| A guessed bounding-box axis activated hard anatomical order checks. | Unknown orientation remains a hint; reliable supplied axes can activate projection checks. Native two-dimensional conflict checks remain active. |
| Parent-only crops truncated accepted parts that legitimately extended beyond the parent box. | The crop encloses the unchanged parent and exclusively its already-assigned native parts. Extension reuses the existing measurement context margin. Association and Model 2 are not rerun on the expanded pixels. |
| Crop contact and crop-only loss could become `PARENT_FRAME_CLIPPED` / `UG_OUT_OF_FRAME`. | Image and crop diagnostics are separate. Detector-box contact alone leaves native silhouette clipping unknown. Explicit original-image clipping and configured frame-quality rejection remain conservative. |
| Reviewed native masks lost provenance needed to disprove bbox-only clipping. | Shape, native coordinates, parent, original box, frame identity, and reviewer provenance are checked. Genuine foreground contact with the image edge remains rejected. |
| Reviewed part refinement could bypass one-region-per-fish uniqueness. | Conflicting reviewed assignments are withheld as `reviewed_region_ownership_conflict`; confidence does not resolve contradictory review labels. |
| Crop-clamped debug records lost raw coordinates, and other fish's detections could appear rejected by detector postprocessing. | Full-frame raw boxes are retained exactly; detector rejection is separate from parent assignment. Below-threshold records carry the actual reason. Pre-NMS proposals are explicitly unavailable. |
| Preview snapshots omitted association diagnostics; video source IDs could coincide with another stable Fish ID. | The same cached preview carries diagnostics and explicit source-to-display identity mapping. Unproven source ownership is withheld. |
| Queued expandable-card events could restore an older highlighted Fish ID. | Deliberate card selection controls highlighting; stale disclosure events cannot change it. |

The original Body/Head/Tail weights remain 50/30/20. Body and Head remain required. When Tail is unavailable, the same policy uses 62.5/37.5 for Body/Head. Original weighted scores and the pre-fusion verdict remain available. Uncalibrated geometric evidence still has no grading contribution, and centimeters still require validated physical calibration.

Native mask consistency is supporting evidence, not proof of anatomical ownership. Ordinary MobileSAM candidates retain their engineering checks, shadow proposals, review indicators, and unvalidated status. Independently reviewed native masks and exact reviewed part labels can exclude contradictory pixels and resolve documented ownership; successful SAM generation or its predicted mask score cannot do so by itself. Remaining mask failures are reported as overlap, conflicting ownership, incomplete required support, fragmented/contaminated foreground, actual edge contact, or source/provenance failure rather than silently bypassed.

## Reproduction results

The original CSV photo is **`WIN_20260823_20_49_53_Pro.jpg`**, available in `C:/Users/User/Downloads/Class B/`. It is not the separate `20_47_00` photo used in an earlier SAM benchmark. A fresh CPU Model 2 pass reproduces all 22 exported native candidates within 0.000489 pixels and 0.00000155 confidence. Controlled comparisons reuse identical frozen detections and parent boxes on both sides.

The CSV directly reproduces three crop losses in already-assigned evidence: Fish 3 Head lost 18.317 native pixels at its top, Fish 3 Body lost 59.486 pixels at its right, and Fish 5 Body lost 5.811 pixels at its top. The adaptive crop retains all three completely; every original accepted box survives a crop-local/native round trip. This is an automated seven-record regression. Full-precision measurements are in `results/qa/additional/csv_crop_truncation_audit.json`. Fish 3's expanded context reaches the image bottom while its parent rectangle does not, demonstrating why crop contact must remain a distinct diagnostic.

| Cohort | Fish | Raw Head/Body/Tail | Assigned before | Assigned after | Ungraded before | Ungraded after |
|---|---:|---|---|---|---:|---:|
| Original seven-record CSV | 7 | 7/9/6 | 2/4/0 | 2/4/0 | 5 (71.4%) | 5 (71.4%) |
| Current 17 project test photos | 117 | 90/107/46 | 18/67/5 | 24/71/10 | 108 (92.3%) | 105 (89.7%) |
| Ten recorded stress scenes | 56 | 50/59/20 | 8/34/0 | 10/35/3 | 52 (92.9%) | 51 (91.1%) |

These are engineering coverage measurements, **not measured assignment or grading accuracy**. Independent expert parent-to-part labels are unavailable; correct assignments, false associations, and correct grading coverage remain unmeasured/null. The cohorts overlap and must not be combined into an independent accuracy score. The 17-image set also has known historical training exposure. Three frozen real detector cases reproduce supported required-Head recovery, but their physical ownership still requires independent review.

The CSV remains five Ungraded because the existing evidence still fails required-part ownership/containment/score checks. Parts are not borrowed and thresholds are not lowered to make that number smaller. Missing evidence is not labeled as physical damage or occlusion without evidence. Some edge Heads satisfy containment but fail the unchanged ownership score; both facts are now visible. Missing network detections and parts suppressed inside predictor confidence filtering/NMS cannot be recovered by this software repair.

The recorded median association-only times were 1.233 to 2.221 ms for the CSV, 0.647 to 1.084 ms across the 17-image cohort, and 0.458 to 0.938 ms across stress scenes. They exclude inference, segmentation, API, rendering, and model loading. More detailed diagnostics add matching work. Runtime association timing now also excludes shared segmentation preparation, which has its own measured scope. No end-to-end speed improvement or GPU-performance claim is made.

Full candidate decisions, per-fish grading, timings, and 28 paired original-image overlays are in `results/qa/additional/association_comparison.json`, `association_comparison.md`, and `visuals/`. [The reproduction report](additional_reproduction.md) documents source identities, protected detector settings, checkpoint hashes, coordinate/letterbox checks, and commands. [The association audit](additional_association_audit.md) records exact bug fixtures and boundary/review safeguards.

## Viewer and export behavior

The optional **Anatomical Association Debug View** is off by default. Highlight a Fish ID to inspect native raw, assigned, rejected, and ambiguous candidates in the main viewer and read exact reasons inside that fish's expandable evidence card. Unknown frame/coordinate provenance prevents unsafe overlay drawing. Normal view continues to show owned parts only. Class A, B, C, Rejected, and Ungraded grouping is preserved.

Bounding Boxes / Fish Masks, opacity, highlighting, zoom, Model 1 boxes, Model 2 parts, structural controls, review indicators, loading/error/elapsed states, and new-analysis reset remain available. Debug toggles reuse existing data and issue no model or segmentation request. Asset versions were updated so a browser reload retrieves the new frontend.

CSV/XLSX and browser exports append anatomical association diagnostics, part decisions, inference provenance, and raw-detection diagnostics. Existing export columns and complete source events remain intact. Preview records retain `quality_inference`, `model2_debug`, and `model1_detection` with their native source provenance. Video snapshot parts preserve source parent IDs alongside stable display IDs.

## Validation

- Full CPU suite: **1,660 passed, 12 skipped, 7 warnings, 127 subtests passed**, zero failures, 40.86 seconds. Log: `results/qa/additional/final_tests.log`.
- Actual Chrome 156: **23 checks passed**, including main canvas, all controls, source/selection safety, loading completion, zero fetches, unchanged grades, 390-pixel mobile layout, and new-analysis reset. This uses synthetic native-pixel frontend fixtures, not neural inference or ownership ground truth. Artifacts: `results/qa/additional/ui/`.
- JavaScript syntax and `git diff --check` passed.
- All seven historical rows retain their existing weighted results when geometric scoring is disabled. New tests also exercise crop extension, exact native raw boxes, detector/ownership separation, boundary semantics, optional Tail behavior, diagonal fish, overlapping/competing parents, unreliable masks, reviewed provenance/uniqueness, and source-ID collisions.
- Protected source ASTs and full checkpoint hashes are checked against the task baseline. `baseline_source.zip` was explicitly reconstructed from clean-at-task-start tracked HEAD `728380ed518ff54f7c6ccad4e89d574a8e0bf39a` after work began; its manifest does not claim a pre-edit capture timestamp. Real detector verification used CPU without CUDA initialization.

Reproduce the automated suite from the project root with `python -B -m pytest -q -p no:cacheprovider tests`. Browser smoke: `python -B tests/anatomical_debug_browser_smoke.py`. Fixed-detection comparisons reuse the saved inputs with `python -B -m src.evaluation.evaluate_association_repairs --repeats 11`; the separate collection/verification options in the reproduction report perform actual CPU inference and are unnecessary for ordinary replay.

## Exact changed files

All paths below are relative to `Thesis/sardinella-lemuru-ml/`. `docs/additional.md` is the user's input and was not edited. Generated images, source snapshots, JSON reports, and logs under `results/qa/additional/` are QA artifacts.

| File | Change |
|---|---|
| `src/inference/association.py` | Eligible competition, supported one-to-one ownership, optional Tail, orientation and exact diagnostics. |
| `src/inference/preprocessing.py` | Contextual crop enclosing exclusively assigned evidence. |
| `src/inference/yolo_quality_model.py` | Crop integration, native provenance, clipping distinction, detector/ownership debug separation and timing scope. |
| `src/inference/grading_engine.py` | Separate crop loss from original-image clipping while preserving grading requirements. |
| `src/inference/experimental_segmentation.py` | Retain reviewed native mask provenance. |
| `src/inference/mask_ownership.py` | Verify reviewed source proof before disproving bbox-only clipping. |
| `src/inference/reviewed_features.py` | Withhold conflicting reviewed region assignments. |
| `src/api/image_analysis.py` | Preserve/normalize debug coordinates and video source/display IDs. |
| `src/api/segmentation_preview.py` | Reuse anatomical diagnostics in existing previews. |
| `src/api/export.py` | Append four anatomical diagnostic fields. |
| `frontend/app.js` | Optional native debug overlay, per-fish table/export, source-ID safety, stable card highlighting. |
| `frontend/index.html` | Existing-viewer debug controls and refreshed asset versions. |
| `frontend/styles.css` | Minimal debug legend styling. |
| `src/evaluation/evaluate_association_repairs.py` | Frozen-detection comparison, original-image verification, predictor/integrity audit. |
| `tests/test_association_additional_regressions.py` | Matching/orientation/optional-Tail fixes and all seven CSV records. |
| `tests/test_additional_crop_provenance.py` | Crop/native-frame fidelity, postprocessing separation and preview reuse. |
| `tests/test_additional_boundary_semantics.py` | Crop versus original-image grading diagnostics. |
| `tests/test_additional_reviewed_boundary.py` | Reviewed native boundary proof and invalid provenance. |
| `tests/test_additional_reviewed_uniqueness.py` | Post-review one-region-per-fish conflicts. |
| `tests/test_association_reproduction.py` | Exact CSV source/records and frozen real detector cases. |
| `tests/fixtures/association_repair_real_cases.json` | Three frozen real-image software reproductions. |
| `tests/test_anatomical_debug_ui.py` | Viewer, source mapping, CSV/XLSX/browser evidence contracts. |
| `tests/anatomical_debug_browser_smoke.py` | Actual Chrome main-viewer/mobile/reset checks without models. |
| `docs/additional_association_audit.md` | Exact defects, safeguards and association validation. |
| `docs/additional_reproduction.md` | Correct original image, model settings, benchmark scope and limitations. |
| `docs/additional_audit.md` | This integrated report. |
| `README.md` | Link to this implementation and validation report. |
| `TAMBAN_DEEP_CODE_QA_PROGRESS.md` | Independent implementation/validation entry; scientific approval gates remain unchanged. |
