# Final same-backend crowded-fish regression

Detection thresholds, checkpoints and configured backends are identical before and after. All final source hashes match the recorded implementation. Each scenario was run with raw diagnostics disabled and enabled. The two after modes must agree for every fish.

| Scenario | Before (diagnostics off) | Before (diagnostics on) | After (both diagnostic modes) |
|---|---|---|---|
| candidate_previous_four_fish | {'Rejected': 1, 'Ungraded': 3} | {'Ungraded': 4} | {'Rejected': 2, 'Ungraded': 2} |
| candidate_six_fish_failure | {'Ungraded': 6} | {'Ungraded': 6} | {'Rejected': 2, 'Ungraded': 4} |
| intact_isolated_control | {'Ungraded': 1} | {'Ungraded': 1} | {'Ungraded': 1} |
| intact_rotated_negative_slope | {'Ungraded': 1} | {'Ungraded': 1} | {'Class A': 1} |
| natural_overlap_control | {'Class C': 1, 'Ungraded': 5} | {'Class C': 1, 'Ungraded': 5} | {'Class C': 1, 'Ungraded': 5} |
| partially_clipped_control | {'Ungraded': 1} | {'Ungraded': 1} | {'Ungraded': 1} |

## Confirmed six-fish targets

The user identified the fourth and sixth fish from the left as headless. Their detector IDs are 6 and 4. This is user-supplied development truth, not an independent calibrated test cohort.

| Fish | Left-to-right position | Before grade | After grade | After integrity | Source of torso evidence |
|---:|---:|---|---|---|---|
| 4 | 6 | Ungraded | Rejected | confirmed_absent | silhouette_torso_geometry |
| 6 | 4 | Ungraded | Rejected | confirmed_absent | silhouette_torso_geometry |

Confirmed head-removal detection on the two user-identified targets changes from 0/2 before to 2/2 after. This is targeted regression recovery, not an independent recall estimate.

Every per-fish integrity record, failed/passed gate and unchanged source/checkpoint hash is retained in the JSON. Independent calibration and held-out accuracy remain unavailable. User-confirmed targets and qualitative/synthetic controls demonstrate the requested regression behavior without supplying an independent false-rejection-rate estimate.

## Implemented fixes and validation

The demonstrated blockers were diagnostic-only Head candidates vetoing grades, missing Model 2 Body detections blocking an otherwise complete silhouette inspection, and a parent crop removing 13 columns of the fourth fish's foreground. Diagnostic candidates now obey the existing configured evidence thresholds; native silhouette extents expand analysis crops; conservative, independently checked torso geometry can support head integrity without inventing a Model 2 Body detection or supplying normal weighted grades.

For actual segmentation conflicts, bounded positive/negative point refinements reuse the same MobileSAM model, device and frame embedding. Complete candidate masks compete under the existing ownership gates; no pixels are cut or reassigned, no headless score selects a mask, and previously eligible fish remain protected. Native mask overlap supplies the existing association score term without changing its weights, score threshold or margin. Existing accepted and reviewed assignments remain protected. Final ownership is revalidated against the exact mask pixels used to score the association.

The independent anatomical path retains clipping, occlusion, accepted Head, snout, uncertain orientation and contradictory Tail safeguards. The torso fallback uses existing geometry thresholds and does not synthesize detector evidence, grade support or a calibrated rejection confidence. Missing detections alone still cannot cause rejection.

Final relevant regression checks: **422 tests and 21 subtests passed**. The checkpoint comparison covered **six scenes and 19 unique fish**, each with diagnostics disabled and enabled. All final outcomes are invariant to that diagnostic flag. Intact, rotated-intact and partially clipped controls produced no new Rejected results. All checkpoint, grading and calibration configuration hashes are unchanged.

A separate process ran both detectors and MobileSAM on `cuda:0` using the existing memory guards. MobileSAM remained on the GPU with no CPU fallback, and both user-confirmed target fish were Rejected in both diagnostic modes. The [GPU smoke artifact](../results/qa/head_integrity_crowding_stage2/gpu_sam_smoke.json) records the device, checkpoint and final source hashes. Persistent device settings were not changed.
