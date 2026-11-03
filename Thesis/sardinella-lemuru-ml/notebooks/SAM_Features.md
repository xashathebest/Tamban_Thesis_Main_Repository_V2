# TAMBAN THESIS — Automatic MobileSAM Masking, Width-Ratio Grading, Crack Detection & UI Simplification

Act as a Senior Computer Vision Engineer, Machine Learning Engineer, Python Optimization Engineer, and Full-Stack Developer.

Implement a comprehensive improvement to the existing Tamban Fish Quality Grading System by integrating automatic MobileSAM segmentation, orientation-aware anatomical width analysis, structural crack detection, and evidence-based grading adjustments.

**Implement these features directly in the existing repository. Do not merely suggest solutions.**

## 1. Automatically run MobileSAM during inspection

MobileSAM is already integrated experimentally and can produce shaded fish masks. However, it currently requires the user to click **Inspect fish masks**, and the generated masks do not contribute to grading.

Change this behavior.

When a user clicks **Run Analysis**:

1. Model 1 V2 detects all fish using its existing bounding boxes.
2. MobileSAM automatically receives those detections as segmentation prompts.
3. Generate candidate masks for each detected fish.
4. Validate fish-specific mask ownership and reliability.
5. Reuse reliable masks for Model 2 anatomical association and feature extraction.
6. Calculate anatomical width ratios and structural crack evidence.
7. Apply only validated feature contributions to the final grading engine.
8. Display the completed inspection and explain the contribution of each feature.

Do not require the user to click Inspect Fish Masks separately.

For video and live inspection, use an adaptive segmentation schedule based on fish tracking and performance constraints rather than running MobileSAM on every frame.

Reuse image embeddings and segmentation results whenever safe.

**Important:** A generated mask is not automatically reliable. Reject masks containing neighboring fish, ambiguous ownership, major clipping, or significant segmentation errors.

Investigate why the previous experimental implementation marked every mask as requiring review. Distinguish genuine mask failures from overly strict or incorrect validation rules, especially false frame-boundary flags caused by coordinate or crop transformations.

Do not bypass reliability checks simply to increase accepted-mask counts.

## 2. Simplify the annotation UI to one toggle

The current interface has multiple options for displaying fish masks and Model 1 boxes.

Replace the separate fish-mask and Model 1 box checkboxes with **one clean, two-state display toggle**:

**Bounding Boxes | Fish Masks**

Expected behavior:

- **Bounding Boxes:** Show the original Model 1 V2 detection rectangles.
- **Fish Masks:** Show the automatically generated MobileSAM masks as shaded fish silhouettes.
- Only one visualization mode should be active at a time.
- Switching modes must not rerun detection, segmentation, or grading.
- Default mask opacity should be approximately 35–40%.
- Fish IDs must remain visible and readable.
- Selecting Fish #N must highlight only its own detections or masks.
- The corresponding fish result card and inspection evidence should remain synchronized.
- Unreliable masks should have a visibly distinct review state.
- The toggle should work in both light and dark themes.

Preserve appropriate Model 2 part annotations when needed for inspection, but do not clutter the primary view with multiple overlapping controls.

Remove redundant experimental interface elements once the automatic workflow is reliable.

Ensure masks and boxes remain correctly aligned when zooming, resizing, switching images, or reanalyzing media.

## 3. Implement anatomical height-to-width and width-to-length analysis

My main goal is to identify fish with an unusually wide or enlarged Body, which may provide supporting evidence toward Class C.

Do not use raw axis-aligned bounding-box height divided by width as the primary anatomical measurement because fish may be horizontal, vertical, or diagonal.

Instead, use validated fish masks to measure the fish along its actual anatomical orientation.

Calculate:

- Longitudinal fish length.
- Transverse maximum body width.
- Representative central-body width.
- Whole-fish oriented length-to-width ratio.
- Body-only width-to-length ratio.
- Width-to-length consistency across the body.
- Visible silhouette reliability.
- Anatomical measurement confidence or reliability status.

Use PCA, oriented geometry, centerlines, and perpendicular cross-sections where appropriate.

Prefer an actual Body-specific mask or a validated Body region associated with the correct fish. Do not assume that a whole-fish mask alone accurately defines the Body, especially near the Head, Tail, or overlapping fish.

Prevent neighboring fish, clipped boundaries, missing anatomy, and mask contamination from inflating body-width measurements.

Record measurement units and distinguish image-relative ratios from real-world physical measurements.

### Required Class C width behavior

Implement a configurable **Class C Width Supporting Evidence** module.

When a reliably measured fish has an unusually broad Body relative to its anatomical length:

- Calculate the degree of width abnormality.
- Compare it with reviewed reference distributions.
- Generate a transparent Class C supporting score.
- Allow validated abnormal-width evidence to contribute toward Class C.
- Explain the contribution in the fish's grading evidence.

Do not automatically classify every wide fish as Class C.

Normal biological size variation, camera perspective, and overlapping silhouettes must be considered.

Do not invent numerical thresholds or claim validated ranges without supporting reference measurements. If calibration data is unavailable, implement the scoring mechanism and diagnostics but keep its automatic grade-changing contribution disabled until calibrated.

## 4. Develop reliable structural crack detection

I want the system to detect structural cracks on dried fish, especially their Bodies.

Use validated fish-specific and Body masks to constrain crack analysis to the correct fish.

Investigate appropriate lightweight OpenCV-based techniques, including:

- Local contrast and illumination normalization.
- Edge and ridge detection.
- Morphological analysis.
- Line continuity and discontinuity.
- Connected-component analysis.
- Crack skeletonization.
- Crack length and width estimation.
- Region-based structural damage indicators.
- Texture comparison around suspected fracture regions.

Distinguish actual crack candidates from:

- Normal fish scales.
- Natural dark pigmentation.
- Discoloration.
- Shadows.
- Fish boundaries.
- Overlapping neighboring fish.
- Fins and anatomical contours.
- Compression artifacts and image noise.

Crack candidates should be displayed as localized overlays, not just a single numerical score.

### Crack size and severity

Implement configurable crack severity categories:

**Minor crack**
- Short, superficial, or localized structural discontinuity.
- Recorded as supporting evidence.
- Does not automatically disqualify Class A unless the validated quality standard requires it.

**Moderate crack**
- More extensive structural damage.
- Contributes stronger negative quality evidence when verified.

**Major crack**
- A clearly established, significant structural fracture or separation.
- Treated as a major quality defect.
- **A fish with a reliably confirmed major crack must not receive Class A, even when its color, texture, Body, and Head predictions otherwise support Class A.**

For confirmed major cracks, apply the configured Class A eligibility restriction and select the final eligible grade according to the established quality criteria. Do not automatically assign Class C or Rejected without sufficient evidence.

Define crack severity using reviewed fish images and expert-approved measurements, preferably normalized by anatomical dimensions.

Do not invent universal thresholds for minor, moderate, or major cracks.

If a crack is only a visual candidate or the Body mask is unreliable, report uncertainty rather than treating it as a confirmed major defect.

## 5. Integrate geometry and crack evidence into grading

Currently, some extracted features are displayed in the CSV but do not affect final grading.

Audit the grading engine and determine which feature measurements are computed, validated, exported, and actually consumed.

Integrate the new measurements into a clearly documented feature-fusion layer.

Preserve the existing Model 2 anatomical grading structure:

- Body: 50%
- Head: 30%
- Tail: 20%
- Body and Head are required for a valid grade.
- Tail is optional.
- Missing or ambiguous Tail redistributes its weight to Body 62.5% and Head 37.5%.
- Unreliable required anatomical ownership results in Ungraded.

Then introduce an explicit distinction between:

1. Primary Model 2 anatomical grade evidence.
2. Supporting geometric evidence.
3. Supporting structural crack evidence.
4. Validated grade eligibility restrictions.

The final grade must remain explainable and traceable.

### Example behavior

**Fish A**
- Strong Class A anatomical evidence.
- Normal Body width.
- No confirmed significant cracks.
- Class A remains eligible.

**Fish B**
- Class B anatomical evidence.
- Reliably measured unusually large Body width.
- Supporting evidence increases the justification for Class C, subject to calibrated grading rules.

**Fish C**
- Strong Class A anatomical evidence.
- Confirmed major Body crack.
- Class A becomes ineligible.
- Final grade follows the applicable validated quality criteria.

**Fish D**
- Apparent wide Body caused by overlapping neighboring fish.
- Unreliable mask ownership.
- Width evidence excluded from grading.

**Fish E**
- Dark scale pattern resembles a crack.
- Structural evidence uncertain.
- No automatic crack-based downgrade.

Do not allow unvalidated features to silently change classifications.

## 6. Correct anatomical ownership before computing features

A recurring issue is that neighboring fish Heads or Tails appear inside another fish's bounding box.

Use the existing OpenCV/SciPy ownership system and new mask evidence to prevent cross-fish contamination.

Before applying width or crack evidence:

- Verify the candidate mask belongs to the intended fish.
- Confirm Body ownership.
- Exclude neighboring fish pixels where reliably possible.
- Check mask overlap conflicts.
- Validate anatomical orientation.
- Reject ambiguous regions.
- Preserve explicit reasons for unavailable measurements.

A visually attractive mask is not sufficient evidence of correct fish ownership.

## 7. Optimize the complete pipeline

The system runs on an NVIDIA RTX 2050 with 4 GB VRAM.

Use automatic segmentation efficiently:

- Run Model 1 V2 and Model 2 with existing optimized inference.
- Load MobileSAM only once when required.
- Reuse a single image embedding across fish prompts.
- Share validated masks across width, crack, color, texture, and grading modules.
- Avoid redundant GrabCut operations.
- Prevent repeated segmentation for the same image.
- Bound memory usage and release temporary tensors.
- Use CPU-side geometry and crack analysis where appropriate.
- Fall back safely when segmentation cannot run.
- Avoid blocking live-camera responsiveness unnecessarily.

For image analysis, prioritize completing the full inspection correctly.

For video, reuse verified masks only when tracking identity and geometry remain valid. Recompute or invalidate masks when fish move or overlap significantly.

Measure real processing time for each stage and overall end-to-end latency.

Do not claim real-time performance until benchmarked.

## 8. Polish the evidence interface

For each fish, provide a clean expandable **Geometry & Structural Evidence** section containing:

**Body geometry**
- Anatomical length.
- Maximum Body width.
- Representative Body width.
- Width-to-length ratio.
- Normal reference range, when calibrated.
- Width abnormality status.
- Class C supporting points.
- Measurement reliability.

**Structural damage**
- Crack candidates detected.
- Minor, moderate, or major severity when validated.
- Crack locations and dimensions.
- Structural confidence/reliability explanation.
- Whether crack evidence affects grading.
- Whether Class A eligibility is restricted.

**Final grading explanation**
- Original anatomical weighted grade evidence.
- Width supporting contribution.
- Structural damage contribution.
- Applied eligibility rules.
- Final classification.

Provide understandable explanations instead of exposing only raw algorithm values.

Keep the primary result cards compact.

Show colored or outlined crack locations on the fish when structural overlays are enabled.

## 9. Implement automated validation and regression tests

Test the full pipeline using isolated and overlapping fish images.

Include:

- Horizontal fish.
- Vertical fish.
- Diagonal fish.
- Narrow and unusually wide fish.
- Whole-fish and Body-specific masks.
- Partial silhouettes.
- Cropped fish.
- Overlapping fish.
- False width enlargement caused by neighbors.
- Small verified cracks.
- Large verified cracks.
- Scale patterns resembling cracks.
- Dark images and uneven lighting.
- Unreliable masks.
- Missing Head or Body.
- No fish detected.
- Image and video processing.

Verify that:

- The mask is correctly associated with its fish.
- Width measurements are orientation-aware.
- Major verified cracks exclude Class A.
- Minor cracks follow calibrated severity rules.
- Unsupported measurements cannot change grading.
- The Boxes/Masks toggle does not rerun analysis.
- Existing Model 1 and Model 2 accuracy is preserved.

Use reviewed reference annotations where available. If crack labels or normal width distributions are missing, create the required validation workflow and report the data still needed before enabling automatic grading contributions.

Do not claim feature accuracy from synthetic tests alone.

## 10. Final implementation report

After making changes, report:

- Files modified.
- Automatic MobileSAM integration status.
- Whether GrabCut was replaced or retained as fallback.
- Measured segmentation time and total latency.
- Width-analysis implementation and reference calibration status.
- Crack detection methodology and verified limitations.
- Actual grading rules activated.
- Features still disabled pending validation.
- UI improvements.
- Regression test outcomes.
- Remaining issues in heavily overlapping fish.

**Non-negotiable requirements**

- Preserve Model 1 V2 YOLO26s.
- Preserve current Model 2 weights and architecture.
- Do not retrain either model.
- Do not modify original annotations.
- Do not assume every generated mask is reliable.
- Do not invent crack severity thresholds.
- Do not alter existing anatomical grading weights.
- Do not use a neighboring fish's pixels as evidence.
- Do not sacrifice classification reliability merely to increase the number of graded fish.
- Do not fabricate performance improvements.

**FINAL OBJECTIVE:** Automatically generate fish-specific MobileSAM masks during inspection, provide a clean Bounding Boxes/Fish Masks visualization toggle, measure reliable anatomical width-to-length ratios, detect and assess crack severity, and integrate validated geometry and structural evidence into the existing Class A/B/C/Rejected grading system—efficiently, transparently, and without retraining the existing models.
