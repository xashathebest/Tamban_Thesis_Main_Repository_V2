# CODEX TASK: Implement Multi-Model Selection and Inference Management for the Tamban Fish Quality Inspection System

## 1. Project Context

We are developing a dried Sardinella lemuru quality-inspection system using computer vision.

The project already contains multiple trained model files inside the existing `models/` directory. I want the application to use these existing models rather than requiring one hardcoded model.

**Main requirements:**
1. Make YOLO26 the default Model 2.
2. Allow the operator to switch between available models through the UI.
3. Load the correct model weights and inference adapter for the selected model.
4. Ensure Analyze Image and Live Inspection use the selected model consistently.
5. Keep the existing Model 1 whole-fish detector separate from Model 2 part detection.
6. Preserve the grading engine, quality rules, tracking, database, and Excel reporting.
7. Detect and report model-loading or inference errors instead of silently using another model.

Do not rebuild the application from scratch. Inspect the repository and integrate this functionality into its existing architecture.

---

## 2. Inspect the Existing Models Directory

Discover the actual files and inspect their formats, configurations, and intended tasks. The following paths are based on the current project structure shown in the screenshot; verify the exact paths and filenames before implementing anything.

Expected model families include:

- `models/yolo26/`
  - YOLO26 part-detection checkpoint, with a filename resembling `model2_tamban_yolo26m_partdet...`
  - `README.md`
  - `MODEL_REGISTRY.json`

- `models/yolo26n_seg_exp4/weights/`
  - `exp-4.pt`

- `models/efficientnet/`
  - `model2_tamban_effnetv2m_retinar...`

- `models/faster_rcnn/`
  - `model2_tamban_fasterrcnn_r50fpn...`

- `models/fish_detector/weights/`
  - `model1_fish_parent_detector.pt`

- `models/fish_quality/`
  - Inspect all files and determine their actual roles.

The directory also contains other model files. Discover them recursively rather than relying exclusively on the list above.

### Important

Do not assume all these models perform the same task.

Inspect:
- File extensions and actual checkpoint formats.
- Architecture and inference framework.
- Input dimensions and preprocessing requirements.
- Class names and class IDs.
- Whether the model performs object detection, segmentation, classification, or another task.
- Whether weights are complete and loadable.
- Whether model-specific configuration or metadata exists.
- Whether each model is intended for whole-fish detection, part detection, or quality classification.

Do not rename, overwrite, move, delete, or retrain any existing weights.

---

## 3. Establish Model Roles

Maintain the existing two-stage inspection architecture.

### Model 1: Whole-Fish Detector

Default to the existing whole-fish detector:

`models/fish_detector/weights/model1_fish_parent_detector.pt`

Verify the actual path.

Its responsibility is to locate individual dried fish in an image and provide bounding boxes or supported masks for each fish.

It must not be replaced by a Model 2 part detector.

### Model 2: Selectable Part Detection or Quality Model

YOLO26 must be the default selection for the existing Model 2 part-detection workflow.

The model selector must support other existing models only when their capabilities are compatible with the intended workflow.

Do not force an EfficientNet classifier, Faster R-CNN detector, or segmentation model into an incompatible interface. Build or reuse appropriate inference adapters for their actual tasks.

If a model cannot produce the evidence required by the current grading engine, mark it as incompatible with that grading workflow unless a validated adapter exists.

Never fabricate Head, Body, or Tail detections from a model that does not predict those classes.

---

## 4. Create a Central Model Registry

Inspect and reuse `models/yolo26/MODEL_REGISTRY.json` if it already defines useful metadata. Extend it only if needed.

Create or improve a central registry containing the actual available models and their metadata.

Each entry should define, where applicable:

- Stable model ID.
- Display name.
- Model family and architecture.
- Relative checkpoint path.
- Task type.
- Framework.
- Class names and class mappings.
- Input size and preprocessing settings.
- Supported inspection roles.
- Supported inference adapter.
- Availability and compatibility status.
- Optional model-specific settings.
- Default-selection status.

Resolve checkpoint paths relative to the project root, not the current working directory.

Validate that paths stay inside the expected models directory and do not rely on absolute paths from a developer's machine.

The registry must not claim a model is available merely because its filename exists. Validate that it can be loaded successfully.

Do not create fake metadata or invent class names. Obtain class mappings from verified checkpoint metadata or the appropriate model configuration.

---

## 5. Make YOLO26 the Default Model 2

Set YOLO26 as the default Model 2 selection in the model registry and application configuration.

Requirements:
- On a fresh installation, YOLO26 is selected by default.
- On application startup, the selected model is loaded and its status is reported accurately.
- If the user switches models, subsequent inference uses the selected model.
- The UI clearly displays the active model name and task.
- The active model ID is passed through the actual inference pipeline.
- The system must not display YOLO26 as selected while silently running another model.
- The system must not silently fall back to a different checkpoint when loading fails.

If YOLO26 cannot load, show an actionable error and allow the user to select another compatible model.

Persist the operator's selection using the application's existing settings mechanism, if available. If no persistence mechanism exists, implement a minimal one consistent with the existing architecture.

YOLO26 remains the default for new installations even if a different model was selected during a previous session.

---

## 6. Implement the Model Selector in the UI

Add a model-selection control to the existing Live Inspection and Analyze Image interface.

Use a dropdown or equivalent selector with readable names, for example:

- YOLO26 — default
- YOLO26n Segmentation — EXP4
- EfficientNetV2-M — only for its verified task
- Faster R-CNN ResNet-50 FPN — only for its verified task
- Other discovered compatible models

The exact options must come from the validated registry rather than a hardcoded list.

Each option should display or expose:
- Model name.
- Model task.
- Compatibility with the current inspection workflow.
- Availability status.
- Loading status or any error preventing use.

The UI should clearly indicate:
- Selected model.
- Loaded model.
- Model readiness.
- Whether the last inference succeeded.
- Whether the selected model is compatible with the active workflow.

Disable incompatible options for workflows they cannot support, with an explanation of why they are incompatible.

Do not confuse model readiness with successful prediction. A model may be loaded successfully yet produce no valid detections.

Avoid redesigning unrelated parts of the UI.

---

## 7. Integrate Model Selection With the Real Inference Pipeline

This is the most important part.

Trace the complete execution paths for:
- Live Inspection.
- Analyze Image.
- Any batch-image analysis feature.
- Diagnostic inference.
- Any existing API or background worker that performs inference.

Ensure every relevant entry point obtains the active model from the same validated model-selection service.

Do not implement a selector that changes only the UI label.

When the selected model changes:
1. Validate compatibility.
2. Load or retrieve the correct model instance.
3. Verify its checkpoint and class mapping.
4. Update the active model ID.
5. Use the selected adapter for subsequent inference.
6. Update UI status and diagnostic metadata.

Ensure the current analysis does not unexpectedly switch models halfway through processing.

Avoid reloading the same weights on every video frame. Cache loaded model instances where appropriate and unload or release unused models safely.

Do not load every large model into GPU memory simultaneously by default. Prefer lazy loading, controlled caching, and explicit resource management.

If models are switched during live inspection, apply the change safely at a frame boundary or inspection-session boundary.

Record the model ID and checkpoint identity used for each analysis so results can be reproduced.

---

## 8. Preserve the Existing Grading Pipeline

Do not replace the grading engine or change the established grading policy simply to make the model selector work.

Preserve:
- Model 1 whole-fish detection.
- Model 2 part detection and segmentation where applicable.
- Head, Body, and Tail evidence.
- Part-to-fish association.
- Tracking and duplicate-handling safeguards.
- Defect evidence and its existing validation rules.
- Class A, Class B, Class C, and Rejected grading.
- Ungraded handling and reason codes.
- SQLite persistence.
- Excel and CSV reports.
- Calibration and inspection settings.

YOLO26 must feed predictions into the existing grading engine through the correct adapter.

For alternative models, only implement grading integration when their output semantics can be validated against the required evidence.

Do not force a grade when Body evidence is missing. Preserve the existing `UG_MISSING_PART_EVIDENCE` behavior when appropriate.

Do not assume that the highest-confidence prediction always represents the correct grade.

---

## 9. Address the Existing Model 2 Detection Problem

The current application can detect whole fish but frequently marks them Ungraded because Body evidence is missing.

Roboflow detects Head, Body, and Tail on the exact same training image that fails in local Analyze Image.

Investigate whether local inference differs from the successful Roboflow prediction.

For the default YOLO26 model, verify:
- The exact checkpoint loaded.
- Checkpoint identity and model version.
- Actual class names and IDs.
- Model task and adapter.
- Input image dimensions.
- Preprocessing and resizing.
- Original-image inference results.
- Model 1-generated fish crops.
- Raw predictions before application confidence filtering.
- Predictions after filtering.
- Part-association results.
- Final grading inputs and reason codes.

Use the existing diagnostic infrastructure where possible.

Compare the same checkpoint and exact input wherever possible. Do not assume every Roboflow-hosted model has identical behavior to an arbitrary local checkpoint.

If the selected YOLO26 model does not detect the expected parts, expose the raw diagnostic results rather than silently assigning a grade.

Do not automatically retrain or lower production thresholds.

---

## 10. Define Clear Model Compatibility

A model should be selectable for a workflow only if it can satisfy that workflow's input/output contract.

Examples:
- A whole-fish detector is suitable for Model 1.
- A part detector that predicts the required Head, Body, and Tail classes can serve as Model 2.
- A segmentation model may serve as Model 2 if its masks and class outputs can be mapped correctly.
- A whole-image quality classifier cannot automatically replace a part detector.
- An EfficientNet classifier must not be presented as a Head/Body/Tail detector unless its actual trained task supports that behavior.

If a model can only support image-level classification, expose it in a compatible classification or research workflow rather than pretending it provides part-level evidence.

Do not advertise capabilities that have not been verified.

---

## 11. Add Tests

Create unit and integration tests for:

1. Registry discovery and validation.
2. YOLO26 being the default Model 2.
3. Correct resolution of checkpoint paths.
4. Correct class-name mappings.
5. Missing or invalid checkpoint handling.
6. Model-loading failures being visible in the UI.
7. Switching between compatible models.
8. Switching updating actual inference, not just the UI label.
9. Incompatible models being rejected for unsupported workflows.
10. Model selection being consistent between Live Inspection and Analyze Image.
11. Repeated video inference reusing loaded weights rather than reloading per frame.
12. Model switching not mixing predictions from different checkpoints.
13. Existing grading behavior remaining unchanged.
14. Ungraded reason codes remaining correct.
15. Diagnostic reports recording the actual selected model.
16. Existing database and report-export functionality remaining intact.

Use mocks for unit tests where appropriate, and actual local checkpoints for separate integration tests when available.

Tests must not depend on internet access or download weights unexpectedly.

Do not claim a real model works merely because a mocked test passes.

---

## 12. Performance and Resource Management

The application previously experienced webcam lag.

Avoid worsening performance through multi-model support.

Requirements:
- Load models lazily.
- Cache model instances when resource limits permit.
- Avoid inference on the same frame multiple times unnecessarily.
- Do not load all models onto the GPU simultaneously without justification.
- Use the existing device-selection strategy and report whether CPU or GPU inference is active.
- Release resources appropriately when switching models.
- Measure model-load time and inference latency.
- Keep UI updates separate from expensive inference operations where the architecture permits.
- Preserve a stable video frame rate as far as the hardware and selected model allow.

Do not claim a particular frame rate without measurement.

---

## 13. Documentation

Update the relevant README and model documentation with:
- Available models discovered in the repository.
- Their actual verified tasks.
- Which model is the default Model 2.
- How to switch models in the UI.
- How to add another compatible model.
- How checkpoint paths and class mappings are configured.
- How to diagnose model-loading failures.
- How to compare local inference against Roboflow.
- Known limitations and resource requirements.

Do not include fabricated benchmark results.

---

## 14. Final Deliverables

After implementation, report:

1. All models discovered and their verified tasks.
2. Which model is used as Model 1.
3. Which model is used as the default Model 2.
4. How the UI switches between models.
5. The actual checkpoint loaded for each selection.
6. Which models are incompatible with the grading workflow and why.
7. Any confirmed cause of the local YOLO26 detection failure.
8. Files created or modified.
9. Test results, including model-free and actual-checkpoint tests.
10. Measured inference latency where available.
11. Remaining limitations.

### Completion criteria

The task is complete only when:
- YOLO26 is selected by default.
- The UI can switch between verified compatible models.
- Switching changes the actual inference implementation.
- Live Inspection and Analyze Image use the intended active model.
- Model status and errors accurately reflect reality.
- Existing grading rules and exports still work.
- Regression tests pass.
- The application does not silently substitute another model when the selected model fails.

Inspect first, implement incrementally, and verify each change. Do not rewrite working components unnecessarily.