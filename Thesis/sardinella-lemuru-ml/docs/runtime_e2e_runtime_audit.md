# Runtime anatomy and mask-report audit

This follow-up audits the working implementation after `additional.md`. It preserves detector weights, class mappings, confidence/NMS settings, grading weights, calibration gates, and every existing viewer control.

## Confirmed false-grade defect

The full-frame association code calculated whether required Head and Body evidence was geometrically distinct, but only used that information when checking a conflicting Head/Tail set. When Tail was unavailable, execution continued before checking a contradictory required pair. Consequently, the same native detection location could be labeled both Head and Body and satisfy the two required regions. A Head/Body pair with incompatible transverse intervals under an explicitly reliable axis was also accepted.

The correction withholds both required regions as `required_anatomical_group_inconsistent` in two narrow circumstances:

- Their native box centers are exactly coincident.
- An explicitly reliable supplied axis establishes disjoint transverse intervals.

No new center-distance, overlap, confidence, or calibration threshold is introduced. Existing natural overlap with distinct centers remains accepted. A guessed AABB axis or an explicitly unvalidated candidate axis cannot activate the reliable-axis gate. Original boxes, class IDs, confidences, scores, and candidate parents remain in the diagnostics. Contradictory Head/Body evidence is never resolved by choosing whichever has greater detector confidence.

`tests/test_runtime_required_pair_regressions.py` produced **six failures and two passes before the correction**. Its eight initial cases and six shared-helper cases now all pass. Its exact identical-box examples change **Class A to Ungraded** under the same canonical grading policy, with and without Tail. This is a software-safety correction, not a claim about expert labels or measured accuracy on real fish.

The task-start baseline source is replayed explicitly in `results/qa/runtime_e2e/required_pair_reproduction.json`. The 24 real-image baseline payloads, including all 17 current project test photos, contained 19 accepted Head/Body pairs. **Zero** satisfy the new narrow contradiction rule. Their real-image grading coverage is therefore not increased by this change. Per-pair native coordinates and outcomes are in `required_pair_impact.json`.

## Confirmed mask-report defects

An available MobileSAM candidate that passed every engineering check had an empty rejection list. The report treated that empty list as a missing candidate and emitted `Candidate unavailable.`. The same mask remained available for extraction and visualization, so its status and explanation contradicted one another.

The report now states that engineering checks passed while anatomical ownership and grading validation remain unavailable. Rejected candidates retain their exact existing rejection codes. Decoder exceptions also retain their actual error type and message in `backend_error`; this adds diagnostic detail without approving a mask or changing any grading gate.

`tests/test_runtime_mask_report_regressions.py` produced **two failures and two passes before the correction** and all four pass afterward. It checks successful, missing-required-Head, failed-prompt, cached, and multiple-parent cases without any neural inference.

## Validation and conservative limits

After both corrections and shared-helper extraction, the combined new anatomy/mask regressions and existing association, reproduction, optional-Tail, two-model, experimental-segmentation, grading, and reviewed-uniqueness suites passed **111 tests and five subtests in 3.67 seconds on CPU**. A separate mask/preview subset passed **101 tests in 4.05 seconds**. The integrated root report records the final whole-repository result.

An extra ambiguous required-region candidate can still withhold a fish even when a different Head or Body was assigned clearly. That remains conservative: without independent ownership evidence, software cannot assume the ambiguous candidate is a harmless false positive or belongs to the neighbor. Ignoring it merely to improve grading coverage would weaken the ownership standard.

Generated MobileSAM masks still do not establish independent expert ownership. Fragmentation, actual source-image edge contact, conflicting masks, missing required anatomical support, foreign anatomical evidence, and stale or invalid provenance remain rejection conditions. Native reviewed masks retain the separate checked-review path. Ordinary detector boxes remain region evidence, not validated anatomical pixel masks.

The pure weighted grading engine consumes already-selected evidence and its weights are unchanged. `required_pair_geometry(head_bbox, body_bbox, reliable_axis=None)` provides the same narrow check for both inference adapters; full-frame association consumes it directly. Crop callers can apply it to their selected required regions without introducing full-frame ownership thresholds into legacy crop grading. The integrated report records caller integration and adapter-level validation.

## Files

- `src/inference/association.py`: narrow required-pair contradiction handling and diagnostics.
- `src/inference/experimental_segmentation.py`: truthful success explanation and retained backend error details.
- `tests/test_runtime_required_pair_regressions.py`: fourteen anatomy/grading and shared-helper software fixtures.
- `tests/test_runtime_mask_report_regressions.py`: four mask-report fixtures.
- `docs/runtime_e2e_runtime_audit.md`: this report.

No model, training notebook, annotation, detector threshold, or calibration configuration was edited by this audit.
