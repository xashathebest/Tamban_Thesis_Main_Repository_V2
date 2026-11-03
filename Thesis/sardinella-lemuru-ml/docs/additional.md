# TAMBAN THESIS — Fix All Non-Model Issues Causing Ungraded Fish

Act as a Senior Computer Vision Engineer, Python Backend Engineer, and Full-Stack Developer.

Perform a deep code audit and directly fix the **non-model-related problems** in my Tamban Fish Inspection and Quality Grading System.

Previous inspection CSV exports repeatedly showed that Model 2 detects Head and Tail candidates, but many are rejected or unassigned. This results in almost every fish being classified as **Ungraded**, even when anatomical parts appear visible.

**IMPORTANT: Do not retrain, fine-tune, replace, or modify Model 1 V2 or Model 2. Focus entirely on preprocessing, inference integration, anatomical association, segmentation validation, postprocessing, grading logic, and UI reliability.**

## 1. Fix Head, Body, and Tail association

Investigate why valid Model 2 detections are being discarded.

- Trace every raw Head, Body, and Tail detection through the complete association pipeline.
- Fix incorrect bounding-box containment rules, coordinate transformations, thresholds, and matching logic.
- Correct cases where legitimate Head detections become `UNASSIGNED`, `AMBIGUOUS`, or `REJECTED` without sufficient justification.
- Use fish orientation, anatomical position, Body alignment, and spatial relationships to associate parts correctly.
- Apply global one-to-one matching where appropriate to prevent multiple fish from claiming the same anatomical part.
- Never assign a neighboring fish's Head or Tail merely to produce a grade.
- Preserve uncertainty when ownership genuinely cannot be established.

**Priority: Head first, Body second, Tail third.**

## 2. Fix cropping and `PARENT_FRAME_CLIPPED`

Previous CSVs reported numerous `PARENT_FRAME_CLIPPED` states, with some configurations using zero ROI padding.

Investigate and correct:

- Cropping that cuts off visible Heads or Tails.
- Incorrect ROI padding.
- Image-border versus crop-border clipping.
- Local-to-global coordinate conversion.
- Incorrect clipping flags.
- Model input resizing and letterboxing.
- Part detections discarded because of coordinate mismatches.

Use adaptive contextual padding without accidentally assigning neighboring fish parts.

A fish should not be marked as having missing anatomical evidence simply because the analysis crop was too restrictive.

## 3. Fix anatomical ownership using existing masks

MobileSAM already generates fish-shaped candidate masks.

Investigate why masks repeatedly fail reliability checks and why segmentation evidence is not being used.

- Verify mask coordinates against original-image coordinates.
- Fix incorrect overlap, boundary, and clipping checks.
- Distinguish actual fish-mask contamination from overly strict validation.
- Use reliable fish masks as supporting evidence for anatomical association.
- Prevent nearby fish parts from being assigned to the wrong parent.
- Reject masks whose ownership genuinely remains ambiguous.

Do not automatically trust a mask simply because it was generated successfully.

## 4. Audit detection postprocessing

Without changing model weights:

- Verify correct class mappings for Head, Body, and Tail.
- Inspect inference confidence thresholds.
- Review NMS behavior and class filtering.
- Check whether small or thin parts are lost during resizing.
- Identify whether valid predictions disappear before association.
- Preserve raw detections for diagnostic comparison.

Do not blindly lower thresholds or suppress reliability checks. Any changes must be justified through verified examples and regression tests.

## 5. Fix the Ungraded decision logic

Preserve the existing grading requirements:

- Body = 50%.
- Head = 30%.
- Tail = 20%.
- Body and Head are required.
- Tail is optional.
- If Tail is unavailable, redistribute weights to Body 62.5% and Head 37.5%.
- If Body or Head ownership cannot be established reliably, retain Ungraded.

Ensure:

- A missing Tail alone never forces Ungraded.
- Valid Head and Body detections are not incorrectly rejected.
- Optional Tail ambiguity does not invalidate otherwise reliable grading.
- Missing, physically damaged, occluded, clipped, and unassigned anatomical parts are distinguished correctly.
- Grade calculations use the correct parent fish's anatomical evidence.

Do not fabricate missing anatomy or force uncertain fish into a class.

## 6. Add comprehensive debugging

For every fish and anatomical part, record:

- Raw detection confidence.
- Bounding-box coordinates.
- Candidate parent Fish IDs.
- Matching scores.
- Orientation compatibility.
- Mask compatibility.
- Clipping status.
- Acceptance threshold.
- Final assignment status.
- Exact rejection reason.

Add an optional **Anatomical Association Debug View** showing raw detections, accepted parts, and rejected or ambiguous candidates with distinct colors.

Make it possible to identify exactly why a visible Head was not accepted.

Include these diagnostics in CSV exports.

## 7. Improve processing and UI reliability

- Prevent stale annotations and results when analyzing another image.
- Ensure Fish IDs remain consistent across detections, masks, anatomical parts, and grading evidence.
- Reuse MobileSAM masks instead of unnecessarily recomputing them.
- Fix frontend/backend coordinate inconsistencies.
- Preserve the Bounding Boxes / Fish Masks toggle.
- Preserve opacity, highlighting, zoom, and existing annotation settings.
- Show genuine processing progress, errors, and elapsed time.
- Avoid duplicate inference or segmentation operations.

Do not redesign or remove existing working features.

## 8. Test against previous inspection failures

Use previous inspection CSV exports and their corresponding original images when available.

Create regression tests for:

- Clearly visible Heads previously marked unassigned.
- Valid Heads rejected because of crop clipping.
- Diagonal fish.
- Multiple overlapping fish.
- Neighboring Heads inside another fish's bounding box.
- Missing or occluded Tails.
- Fish near image boundaries.
- Unreliable MobileSAM masks.
- Legitimately ambiguous ownership.
- Multiple fish competing for the same detected part.

Compare before and after results using the same input images.

Measure:

- Raw Head/Body/Tail detections.
- Correctly assigned Head/Body/Tail detections.
- False anatomical associations.
- Ungraded rate.
- Correct grading coverage.
- Processing latency.

**Do not count an increased grading rate as an improvement if incorrect anatomical associations also increase.**

If the original images are unavailable, identify that limitation and do not claim the CSV alone proves the corrections are accurate.

## 9. Implement fixes directly

Do not stop at an audit or produce only recommendations.

1. Locate the actual root causes in the repository.
2. Implement corrections.
3. Add appropriate tests.
4. Run regression checks.
5. Verify existing functionality remains intact.
6. Report changed files and before/after results.

Clearly distinguish:

- Confirmed software bugs fixed.
- Association improvements validated with examples.
- Remaining limitations caused by Model 2 detection quality.
- Genuinely ambiguous or occluded fish that should remain Ungraded.

## Final objective

**Ensure that every correctly detected Head, Body, and Tail has a fair opportunity to be associated with its actual parent fish, without incorrect clipping, coordinate errors, overly restrictive rules, or faulty postprocessing.**

Reduce unnecessary Ungraded classifications through verified software corrections—not by weakening confidence or ownership safeguards.

Keep both trained models unchanged so I can independently prepare a better Model 2 V2 dataset.