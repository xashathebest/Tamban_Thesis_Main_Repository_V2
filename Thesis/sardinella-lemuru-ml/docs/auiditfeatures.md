# TAMBAN THESIS — Improve Multi-Feature Fish Grading and Reduce Unnecessary Ungraded Results

Act as a Senior Machine Learning Engineer, Computer Vision Engineer, and Python Backend Developer.

Improve the actual fish-quality grading intelligence by implementing meaningful multi-feature evidence fusion. The system must not rely excessively on Model 2 confidence scores while ignoring structural cracks, Body width, color, and texture.

Implement the improvements directly in the existing repository.

**Do not retrain or replace Model 1 V2 or Model 2, and do not modify the frontend UI unnecessarily.**

## 1. Required Anatomical Evidence

Preserve these requirements:

- Head detection and correct fish ownership are required.
- Body detection and correct fish ownership are required.
- Tail detection is optional.
- Missing Tail must not automatically result in Ungraded.
- Within anatomical evidence, retain Body 50%, Head 30%, and Tail 20%.
- When Tail is unavailable, redistribute the anatomical contribution to Body 62.5% and Head 37.5%.

Separate anatomical detection confidence from actual quality grading evidence.

Do not reject correctly detected and reliably associated anatomy merely because its confidence score is moderately low. However, never assign a neighboring fish's anatomy just to obtain a grade.

## 2. Implement Updated Feature-Fusion Weights

Use these initial configurable weights:

| Feature | Weight |
|---|---:|
| Anatomical Model 2 quality evidence | 40% |
| Structural cracks and damage | 30% |
| Body width and geometry | 15% |
| Color, brightness, oiliness, and discoloration | 10% |
| Texture and surface condition | 5% |
| **Total** | **100%** |

These are experimental starting weights. Validate and calibrate them against expert-reviewed fish grades before treating them as established grading standards.

Each feature must generate class-specific supporting evidence for Class A, B, C, or Rejected.

Combine actual feature evidence with reliability-aware weighting. Do not simply add raw model confidence percentages.

Unavailable features must not be treated as zero-quality evidence. Redistribute eligible weights transparently when optional evidence is unavailable, while reporting evidence coverage and uncertainty.

## 3. Prioritize Structural Crack Detection — 30%

Structural cracks are one of the most important quality indicators.

Implement reliable detection and assessment of cracks using correctly owned Body regions and segmentation evidence.

Analyze:

- Small localized cracks.
- Moderate structural cracks.
- Large cracks.
- Crack length relative to fish size.
- Crack width and depth indicators where visually measurable.
- Crack location and affected Body area.
- Whether cracks are superficial or indicate major structural damage.

### Grading behavior

- Small cracks may still be present in a **Class C** fish when the combined evidence supports Class C.
- More noticeable cracks may be present in a **Class B** fish when its overall condition supports Class B.
- A confirmed major structural crack must prevent Class A.
- More severe cracks must not automatically imply better quality than smaller cracks.
- Crack severity alone must not force a particular grade; evaluate the surrounding defects, anatomical quality, and overall evidence.
- Extensive damage may support Class C or Rejected when the validated quality criteria justify it.

Avoid false detections from scales, shadows, natural pigmentation, fins, and overlapping fish.

Use reviewed examples to calibrate crack severity. Do not invent universal crack-size thresholds.

Ensure validated crack evidence contributes the configured 30% to the final quality assessment.

## 4. Give Abnormal Body Width Meaningful Influence — 15%

Measure fish geometry using segmentation masks and orientation-aware calculations.

Evaluate:

- Anatomical fish length.
- Maximum Body width.
- Representative Body width.
- Width-to-length ratio.
- Unusually enlarged or swollen Body appearance.
- Width consistency across the Body.

**A fish with an abnormally large Body width relative to its length should receive supporting evidence toward Class C.**

However:

- Do not automatically classify every wide fish as Class C.
- Account for natural fish-size variation.
- Do not use another overlapping fish's pixels.
- Use validated Body measurements where possible.
- Compare measurements with reviewed reference distributions.

Ensure reliable abnormal-width evidence actually contributes to the final grade.

## 5. Color, Brightness, Oiliness and Discoloration — 10%

Color must contribute only 10% of the total evidence.

Evaluate:

- Unusual brightness.
- Excessively shiny or oily-looking appearance.
- Yellowing and brown discoloration.
- Darkened or abnormal regions.
- Color inconsistencies.
- Relevant HSV and surface appearance features.

**An unusually bright or oily-looking fish may receive supporting Class C evidence when other quality indicators agree.**

Do not assume all bright fish are Class C. Differentiate actual surface oiliness where measurable from lighting reflections, glare, camera exposure, and natural coloration.

Use calibrated reference examples and ensure the measured features contribute meaningful per-class evidence.

## 6. Texture and Surface Condition — 5%

Use available Body-region texture evidence to assess:

- Surface irregularity.
- Roughness and structural deterioration.
- Unusual texture patterns.
- Visible surface defects.

Avoid double-counting the same crack or discoloration defect under multiple feature categories.

Texture receives only 5% of the final score.

## 7. Fix Excessive Ungraded Results

Audit the current grading logic and identify why fish remain Ungraded despite visible anatomical parts.

Correct:

- Incorrect Head/Body association.
- Unnecessarily restrictive confidence gating.
- Crop and coordinate errors.
- False anatomical ambiguity.
- Missing optional Tail penalties.
- Absolute support thresholds that fail to account for missing optional features.
- Features calculated but excluded from the final grading engine.

**The system must require a reliably identified Head and Body, but it should not require every optional feature to be available.**

When required anatomy is established, combine all reliable available evidence to determine the final classification.

Keep Ungraded when Head/Body ownership is genuinely uncertain or the evidence is insufficient for a defensible classification.

Do not force classifications simply to reduce the Ungraded percentage.

## 8. Implement Explainable Feature Fusion

For every inspected fish, calculate and retain:

- Original anatomical quality evidence.
- Head, Body, and Tail contributions.
- Structural crack evidence and its 30% allocation.
- Body-width abnormality evidence and its 15% allocation.
- Color and surface appearance evidence and its 10% allocation.
- Texture evidence and its 5% allocation.
- Actual effective weights when features are unavailable.
- Per-class combined evidence.
- Final predicted grade.
- Applied grade restrictions.
- Reasons for excluded or unreliable features.

Ensure the final grade is calculated using these features, rather than merely displaying them.

A verified major structural crack must restrict Class A eligibility, even if anatomical evidence strongly favors Class A.

## 9. Validate the Grading System

Use expert-reviewed fish examples to test the revised grading behavior.

Verify examples involving:

- Class A appearance with a major crack.
- Class B appearance with moderate structural damage.
- Class C fish with smaller cracks and other deterioration.
- Abnormally wide fish supporting Class C.
- Bright or oily-looking fish with other Class C indicators.
- Overlapping fish that produce misleading measurements.
- Missing Tail with reliable Head and Body.
- Genuine missing or ambiguous Head/Body evidence.

Compare anatomical-only grading against the combined feature-fusion approach.

Measure grading accuracy, confusion matrices, class-specific precision and recall, correct grading coverage, and false anatomical assignments.

Calibrate feature weights and score restrictions using reviewed examples rather than arbitrary thresholds.

If a feature is not yet reliable enough to affect grading, clearly identify its validation blocker. Do not pretend it is active.

## FINAL OBJECTIVE

Create a genuinely multi-feature Tamban Fish Quality Grading System using:

**40% Anatomical Evidence + 30% Structural Cracks + 15% Body Geometry + 10% Color + 5% Texture.**

Head and Body must be detected and correctly associated. Tail remains optional.

Make structural cracks and abnormal Body width meaningful contributors, while allowing available reliable visual evidence to influence the classification.

Reduce unnecessary Ungraded results without sacrificing correctness or inventing missing evidence.

Preserve existing models, inspection history, and all working functionality. Implement the necessary backend improvements directly and report the grading features actually activated, validation results, and remaining limitations.