# Head-integrity checkpoint comparison

This report records the initial diagnostic-only stage on CPU. The confirmed-image investigation and configured GPU comparison are documented in [crowded-fish experiments](head_integrity_crowding_experiments.md) and [final crowded-fish results](head_integrity_crowding_results.md).

The later [silver-fish neighbor audit](silver_neighbor_head_integrity.md) addresses the active Faster R-CNN configuration specifically. Fish 6's ambiguous Body remains unassigned, while its independently clear anterior endpoint permits Rejected. This result was verified through the reloaded running Analyze Media API; 452 tests and 21 subtests passed.

The subsequent fix recovers the fourth and sixth fish from the left in the confirmed six-fish image as Rejected, with raw diagnostics disabled or enabled. It preserves the previously successful rejection. Final relevant regression validation passed 422 tests plus 21 subtests; real GPU MobileSAM validation also recovered both targets. The historical tables below remain the original first-stage results.

Real local Model 1, Model 2 and MobileSAM checkpoints, CPU FP32, one thread. Detection thresholds remain 0.50 and 0.25; input sizes remain 768. No thresholds were fitted. All compared checkpoint hashes match.

These are development regressions. The four-fish and six-fish captures were inferred from available local files and remain subject to user confirmation. The prior four-fish capture produces four Ungraded results in the original HEAD implementation at the current runtime; its reported successful historical verdict was not reproduced.

| Scenario | Fish | Before grades | After grades | Before integrity | After integrity |
|---|---:|---|---|---|---|
| candidate_previous_four_fish | 4 | {'Ungraded': 4} | {'Ungraded': 4} | {'unverified_ownership': 2, 'ungraded_out_of_frame': 1, 'ungraded_overlapping': 1} | {'unverified_nondetection': 3, 'ungraded_out_of_frame': 1} |
| candidate_six_fish_failure | 6 | {'Ungraded': 6} | {'Ungraded': 6} | {'ungraded_overlapping': 6} | {'unverified_nondetection': 2, 'ungraded_out_of_frame': 3, 'unverified_crop_truncation': 1} |
| intact_isolated_control | 1 | {'Ungraded': 1} | {'Ungraded': 1} | {'unverified_ownership': 1} | {'unverified_crop_truncation': 1} |
| intact_rotated_negative_slope | 1 | {'Ungraded': 1} | {'Ungraded': 1} | {'unverified_ownership': 1} | {'unverified_nondetection': 1} |
| natural_overlap_control | 6 | {'Class C': 1, 'Ungraded': 5} | {'Class C': 1, 'Ungraded': 5} | {'ungraded_overlapping': 6} | {'ungraded_overlapping': 5, 'ungraded_out_of_frame': 1} |
| partially_clipped_control | 1 | {'Ungraded': 1} | {'Ungraded': 1} | {'ungraded_out_of_frame': 1} | {'ungraded_out_of_frame': 1} |

## candidate_previous_four_fish

Source: `C:\Users\User\Downloads\WIN_20261106_15_18_19_Pro.jpg`. SHA-256: `0da3982d1a97bb1cc2ba9b758f1aa14476869647b71797487e58835009975af1`.

| Fish | Owned Model 2 regions | Before integrity | After integrity | After gate reason |
|---:|---|---|---|---|
| 1 | Body | unverified_ownership | unverified_nondetection | Model 2 saw Head evidence on this fish that was not accepted as an owned Head. That miss is not physical absence. |
| 2 | Body | ungraded_out_of_frame | ungraded_out_of_frame | The fish meets the image boundary, so a Head outside the frame is not rejected. The existing grade is not replaced. |
| 3 | none | ungraded_overlapping | unverified_nondetection | Model 2 saw Head evidence on this fish that was not accepted as an owned Head. That miss is not physical absence. |
| 4 | none | unverified_ownership | unverified_nondetection | Model 2 saw Head evidence on this fish that was not accepted as an owned Head. That miss is not physical absence. |

Model 2 returned 242 decoded native detections after model NMS at the 0.001 diagnostic floor; 10 pass the unchanged 0.25 detector threshold. The JSON distinguishes these frame counts from each fish's accepted parts.

| Fish | Missing Head's strongest association score | Missing Body's strongest association score | All failed rejection gates after change |
|---:|---|---|---|
| 1 | 0.047052 | owned | no_unassigned_head: unassigned_head_overlaps_silhouette |
| 2 | 0.592454 | owned | mask_ownership: frame_clipped; native_frame_complete: head_may_be_outside_frame; analysis_crop_complete: analysis_crop_truncates_silhouette; no_unassigned_head: unassigned_head_overlaps_silhouette; anterior_truncation: severed_end_not_confirmed |
| 3 | 0.577339 | 0.69908 | mask_ownership: withheld; no_unassigned_head: unassigned_head_overlaps_silhouette; body_evidence: body_silhouette_missing |
| 4 | 0.083293 | 0.075959 | mask_ownership: withheld; no_unassigned_head: unassigned_head_overlaps_silhouette; body_evidence: body_silhouette_missing |

## candidate_six_fish_failure

Source: `C:\Users\User\Downloads\WIN_20261105_14_14_54_Pro.jpg`. SHA-256: `26022dd3a8218c6859408b8cc818685cf4f79f2c620339867cc37e924c07b918`.

| Fish | Owned Model 2 regions | Before integrity | After integrity | After gate reason |
|---:|---|---|---|---|
| 1 | none | ungraded_overlapping | unverified_nondetection | Model 2 saw Head evidence on this fish that was not accepted as an owned Head. That miss is not physical absence. |
| 2 | none | ungraded_overlapping | ungraded_out_of_frame | The fish meets the image boundary, so a Head outside the frame is not rejected. The existing grade is not replaced. |
| 3 | none | ungraded_overlapping | ungraded_out_of_frame | The fish meets the image boundary, so a Head outside the frame is not rejected. The existing grade is not replaced. |
| 4 | none | ungraded_overlapping | unverified_nondetection | Model 2 saw Head evidence on this fish that was not accepted as an owned Head. That miss is not physical absence. |
| 5 | Body | ungraded_overlapping | ungraded_out_of_frame | The fish meets the image boundary, so a Head outside the frame is not rejected. The existing grade is not replaced. |
| 6 | none | ungraded_overlapping | unverified_crop_truncation | The analysis crop excludes native silhouette pixels. Its artificial edge cannot establish a severed Head. |

Model 2 returned 73 decoded native detections after model NMS at the 0.001 diagnostic floor; 4 pass the unchanged 0.25 detector threshold. The JSON distinguishes these frame counts from each fish's accepted parts.

| Fish | Missing Head's strongest association score | Missing Body's strongest association score | All failed rejection gates after change |
|---:|---|---|---|
| 1 | 0.642425 | 0.201534 | mask_ownership: withheld; no_unassigned_head: unassigned_head_overlaps_silhouette; body_evidence: body_silhouette_missing; anterior_truncation: severed_end_not_confirmed |
| 2 | 0.614568 | 0.026109 | mask_ownership: frame_clipped; native_frame_complete: head_may_be_outside_frame; analysis_crop_complete: analysis_crop_truncates_silhouette; no_unassigned_head: unassigned_head_overlaps_silhouette; body_evidence: body_silhouette_missing; anterior_truncation: severed_end_not_confirmed |
| 3 | 0.135626 | 0.058563 | mask_ownership: frame_clipped; native_frame_complete: head_may_be_outside_frame; no_unassigned_head: unassigned_head_overlaps_silhouette; body_evidence: body_silhouette_missing; anterior_truncation: severed_end_not_confirmed |
| 4 | 0.065677 | 0.191724 | mask_ownership: withheld; no_unassigned_head: unassigned_head_overlaps_silhouette; body_evidence: body_silhouette_missing |
| 5 | 0.64943 | owned | mask_ownership: frame_clipped; native_frame_complete: head_may_be_outside_frame; no_unassigned_head: unassigned_head_overlaps_silhouette |
| 6 | 0.13674 | 0.529785 | mask_ownership: analysis_crop_truncated; analysis_crop_complete: analysis_crop_truncates_silhouette; no_unassigned_head: unassigned_head_overlaps_silhouette; body_evidence: body_silhouette_missing |

## Implementation verified by this comparison

The independent integrity path now retains the signed anatomical axis and reports native centerline/cross-section geometry, terminal widths, truncation and taper. It checks per-neighbor mask ownership, native image clipping, analysis-crop retention, source identity, occlusion and landmark conflicts before rejecting. A missing required quality-grading part does not prevent an otherwise independently eligible head-integrity assessment.

Raw Head candidates without an accepted parent remain possible/unassigned Head evidence. Only an accepted association to a different fish is described as foreign ownership. Both continue to veto head-removal inference. The report lists all passed and failed rejection gates. An anatomical rejection does not reuse the prior weighted grade's score as calibrated head-removal confidence.

Model weights, grade weights, detector/association thresholds and existing safeguards were preserved. Final relevant validation: 337 tests plus 21 subtests passed. The broad run passed 334 tests; three encountered the existing Windows Temp PermissionError and then passed with a project-local pytest basetemp. The focused final safety regression also passed 121 tests. This checkpoint comparison evaluates six scenarios and 19 fish, with all final grades unchanged and no new anatomical rejections. It establishes diagnostic/safety behavior, not improved headless recall.

## Evidence and limitations

The JSON report records every fish's Model 1 box/confidence, Model 2 raw/selected/unassigned counts, accepted parts, strongest association candidates and their failed checks, original grade reason, and complete before/after integrity report. This includes terminal widths, truncation, orientation, clipping, mask ownership and each rejection gate when available.

No independently adjudicated head-integrity cohort was found. The repository's COCO annotations describe the twelve grade/part categories, not fish-level head removal, occlusion or segmentation ownership. The expert-library manifest is empty. Existing silhouette thresholds document three headless and one intact 2026-11-06 profiles plus synthetic controls. Those examples are development data and cannot establish independent recall or false-rejection accuracy. Therefore calibration and biological accuracy remain unverified; no new threshold values were selected from these two captures.

The intact isolated/rotated controls and clipped control are qualitative software controls; the natural-overlap control has no independently verified head-integrity labels. No precision, recall, or false-rejection-rate claim is made from them. Inspect the complete JSON and provide a separate locked calibration cohort and held-out evaluation cohort with specimen lineage, head-integrity truth, overlap/clipping state and independent reviewers before reporting those metrics.

Reproduce from the project root:

```powershell
.\.venv\Scripts\python.exe -B results/qa/head_integrity_improvement/evaluate.py --phase before
.\.venv\Scripts\python.exe -B results/qa/head_integrity_improvement/evaluate.py --phase after
.\.venv\Scripts\python.exe -B results/qa/head_integrity_improvement/compare.py
```
