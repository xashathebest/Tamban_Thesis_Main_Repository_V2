# Codex Task: Redesign the Sardinella Lemuru Fish Quality Inspection UI for Usability

## 1. Project context

I am developing a real-time dried Sardinella lemuru (tamban) fish quality inspection system using Python, YOLO Model 1, YOLO26m Model 2, and an existing inspection pipeline.

The detection pipeline has recently improved. The UI currently displays:
- A live camera or image preview.
- The number of fish detected.
- Class A, Class B, Class C, and Rejected counts.
- An Ungraded count.
- Model 1 whole-fish detections and Model 2 part-level evidence.

The current UI has a large, mostly empty inspection area, small text, oversized statistic cards, and insufficient guidance for users who need to understand the inspection results.

Your task is to improve the entire interface so it is professional, intuitive, responsive, and suitable for a college thesis demonstration and future conveyor-belt inspection.

**This is a UI/UX improvement task, not a model-retraining task.**

## 2. Primary objectives

1. Make the camera feed and detection overlays the main focus.
2. Make the grading results easy to understand at a glance.
3. Reduce unused whitespace and improve screen-space utilization.
4. Make the interface understandable to a nontechnical operator.
5. Explain why fish are Ungraded without overwhelming the user.
6. Provide clear controls for starting, stopping, and configuring inspections.
7. Preserve the current working models, inference behavior, association logic, and grading rules.
8. Improve usability on common laptop and desktop screen sizes.

## 3. Inspect the existing application before modifying it

First inspect the repository to identify:
- The actual UI framework and entry point.
- The existing page layout and components.
- The camera and uploaded-image inspection workflows.
- How model selection and configuration are implemented.
- How prediction results and grading counts are produced.
- The existing diagnostic and error-reporting mechanisms.
- Which UI components are reusable.
- The existing CSS, theme, and design conventions.

Use the current architecture and UI framework. Do not introduce a new frontend framework or duplicate the inference pipeline just to redesign the interface.

Before editing, identify the source of the current excessive whitespace and oversized result cards.

## 4. Recommended layout

Redesign the primary inspection page using a clear hierarchy.

### A. Header

Create a compact application header containing:
- Application name: Tamban Quality Inspection System.
- Subtitle: Real-time Sardinella lemuru quality inspection.
- Camera or inspection status.
- Selected model information in a compact status area.
- A settings control.

Use a clean, professional visual style suitable for an academic computer vision system.

Do not place long technical descriptions in the header.

### B. Main inspection workspace

Use a balanced two-column layout on desktop.

**Left/main column: Inspection preview**
- Make the camera or uploaded image preview the dominant element.
- Preserve the original image aspect ratio.
- Prevent the preview from becoming excessively tall or stretching the image.
- Display Model 1 whole-fish bounding boxes and Model 2 part-level predictions using distinct, readable colors.
- Ensure labels remain legible against dark and light backgrounds.
- Avoid labels overlapping excessively where possible.
- Provide a clear empty state when no camera or image is available.
- Display a loading indicator during image analysis.
- Display an understandable error message when camera access or inference fails.

Provide clear controls for:
- Start camera.
- Stop camera.
- Capture or inspect a frame, if supported.
- Upload an image.
- Analyze or reanalyze an image.
- Reset the current image or inspection, where safe.

Only display controls that correspond to real existing functionality. Connect each control to the existing application logic.

**Right/sidebar: Inspection results**
- Present grading counts in compact summary cards.
- Use a responsive grid instead of one excessively tall column.
- Include Fish Detected, Class A, Class B, Class C, Rejected, and Ungraded.
- Make the counts prominent and their labels easy to read.
- Include a short explanation or tooltip for each category.
- Ensure the Fish Detected count is visually distinct from grade counts.
- Display the number of graded fish and the grading coverage when these values can be calculated reliably.
- Never count an Ungraded fish as a successfully graded fish.

Use neutral surfaces, consistent spacing, restrained colors, subtle borders, and clear typography.

Suggested semantic colors:
- Class A: green.
- Class B: blue.
- Class C: amber.
- Rejected: red.
- Ungraded: neutral gray.
- Camera active: a restrained green status indicator.
- Errors: red with explanatory text.

Do not use color alone to communicate status; retain readable text labels.

### C. Inspection details

Below the main workspace, add a collapsible or tabbed details area containing only information that already exists or can be obtained from the current pipeline.

Possible sections:
- Fish-by-fish results.
- Model 2 part detections.
- Confidence values.
- Association status.
- Reasons for Ungraded results.
- Inspection diagnostics.

Each fish record should have a stable identifier where available and display:
- Fish or track ID.
- Final grade or Ungraded status.
- Available Head, Body, and Tail evidence.
- Confidence or support information where meaningful.
- A concise explanation of the result.

Allow the user to expand a fish record for further details rather than showing every technical field by default.

When possible, selecting a fish record should highlight its corresponding detection in the preview. Only implement this if the current rendering architecture supports reliable association between records and boxes.

### D. Ungraded explanations

Ungraded is a legitimate result and must remain visible.

Make it understandable to operators by displaying the actual recorded reason, such as:
- Insufficient part detections.
- Ambiguous part-to-fish association.
- Incomplete evidence.
- Insufficient confidence or support.
- Missing evidence.

Use the real reason provided by the pipeline. Do not invent a reason when one is unavailable.

Offer a short, context-appropriate next step, such as reviewing the fish position or inspecting the diagnostic details. Do not tell operators to retrain the model when the cause is an association or evidence issue.

Never force an automatic grade simply to make the UI look more complete.

## 5. Model and camera controls

Add a compact configuration panel or settings dialog for supported options.

Where available, include:
- Model 1 selection.
- Model 2 selection.
- Effective confidence threshold.
- Camera selection.
- Supported image size or inference configuration.
- Optional diagnostic mode.

The UI must reflect the actual settings used by the backend.

When a model is changed:
- Use the existing model registry and loading mechanisms.
- Confirm the selected checkpoint is actually used.
- Show the correct model name and loading status.
- Handle missing weights and loading failures explicitly.
- Never silently fall back to another model or mock inference.

Avoid exposing long checkpoint paths in the main view. Put technical details in a collapsible diagnostic section.

Do not add configuration controls that do not work.

## 6. Improve visual consistency

Use a consistent design system:
- Clear typography hierarchy.
- Readable body text.
- Consistent spacing and padding.
- Consistent card heights where appropriate.
- Restrained shadows and borders.
- Rounded corners used consistently.
- Clear button hierarchy.
- Accessible text contrast.
- Visible keyboard focus states.
- Clear hover, disabled, loading, and error states.

Avoid:
- Huge statistic cards.
- Excessive whitespace.
- Tiny labels.
- Unnecessary gradients and decorative effects.
- Excessive animation.
- Multiple competing accent colors.
- Oversized headers.
- Technical JSON output in the default operator view.
- Horizontal scrolling at common laptop resolutions.

Keep technical debugging information available without making it the default experience.

## 7. Responsive behavior

Ensure the interface works at:
- 1366 × 768.
- 1440 × 900.
- 1920 × 1080.
- Narrower laptop windows.
- Tablet-sized screens, if supported by the current application.

On smaller screens:
- Stack the inspection preview and results vertically.
- Keep primary controls easy to reach.
- Make result cards wrap cleanly.
- Prevent the preview from overflowing its container.
- Avoid clipping status messages and diagnostic details.

Use the existing framework's responsive layout capabilities rather than hardcoding one screen size.

## 8. Preserve the working inference pipeline

This requirement is critical.

Do not change:
- The selected `yolo26m_partdet` checkpoint.
- Model 1 or Model 2 weights.
- Full-frame Model 2 inference behavior.
- The configured inference image size.
- Preprocessing or postprocessing.
- Class ID/name mappings.
- Part-to-fish association behavior.
- Tracking behavior.
- Grading weights or thresholds.
- Class A, B, C, Rejected, or Ungraded decision rules.

Do not duplicate inference logic inside UI components.

Do not make model inference slower by running redundant inference calls to render additional UI elements.

Use the existing result objects, state management, and callbacks. If UI data is missing, identify the appropriate existing pipeline output or add a minimal, backward-compatible presentation field.

If a backend modification is necessary, explain why it is required and keep it separate from visual changes.

## 9. Performance

The application must remain usable during webcam inspection.

- Avoid unnecessary rerenders.
- Avoid recomputing predictions when only UI presentation changes.
- Do not repeatedly reload models.
- Do not create unbounded queues of webcam frames.
- Keep diagnostic output optional.
- Avoid blocking the UI while model loading or inference is in progress.
- Preserve the existing frame-processing and inference scheduling behavior unless a specific UI integration defect is demonstrated.

Do not sacrifice inference correctness for visual effects.

## 10. Testing and acceptance criteria

After implementing the redesign:

1. Run the existing test suite.
2. Verify that Model 1 and Model 2 are loaded through the existing model registry.
3. Verify that the selected checkpoint is displayed accurately.
4. Verify that all grading counts use actual backend results.
5. Verify that the sum of final grade categories and Ungraded is consistent with the number of fish processed, where the existing counting semantics permit this.
6. Verify that changing UI controls does not silently alter model behavior.
7. Test the camera workflow and uploaded-image workflow separately.
8. Test no-camera, missing-model, inference-error, and no-detection states.
9. Verify that the Ungraded explanations use actual diagnostic reasons.
10. Verify that the layout remains usable at common laptop resolutions.
11. Confirm that the redesign has not changed the grading algorithm or inference settings.
12. Fix any regressions caused by the UI changes.

Do not claim a visual test passed if it was not actually performed.

## 11. Final deliverables

Provide:
- A summary of the UI changes.
- The files changed and the purpose of each change.
- The actual tests run and their results.
- Any functionality that could not be connected because the backend does not expose the required data.
- Any remaining limitations.

The final interface should look and feel like a professional, practical fish-quality inspection dashboard: the live image is central, results are easy to read, controls are obvious, and technical diagnostics remain accessible without overwhelming ordinary operators.