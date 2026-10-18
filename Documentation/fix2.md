Continue from the completed YOLO26m checkpoint correction. Do not repeat the previous investigation or change the active checkpoint without evidence.

Current verified results:
- Model 2 is configured to use `yolo26m_partdet`.
- Model 1 detected 7 fish in the reference test image.
- Model 2 returned 68 raw full-frame detections, with 15 at confidence >= 0.25.
- The integrated pipeline processed 7 fish; 1 received Class C and 6 remained Ungraded.
- The focused test suite passed 62 tests.
- Roboflow equivalence remains unverified because the exact hosted model version and inference settings are unavailable.

OBJECTIVE:
Determine exactly why 6 fish remain Ungraded and whether valid Model 2 detections are lost between inference and grading.

1. Read the existing YOLO26 diagnostic report, previous `last.pt` report, direct YOLO26 comparison, and the diagnostic reasons recorded for each Ungraded fish. Locate the actual report files; do not invent paths or assume the reports show successful inference.

2. For every fish track, produce a trace containing:
   - Fish/track identifier.
   - Model 1 bounding box and confidence.
   - Model 2 predictions relevant to that fish.
   - Predicted class names and confidence values.
   - Results before and after each filter.
   - Part-to-fish association results.
   - Head, Body, and Tail evidence available to the grader.
   - Final grade and exact reason for remaining Ungraded.

3. Find the earliest stage where the six fish lose sufficient evidence. Distinguish among:
   - No Model 2 detections.
   - Valid detections filtered out.
   - Incorrect class-name or class-ID mapping.
   - Incorrect full-frame/crop assumptions.
   - Incorrect coordinate conversion.
   - Part detections associated with the wrong fish.
   - Tracking or temporal aggregation errors.
   - Grading requirements that cannot be satisfied by the available evidence.

4. Confirm the actual YOLO26m checkpoint metadata, class-name mapping, input size, inference device, and effective confidence and IoU thresholds. Keep these settings consistent between the standalone diagnostic and integrated inference wherever the model supports it.

5. Determine whether the model was trained for full-frame part detection or fish-crop part detection by inspecting available metadata, training configuration, dataset structure, and existing implementation. Do not infer the intended architecture from the filename alone.

6. Add a reproducible regression test using the existing reference image and local weights. Compare direct inference with integrated inference. Where actual expected Roboflow outputs are available, compare boxes and classes using appropriate tolerances. Do not fabricate reference predictions.

7. Fix only demonstrated defects. Preserve the existing scientific grading rules. Do not solve the Ungraded problem by blindly lowering confidence thresholds, forcing missing parts to count as present, assigning default grades, or changing grading weights.

8. Rerun the relevant tests and report the actual results. If local weights, reference images, or report files are unavailable, clearly state which checks could not be completed.

DELIVERABLE:
Provide a per-fish diagnostic table, the confirmed root cause, the minimal code changes, regression results, and any remaining limitations. If no defect is found, explain which additional evidence is needed instead of claiming the pipeline is fixed.