# Tamban Thesis - Step-by-Step Development Prompts

**Version:** October 13, 2026  
**Basis:** `Thesis-main (2).zip`, the October 13 code QA, and the feature-engineering documentation.  
**Purpose:** Independent, copy-and-paste Markdown prompts for a coding assistant. Run **one prompt at a time**, review the actual diff, run tests, and commit/backup before moving to the next.

## How to use

1. Open the **current** thesis repository in a coding-capable assistant (e.g., your local editor or a connected coding agent).
2. Open the numbered `.md` file and paste **that file's contents only** into the assistant. You do not need to paste this entire package.
3. Let the assistant inspect the current code before changing anything. Review the files it changes and verify its test output.
4. Keep each step in a separate Git commit or branch, then proceed to the next file. Skip or postpone gated steps until the stated prerequisites are available.

These are **implementation instructions, not prewritten patches**. The current repository may have changed since the QA; all paths below are starting points to verify, not claims that a function still has the same line number. Large YOLO checkpoints were intentionally omitted from the shared ZIP: do not interpret missing `.pt` weights as model defects, and do not fabricate inference accuracy or test results.

## Recommended order

| Prompt | Scope | Gate / dependency |
|---|---|---|
| 01 | Re-audit active architecture and baseline tests | Start here |
| 02 | Fix evidence-bearing temporal grading and uncertainty recovery | Core safety fix |
| 03 | Fix full-frame parent-to-part association under overlap | Core safety fix |
| 04 | Introduce adviser-recommended Body + (Head OR Tail) rule | Requires documented team approval before activation |
| 05 | Distinguish physical missing anatomy from nondetection | Expert rule confirmation required before auto-reject |
| 06 | Audit existing masked color/texture/morphology features | No grading changes |
| 07 | Report live features as diagnostics without altering verdicts | After 06 |
| 08 | Compare brightness/color/reflectance for B vs C | Expert-labeled validation data required |
| 09 | Evaluate texture and edge features as research baselines | Expert-labeled validation data required |
| 10 | Create expert-approved belly-defect rubric | Annotator consultation/consent |
| 11 | Implement specimen-aware belly-defect annotation data pipeline | After 10 |
| 12 | Prototype belly-hole/tear detection | After enough expert-labeled examples exist |
| 13 | Test optional feature fusion against weighted baseline | After 08/09 and, if used, 12 |
| 14 | End-to-end fish-level evaluation and ablation | Independent fish-level labels and checkpoints |
| 15 | Optional evidence-clip library in sidebar | Approved recording access/consent |
| 16 | Final code QA, docs and release checks | After completed steps |

## Research-policy safeguards

- **Current weighted baseline:** Body 50%, Head 30%, Tail 20%; missing-part contributions are zero, not redistributed. Treat these weights as **provisional expert-informed hypotheses** rather than expert-certified optimal values.
- **Proposed updated grading eligibility:** Body AND (Head OR Tail). The professor suggested this to reduce Ungraded results, but activate it only after the research team agrees on thresholds and how head integrity is checked.
- **Missing head:** Expert reportedly considers a *physically absent* head grounds for Rejected, but reconfirm in writing. Head **not detected** can be caused by occlusion, so it is not proof of physical absence.
- **Missing tail:** Reportedly still eligible for grading; confirm any grade limits with the annotator.
- **Belly holes/tears:** Potential structural defects; acceptable processing openings and accidental damage must be defined by an expert. Do not equate high edge density with a confirmed hole.
- **Features today:** Live HSV-style measurements are mainly diagnostic; masked color/texture/morphology research features do **not** yet adjust the production grade. Do not describe them as active backup graders until validated and wired into inference.
- **Model confidence:** A model confidence score and a weighted support score are **not automatically calibrated probabilities**.
- **Reproducibility:** Preserve existing Model 1 / Model 2 separation and keep a model-free test path. Report missing model assets transparently instead of treating them as source-code errors.

## Deliverable expectation for every prompt

Ask the coding assistant for changed files, the exact rule implemented, a test summary, open risks, and the next prerequisite. A stage is **not complete** if its acceptance criteria remain untested or if its scientific data is missing.
