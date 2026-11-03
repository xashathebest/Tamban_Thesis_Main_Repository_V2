# End-to-end validation after the non-model repairs

Completed November 3, 2026. This task validates the working implementation after `additional.md`, fixes newly reproduced software defects, and preserves both trained models, detector settings, grading weights, existing controls, and uncertainty safeguards. The earlier uncommitted changes were retained.

## What ran

The actual unchanged Model 1 V2, Model 2 and MobileSAM ran on CPU for **24 image cases**: seven representative cases and all 17 original project test photos. Cases include the original CSV photograph at 3840 by 2160, natural severe overlap, touching and clipped fish, damaged fish, an isolated real fish, and the same isolated source rotated 25 degrees. Original/derived source pixels, hashes, crop/rotation operations, raw predictions, native masks and complete results are retained.

Every actual case used exactly one Model 1 call, one Model 2 call and one shared SAM encoder execution, with zero GrabCut executions. The paired after run reused those exact neural outputs and native masks while executing the final association, ownership checks, crop projection, feature measurements, grading, serialization and preview pipeline. Strict source/frame/parent-prompt checks prevent replaying a mask on different pixels. The baseline is a real snapshot of this task's starting working files, including the prior repairs: `results/qa/runtime_e2e/baseline_source.zip`.

A separate actual HTTP analysis and Chrome run used a real project test photo through `/api/analyze-image`, normalization, display toggles, browser CSV, backend CSV and XLSX. It overlaps the image cohort and is not an additional independent specimen. The final frontend also ran against that exact saved real result without extra inference. The existing live port-8000 service and training processes were not restarted or reconfigured.

## Before and after

| Check on identical evidence | Before this validation | After repairs |
|---|---|---|
| Original seven-record CSV replay | 5/7 Ungraded; accepted Head/Body/Tail 2/4/0 | Identical |
| 17 current project photos | 105/117 Ungraded; accepted Head/Body/Tail 24/71/10 | Identical |
| Seven representative cases | 25/29 Ungraded; accepted Head/Body/Tail 6/18/3 | Identical |
| Cropping, native-coordinate, trace, approval and call-count invariant violations in 24 cases | 0 | 0 |
| Recomputed arithmetic errors in 16 automatically graded verdicts | 0 | 0 |
| Engineering-passed mask reports incorrectly saying unavailable | 8 | 0 |
| Silently truncated Excel evidence cells in the actual nine-fish HTTP result | 45 | 0; all 347 fields per fish match or reconstruct exactly |
| Exact contradictory Head/Body software fixtures | Could produce Class A with or without Tail | Ungraded, explicit anatomical contradiction; raw measurements retained |
| Native live debug box at `(100,60)` with crop origin `(40,20)` | Incorrectly drawn at `(140,80)` | Correctly drawn at `(100,60)` |
| Remapped video structural overlay | Own evidence hidden or a neighbor's numeric ID could pass | Verified source ownership required |

The cohorts overlap, so detected-parent counts must not be combined into a unique-fish accuracy denominator. Current Model 1 V2 detects ten parents on the original CSV photograph; its fresh run has nine Ungraded. The historical CSV contains seven older recorded parents. The seven-record reproduction retains those exact parents instead of substituting the current ten, and remains five Ungraded. This distinction is preserved in the reports.

The existing required-part weights remain Body 50%, Head 30%, Tail 20%; absent Tail uses Body 62.5% and Head 37.5%. The 16 real automatic verdicts were recomputed from their own accepted confidences with zero arithmetic errors. Original weighted support, final support and native accepted parts remain identical in every paired real scene. Ordinary generated masks remain unvalidated, and width/structural grading contributions remain inactive without the existing validation requirements.

## Remaining causes of Ungraded

On the 17-image cohort, **86 of 105** Ungraded outcomes primarily lack required evidence and **19** primarily have required-region ownership ambiguity. Among Ungraded records, **93 lack an accepted Head** and **46 lack an accepted Body**; these overlap. Three have accepted Head and Body but also unresolved competing required-region candidates, so conservative abstention remains appropriate.

For missing Heads, the best recorded candidate fails only the unchanged ownership score in 45 cases, has no intersection with that parent in 19, remains competing-parent ambiguous in ten, fails score/center/containment in 12, and fails score/containment in seven. Those are gate diagnostics, not expert judgments about the true owner. They separate insufficient ownership evidence from absent network candidates and actual coordinate failures.

The isolated real-fish crop produces Head and Tail candidates but **no Body candidate** at the unchanged production confidence/NMS settings. Its Head also fails the 0.70 ownership score. Rotating the same fish creates Body candidates but still does not establish Head ownership. Expanding the downstream analysis crop cannot recover a detection or fix this decision: Model 2 already ran once on the full source image before association and crop extraction.

In the 17-image cohort, **78/117 masks pass geometry checks**, but only **7/117 pass all engineering ownership/required-support checks**. All remain independently unvalidated. Failures include missing reliable Head/Body support, ambiguous parent ownership, overlapping masks, native foreground edge contact, and contamination by neighboring anatomy. A fish-shaped mask or high SAM score alone does not establish the part's parent. The full mask-reason counts, candidate scores and per-fish explanations are in the saved summaries.

These results locate the principal bottlenecks in required Head association, parent extent/competition, missing detector evidence, and unavailable independently validated mask support. They do not show that every remaining failure is caused solely by Model 2. No score was lowered and no neighboring part was assigned to increase coverage.

## Newly confirmed software defects fixed

1. **Contradictory required anatomy could produce an automatic grade.** Head/Body detections with exactly coincident centers, or disjoint transverse intervals under an explicitly reliable axis, could survive association. The shared `required_pair_geometry()` check now withholds those required parts. Crop mode applies the same exact-center safeguard to its strongest required-region candidates. It introduces no new distance, overlap, confidence or matching threshold. Normal overlap with distinct centers and uncertain axes remains permitted. None of the 19 accepted real required-part pairs in the 24 cases is affected. The false-grade demonstrations are synthetic software fixtures, not expert grading-accuracy measurements.
2. **Live debug coordinates were translated twice.** Native full-frame debug boxes were treated as crop-local by the live renderer. It now honors the declared space exactly once, withholds wrong frame/size snapshots and unknown coordinates, and safely ignores malformed boxes. Legacy crop-local drawing remains supported. The initial narrow reproduction had eight failures and three passes; all 11 cases pass.
3. **Mask availability messages contradicted successful engineering checks.** Successful unvalidated candidates could say `Candidate unavailable.` Reports now distinguish success awaiting validation, actual ownership failures, and backend decoder errors. Approval and grading gates are unchanged.
4. **Excel silently lost complete evidence.** Large anatomical JSON and complete events exceeded Excel's cell limit. Oversized JSON now contains an explicit valid reference; exact ordered text chunks and SHA-256 are in the appended **Extended Evidence** sheet. Smaller workbooks retain existing cells and sheet order, CSV retains complete text, and formula protection is preserved. Actual before/after round trips prove 45 corrupted cells become zero.
5. **Video structural overlays compared different ID namespaces.** Source detector IDs were compared to stable display IDs. Verified source-parent matching now restores the fish's own evidence and rejects numeric collisions with a neighbor, wrong frame, or missing source proof. All other controls and grading remain intact.

## Accuracy and latency

**Fish-level grading accuracy and anatomical association accuracy are unmeasured.** No independent blind expert fish grades or parent-to-part ownership labels exist for these inputs. Conditional grading accuracy, overall automatic accuracy including abstentions, ownership precision/recall and false-association rate therefore remain null. Automatic grading coverage is **12/117 (10.3%)** on the 17 photos and **4/29 (13.8%)** in representative cases. Correct arithmetic and increased coverage cannot establish biological grading accuracy.

The ground-truth inventory found a blank independent fish manifest, pending independent validation gates, known training/test lineage overlap, and an empty/default-disabled expert reference library. COCO part labels and folder class names do not provide independent physical-fish final grades or parent ownership. The existing fish-level evaluation tools can compute the requested accuracy once reviewed source/fish identities, blind final grades, parent/part ownership, visibility state and matching system records are available. This task does not certify those missing scientific gates.

Measured CPU image-pipeline latency across the 17 photos has a **1,755.6 ms median** and **1,978.4 ms p95**. The native 3840 by 2160 source took **11,263.0 ms**, including approximately 3,586 ms color extraction and 1,833 ms shared SAM processing. The separate actual HTTP result took **5,075.612 ms**, including 1,961.776 ms segmentation. Nested scopes must not be added together. The after replay excludes neural inference and cannot be used as a production speedup measurement. These are CPU observations, not deployment-GPU throughput or conveyor counting accuracy.

## Final verification and next improvements

- Full regression: **1,715 passed, 12 skipped, 7 warnings, 127 subtests passed**, zero failures in 43.32 seconds. Log: `results/qa/runtime_e2e/final_tests.log`.
- Actual HTTP/Chrome: **46 checks**, four lifecycle checks and mobile checks passed. Final real-payload frontend replay: **16 checks passed**, zero fetches/model executions. Existing main-view controls, loading/error/elapsed states, selection and reset remain supported.
- All 24 paired cases passed runtime invariant checks; all protected predictor ASTs and full checkpoint SHA-256 values remain unchanged. CUDA stayed uninitialized. JavaScript syntax and `git diff --check` passed.
- New tests cover the shared anatomy check, both inference modes, crop/native live rendering, mask reasons, source-bound replay, formula arithmetic, native trace completeness, Excel reconstruction and video source-ID collisions.

The next useful improvements are independently reviewed ownership/grade labels; review of score-only Head failures and parent extent; representative isolated, rotated, touching and clipped-fish examples for future detector evaluation; reviewed native masks where automatic geometry passes but anatomical ownership is unresolved; and deployment-camera timing/counting studies. No retraining, automatic review approval, reliability relaxation, physical calibration or feature removal was performed here.

Detailed reports: [actual image measurements](runtime_e2e_measurements.md), [anatomical and mask audit](runtime_e2e_runtime_audit.md), and [HTTP/UI/export validation and ground-truth inventory](runtime_e2e_api_ui.md). The new evidence is under `results/qa/runtime_e2e/`, including per-scene before/after payloads, frozen native pixels/masks, summaries, exact candidate rejection reasons, source manifests, paired visualizations and real exported workbooks.

## Files changed in this task

Production: `src/inference/association.py`, `src/inference/experimental_segmentation.py`, `src/inference/yolo_quality_model.py`, `src/api/camera.py`, `src/api/export.py`, `frontend/app.js`, and `frontend/index.html`.

New harness/tests: `src/evaluation/validate_runtime_e2e.py`; `tests/test_runtime_e2e_validation.py`; `tests/test_runtime_required_pair_regressions.py`; `tests/test_runtime_mask_report_regressions.py`; `tests/test_runtime_e2e_camera_coordinates.py`; `tests/test_runtime_e2e_crop_anatomy.py`; `tests/test_runtime_e2e_export_roundtrip.py`; `tests/test_runtime_e2e_video_structure_ui.py`; `tests/runtime_e2e_api_browser_smoke.py`; `tests/runtime_e2e_recorded_ui_smoke.py`.

Documentation: this report, `docs/runtime_e2e_measurements.md`, `docs/runtime_e2e_runtime_audit.md`, `docs/runtime_e2e_api_ui.md`, `README.md`, and `TAMBAN_DEEP_CODE_QA_PROGRESS.md`. Earlier `additional.md` changes remain present; they are documented separately in [the prior report](additional_audit.md).

The subsequent [fresh QA recheck](runtime_e2e_qa_recheck.md) reran the complete suite, 24-case replay, actual HTTP/Chrome and export checks against the final code. All executed checks passed; no additional production edits were needed.
