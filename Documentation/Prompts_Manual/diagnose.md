# Task: Diagnose and Fix the Roboflow vs. Local YOLO Inference Mismatch in the Sardinella Lemuru Quality Inspection System

## 1. Context

I am developing a real-time dried Sardinella lemuru (tamban) fish quality inspection system using two YOLO models.

- **Model 1:** Detects each whole fish.
- **Model 2:** Detects the fish's Head, Body, and Tail regions and predicts their grade labels, including Grade A, Grade B, Grade C, and Rejected classes.

The Model 2 labels include:

- Grade_A_Head
- Grade_B_Head
- Grade_C_Head
- Rejected_Head
- Grade_A_Body
- Grade_B_Body
- Grade_C_Body
- Rejected_Body
- Grade_A_Tail
- Grade_B_Tail
- Grade_C_Tail
- Rejected_Tail

Inspect the actual repository to establish the authoritative class list and mapping. Do not assume the list above is complete or that class IDs follow this order.

## 2. The observed problem

I tested the system using the same training/test image in Roboflow and our local application.

In Roboflow, Model 2 correctly detects the visible fish parts. For example, the displayed predictions include:

- Grade_A_Tail at approximately 72–73% confidence
- Grade_A_Body at approximately 86–87% confidence
- Grade_A_Head at approximately 85–87% confidence

In our local application, Model 1 appears to detect a whole fish, but Model 2 part detections are missing or are not displayed as expected. The resulting inspection metrics and grades are also unreliable.

The local application identifies its part model as `YOLO Part Quality Detector (last.pt)`.

Do not assume that this is the same model version as the Roboflow-hosted model. Verify the actual model files, training versions, architecture, class metadata, and inference settings.

The dataset being the same does not prove that the checkpoints or inference pipelines are identical.

## 3. Primary objective

Find and fix the actual cause of the discrepancy between Roboflow inference and local inference.

Do not begin by retraining either model.

Do not merely lower the confidence threshold, change the grading weights, hide the Ungraded state, or force a grade when the evidence is missing.

Do not replace working code or redesign the application unnecessarily.

First inspect the existing implementation and follow the complete inference path from image acquisition to the final rendered prediction.

## 4. Inspect the entire Model 1 and Model 2 pipeline

Trace the relevant code and identify the actual entry points and functions responsible for:

1. Loading model weights from the repository's models directory.
2. Selecting a model through the UI.
3. Reading the webcam frame or uploaded image.
4. Preprocessing and resizing the image.
5. Running Model 1 inference.
6. Extracting the detected fish region.
7. Cropping and preparing the input for Model 2, if the architecture uses crops.
8. Running Model 2 inference.
9. Converting model output coordinates to the original image coordinates.
10. Mapping class IDs to class names.
11. Applying confidence filtering and non-maximum suppression.
12. Associating head, body, and tail predictions with individual fish.
13. Aggregating evidence across frames.
14. Calculating the final fish grade.
15. Rendering the boxes, labels, confidence values, counters, and inspection results.

Follow the real call chain instead of relying on filenames or assumptions.

Inspect all applicable model adapters, configuration files, UI callbacks, image utilities, tracking modules, grading modules, and tests.

## 5. Verify model loading and model selection

Inspect the repository's actual models directory and establish:

- Which Model 1 checkpoint is loaded by default.
- Which Model 2 checkpoint is loaded by default.
- Whether `last.pt`, `best.pt`, or other checkpoints exist.
- Whether the UI-selected model actually changes the model used for inference.
- Whether cached model instances or stale configuration values override the UI selection.
- Whether a missing model silently activates mock mode, a different model, or a fallback.
- Whether the displayed model name matches the checkpoint actually used.
- Whether Model 2 is being called at all during inference.

Use explicit paths relative to the repository or its configured model directory. Avoid paths that depend unexpectedly on the current working directory.

Never silently substitute a mock model or a different checkpoint for a requested production model.

If the requested model is unavailable, report the failure clearly.

Record the resolved checkpoint path and the model's class names in diagnostic output. Where practical, record a file hash to distinguish checkpoints with similar names.

Do not assume `last.pt` is inferior to `best.pt`; determine which file is intended and compare their provenance.

## 6. Compare local inference with Roboflow

Create or extend a standalone diagnostic tool that accepts:

- The exact original image file.
- The selected Model 2 checkpoint path.
- The model's class names.
- A configurable confidence threshold.
- The inference image size and other supported inference parameters.

Run local Model 2 inference directly on the original image, bypassing the webcam, tracking, crop association, temporal aggregation, and final grading.

Save the following:

- The input image dimensions.
- The checkpoint path and hash.
- The model architecture or task type, where available.
- The model's class-name mapping.
- The effective inference settings.
- The raw predictions before application-specific filtering.
- The final predictions after standard model postprocessing.
- Each prediction's class ID, class name, confidence, and bounding-box coordinates.
- An annotated output image.

Compare these results against the predictions from the same image in Roboflow.

If the hosted model version or settings cannot be verified, explicitly document that limitation rather than claiming the two systems use identical models.

Do not invent Roboflow API responses or expected detections. If API access is unavailable, provide a reproducible local diagnostic and explain which comparison still requires a reference export or API response.

## 7. Audit image preprocessing

Compare the actual local inference input against the expected input for the model.

Investigate:

- RGB versus BGR channel ordering.
- RGB versus grayscale conversion.
- Image dtype and numeric range.
- Normalization and pixel scaling.
- Image resizing and aspect-ratio preservation.
- Letterboxing and padding.
- Model inference image size.
- Unexpected rotation or flipping.
- Incorrect image crops.
- Empty or invalid crops.
- Crops that exclude the head, body, or tail.
- Double resizing or double normalization.
- Passing a displayed/resized UI image instead of the original camera frame.
- Incorrect handling of images with different dimensions.

Do not add custom preprocessing blindly. Use the official inference interface for the actual installed model library unless the model's training or deployment requirements demonstrate otherwise.

Ensure that the local direct-inference test can use the original image without passing through the webcam pipeline.

## 8. Audit Model 1 to Model 2 integration

Determine the intended architecture from the repository.

If Model 2 is trained to detect part-level labels in the full image, ensure it receives the appropriate full image.

If Model 2 is trained to detect parts inside individual fish crops, verify that:

- Model 1's bounding box is valid.
- The crop uses the correct coordinate system.
- Crop coordinates are clipped safely to the image bounds.
- The crop contains the complete fish whenever possible.
- The crop is not empty or too small.
- The crop is resized using the expected inference behavior.
- Predictions are translated back to full-image coordinates exactly once.
- The crop's offset is added correctly to the local predictions.

Do not impose a crop-based architecture if the trained model expects the full frame.

If Model 1 misses a fish, record that failure separately from a Model 2 failure.

If Model 1 detects the fish but Model 2 returns no detections, record that distinction explicitly.

## 9. Audit confidence filtering and postprocessing

Compare the raw model predictions with the predictions remaining after every application-level filter.

Check for:

- Different confidence thresholds in the UI and backend.
- Thresholds that are hardcoded or overwritten.
- Incorrect percentage-to-decimal conversions.
- Duplicate or overly aggressive non-maximum suppression.
- Incorrect overlap thresholds.
- Incorrect class filtering.
- Incorrect class ID/name mapping.
- Filters that remove valid head, body, or tail predictions.
- Incorrect handling of segmentation output versus detection output.
- Output parsing that assumes the wrong YOLO API or result structure.
- Predictions discarded because of invalid or incorrectly scaled coordinates.

Ensure the UI displays the actual effective threshold used by inference.

Make the confidence threshold configurable and consistent across the intended inference stages, while allowing explicitly documented stage-specific settings when required.

Do not simply set every threshold to zero.

## 10. Audit the final grading pipeline

A correct part detection should not disappear simply because the grading system cannot yet produce a final fish grade.

Separate these states:

- No whole-fish detection.
- Whole fish detected, but Model 2 returned no part detections.
- Part detections exist, but all were filtered out.
- Part detections exist, but cannot be associated with a fish.
- Part detections exist, but temporal evidence is insufficient.
- Part detections exist, but grading rules are ambiguous.
- A valid final grade was calculated.

Preserve the actual predictions for diagnostic purposes even if the final grade remains Ungraded.

Inspect the current Head/Body/Tail requirements, confidence aggregation, track association, and grading rules. Do not change the scientific grading criteria simply to increase the number of accepted fish.

Verify that the absence of a detection is not automatically interpreted as proof that a part is missing. Distinguish between a confirmed missing part, a model failure, and insufficient evidence.

## 11. Add structured diagnostic logging

Add an optional diagnostic mode that reports one record per inference stage.

For example:

- Frame captured: 640 × 480.
- Model 1 loaded: resolved checkpoint path.
- Model 1 detections before filtering: count.
- Model 1 detections after filtering: count.
- Fish crop created: dimensions and validity.
- Model 2 loaded: resolved checkpoint path.
- Model 2 raw predictions: count.
- Model 2 predictions after filtering: count.
- Class counts and confidence values.
- Part detections associated with each fish.
- Reason for any prediction being discarded.
- Final grading state and reason.

Adapt the format to the existing logging system. Do not log every frame at unrestricted verbosity during normal production operation.

Add a diagnostic option to save the original image, relevant intermediate crops, and annotated predictions for offline comparison.

Avoid exposing sensitive information or writing unbounded image logs.

## 12. Test the exact same image through each stage

Create a regression test or diagnostic script using the exact image from the Roboflow comparison.

The test must exercise these stages independently:

A. Local Model 2 inference on the original image.

B. Model 1 inference on the original image.

C. The real Model 1-to-Model 2 application pipeline.

D. Postprocessing and coordinate conversion.

E. Part-to-fish association.

F. Final grading.

Report the result at every stage so that the first stage where the expected predictions disappear can be identified.

Where expected Roboflow predictions are available, compare them using configurable confidence and bounding-box overlap criteria. Account for legitimate numerical differences rather than requiring identical confidence values.

Do not hardcode the expected prediction count or fabricate successful detections.

If model weights or the reference image are unavailable in the test environment, mark the relevant integration test as blocked and explain the missing prerequisite.

## 13. Webcam performance

The live camera currently appears slow.

After correctness is established, investigate:

- Whether both models are loaded repeatedly.
- Whether model inference blocks the UI thread.
- Whether inference runs on every captured frame unnecessarily.
- Whether image copies and conversions are repeated.
- Whether the model is using CPU or GPU.
- Whether the selected device is supported by the installed PyTorch and YOLO versions.
- Whether model image size and camera resolution are unnecessarily high.
- Whether inference results are processed faster than the UI can display them.

Reuse loaded model instances. Use a bounded latest-frame processing strategy if compatible with the existing architecture. Avoid unbounded frame queues that increase latency.

Measure capture, Model 1 inference, Model 2 inference, postprocessing, and total latency separately.

Do not reduce image resolution or change model behavior until a baseline has been recorded. Any optimization must preserve acceptable detection quality and be validated on the regression image.

## 14. Required regression tests

Add tests for:

- Correct model path resolution.
- UI model selection and actual checkpoint selection.
- Class-name mapping.
- Confidence threshold handling.
- Empty and invalid crops.
- Bounding-box coordinate conversion.
- Model 2 predictions surviving application postprocessing.
- Correct separation of detection failure from grading failure.
- Valid and invalid part-to-fish association.
- Missing weights producing an explicit error.
- Mock mode never activating silently in production.
- Existing grading rules remaining intact unless a demonstrated bug requires a targeted fix.

Run the existing test suite and all relevant new tests.

Use mock models for unit tests when appropriate, but do not treat mock tests as proof that real model inference works.

## 15. Implementation constraints

- Preserve the existing application architecture unless a change is necessary.
- Reuse the models already present in the repository.
- Do not download new weights, retrain models, or change datasets without identifying a specific need and obtaining authorization.
- Do not introduce a second, conflicting inference implementation.
- Do not hardcode absolute machine-specific paths.
- Do not fabricate model predictions or test results.
- Do not silently swallow inference exceptions.
- Keep production inference and demo/mock inference clearly separated.
- Preserve export and database behavior unless a directly related defect is demonstrated.
- Remove files only if you can establish that they are unused and that deleting them will not break tests, deployment, or documented workflows.

## 16. Final deliverables

After investigating and implementing the fix, provide:

1. The confirmed root cause, with references to the relevant files and functions.
2. The complete inference path before and after the fix.
3. Every file changed and why.
4. The exact Model 1 and Model 2 checkpoints selected by the application.
5. Results from direct local inference on the reference image.
6. Results from the integrated application pipeline on the same image.
7. Before-and-after prediction counts and confidence values, where actually measured.
8. Regression-test results, including skipped or blocked integration tests.
9. Webcam latency measurements, if performance changes were made.
10. Any remaining limitations and the evidence required to resolve them.

If the cause cannot be confirmed, do not claim it is fixed. Report the evidence collected, the first unresolved stage, and the next specific diagnostic step.

**Priority order: correct model loading → reproducible direct inference → correct image preprocessing → correct Model 1/Model 2 integration → correct postprocessing → correct grading → performance optimization.**

The primary success criterion is that the same image produces consistent, explainable local Model 2 predictions before and after integration into the application, with no unexplained loss of valid detections.