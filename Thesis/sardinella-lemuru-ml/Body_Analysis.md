# Tamban Fish Inspection — Complete Grading Integration, Body Width Analysis, and UI Redesign

Inspect the existing repository and implement a complete improvement to the current fish inspection and grading system.

**Main objective:** Fix the disconnected Body Width Analysis, make validated width evidence actively contribute to fish classification, and redesign the inspection results into compact, class-grouped, expandable fish cards.

Preserve the existing working functionality. Do not unnecessarily rebuild the detection models, retrain Model 1 or Model 2, or replace the existing weighted grading algorithm.

## 1. Fix the existing Body Width Analysis

The application already calculates pixel dimensions for each fish, but Body Width Analysis displays "Unavailable" even when those measurements exist.

Example from Fish #1:

- Model 1 whole-fish bounding box: 672 × 1511 px
- Model 2 Body bounding box: 583 × 678 px
- Model 2 Head and Tail detections: Available
- Body Width Analysis: Unavailable

Investigate the entire data flow from detection to measurement extraction, grading, and UI rendering.

Requirements:

- Reuse the existing Model 1 and Model 2 bounding-box measurements.
- Ensure both models' measurements refer to the same fish and coordinate system.
- Correctly transform Model 2 crop coordinates back into original-image coordinates when necessary.
- Derive a relative body-width proxy from existing dimensions when geometric conditions allow.
- For approximately axis-aligned fish, use min(Body W, Body H) / max(Whole Fish W, Whole Fish H) as an initial proxy.
- For diagonal or overlapping fish, require reliable orientation-aware measurements before granting width-based grading evidence.
- Avoid marking valid measurements unavailable because of inconsistent property names, asynchronous data updates, or UI-state mismatches.
- Do not fabricate missing values.

Distinguish four statuses: Measured, Unreliable, Missing Detection, and Not Calibrated.

## 2. Make body width actively influence classification

Keep the original weighted grading structure:

- Body: 50%
- Head: 30%
- Tail: 20%

Introduce an additional geometric-support stage after the existing weighted classification.

Calculate a Class C width-support score from 0–10 points, based on how abnormally wide the fish's body is relative to its length.

Requirements:

- Establish normal and abnormal reference ranges from manually verified Class A/B/C fish.
- Do not invent universal pixel thresholds or treat the previous unreliable Colab measurements as validated calibration.
- Use continuous scoring rather than abrupt, arbitrary thresholds.
- Convert width-support points into a bounded, configurable classification contribution.
- Normalize final competing class scores correctly.
- Preserve the original Body/Head/Tail weights.
- Prevent width support from being counted twice.
- Keep the existing Ungraded and Rejected safeguards.
- Width evidence must not independently assign a grade when required Model 2 evidence is missing.
- Allow strong, validated width evidence to change an otherwise borderline Class B decision to Class C when supported by the combined scoring logic.
- Do not automatically promote fish to Class C simply because they have large bounding boxes.

**Critical:** This must be integrated into the real final-grading function, not merely added to the interface.

If valid calibration is missing, retain the feature calculation and display, but disable its grading contribution with a clear reason. Provide the necessary calibration configuration and validation workflow to activate it.

## 3. Redesign results by fish classification

Replace the current lengthy results and separate image-measurements section with one unified inspection-results area.

At the top, display summary counts for:

- Total unique fish detected
- Graded fish
- Ungraded fish
- Class A
- Class B
- Class C
- Rejected

Then group the fish into collapsible categories in this order:

Class A → Class B → Class C → Rejected → Ungraded

Each category should display its fish count and contain the corresponding fish cards.

Provide filter tabs for All, A, B, C, Rejected, and Ungraded. Empty categories can be accessed through their filters without unnecessarily consuming space in the All view.

## 4. Keep all information inside its corresponding fish card

Every detected fish must have exactly ONE main card.

Example structure:

Fish #1 — Class B — Final Support: 54.2%

Expanded details:

**A. Grading Evidence**
- Model 1 detection confidence
- Model 2 Body, Head, and Tail classifications
- Individual part confidence values
- Effective weights
- Original weighted classification and support

**B. Body Width and Geometric Analysis**
- Whole-fish dimensions
- Body bounding-box dimensions
- Relative width proxy
- Orientation and measurement reliability
- Normal reference range
- Width abnormality level
- Class C supporting points
- Actual grading contribution

**C. Image Features and Measurements**
- Whole Fish, Body, Head, and Tail ROI measurements
- Hue, saturation, brightness
- Yellow, brown, dark-area, discoloration, and highlight proxies
- Pixel dimensions
- Missing regions marked as Not Detected

**D. Final Grading Explanation**
- Original weighted grade
- Geometric support contribution
- Final combined grade
- Whether width changed the classification
- Reason for the decision

Do not duplicate the fish's measurements anywhere else on the page.

Use compact tables, tabs, or nested expandable sections to avoid long vertical scrolling.

Collapse detailed evidence by default.

## 5. Improve grading transparency

Clearly distinguish:

- Detection confidence
- Part classification confidence
- Weighted grading support
- Geometric support points
- Final combined classification evidence

These must not be incorrectly presented as interchangeable percentages.

When width affects the classification, show a concise explanation.

For example:

Original Grade: Class B

Width Support: 8/10

Final Grade: Class C

Reason: Validated width abnormality contributed sufficient supporting evidence to change a borderline classification.

This is an interface example, not a predetermined outcome.

If width does not influence the result, display why: normal width, unreliable measurement, missing evidence, disabled feature, or missing calibration.

## 6. Improve handling of Ungraded fish

Ungraded fish must remain visible in their own category.

For each Ungraded fish, display the precise reason, such as:

- No Model 2 part detections
- Insufficient reliable grading evidence
- Ambiguous part-to-fish association
- Missing required body evidence
- Low classification support

Do not use geometric measurements as a shortcut to bypass essential evidence requirements.

Provide clear next-step information without automatically fabricating a grade.

## 7. Add complete export functionality

Provide:

**Export PDF**
- Professional thesis-ready report
- Inspection date, source, and model details
- Overall class distribution
- Grading methodology and thresholds
- Each fish's complete evidence
- Body width analysis and grading contribution
- Image measurements
- Final classification explanations
- Pagination and readable tables

**Export CSV**
- One row per unique fish
- All original measurements
- Part classification confidence values
- Weighted scores
- Relative body width
- Width-support points
- Original and final grades
- Reliability and Ungraded reasons

Allow exporting all fish or the selected class group.

Exports must use the underlying structured results, not only the currently expanded DOM content.

## 8. Prevent incorrect counts and duplicated fish

Ensure that the number of detected fish is based on actual distinct fish detections or stable tracked identities, not repeated frames or UI rerenders.

Preserve fish identity across grading updates where tracking is available.

If a fish's grade changes after additional reliable evidence, update its class group without duplicating the fish or losing its measurement history.

Avoid race conditions between Model 1 detections, Model 2 results, measurements, and grading updates.

## 9. Improve performance and responsiveness

- Avoid recalculating measurements when existing valid results can be reused.
- Do not rerun either model simply because a user expands a fish card.
- Cache appropriate per-fish measurement results.
- Lazy-render large groups and complex measurement tables.
- Ensure a smooth experience with many fish.
- Make the layout responsive for laptop and mobile screens.
- Maintain the existing design system, spacing, typography, and visual consistency.

## 10. Test the entire implementation

Verify these scenarios:

1. A fish with complete Model 1 and Model 2 evidence receives valid dimensions and width analysis.
2. A fish with Body evidence but no Head/Tail still displays its measured dimensions without fabricating missing parts.
3. A fish with no Body evidence displays a proper missing-measurement reason.
4. A rotated or overlapping fish does not receive unreliable Class C width points.
5. A calibrated width contribution genuinely participates in final grading.
6. Missing calibration prevents invalid score adjustments.
7. Class grouping matches the actual final classification.
8. Fish cards contain all their own measurements without duplicate external sections.
9. PDF and CSV exports retain complete information.
10. Existing detection, tracking, and weighted grading continue to function.

Add focused automated tests for measurement extraction, coordinate transformation, grading fusion, missing-value handling, grouping, and exports.

## Final implementation requirements

Implement the changes directly in the existing repository.

Reuse existing utilities and data structures where possible. Avoid placeholder values, mock results, and unnecessary duplicated logic.

After implementation, report:

- Files modified
- Root cause of the unavailable width measurements
- How width evidence is integrated into final grading
- Whether grading influence is enabled or awaiting calibration
- Tests performed and their results
- Any remaining limitations

**Priority order: First fix measurement availability, then implement correct geometric scoring, then redesign the grouped UI, and finally validate exports and overall grading behavior.**

The system should become a cohesive fish-inspection application where each fish has one complete, explainable set of evidence and where calibrated geometric measurements can genuinely improve classification accuracy.