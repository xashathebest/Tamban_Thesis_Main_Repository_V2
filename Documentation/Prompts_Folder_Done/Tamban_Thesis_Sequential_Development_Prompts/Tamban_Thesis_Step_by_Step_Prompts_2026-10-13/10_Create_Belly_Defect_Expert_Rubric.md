# PROMPT 10 - Draft Expert Annotation Rubric for Belly Holes and Tears

Create a **research annotation rubric**, not an unverified AI crack detector, for belly-region openings on dried Tamban fish. A sample fish image shows an apparent belly hole/tear, but the actual cause and quality impact have **not** been independently confirmed. Normal processing cavities could resemble damage.

## Tasks

1. Draft an expert-review rubric defining `belly_defect_present` = Yes/No/Uncertain; `belly_defect_type` = hole/tear/exposed tissue/acceptable processed opening/other/uncertain; `belly_defect_severity` = none/minor/moderate/severe/uncertain, plus `visibility_state`.
2. Include body/fish ID, specimen ID, polygon or box coordinates, image/frame reference, annotator ID, consultation reference, date, and expert-reported grading consequence (`no effect`, `downgrade`, `reject`, `unassessable`, `pending`).
3. Include separate questions for physically missing head/tail, occlusion, accidental tearing vs normal preparation, and whether damage limits Class A/B/C or triggers Rejected.
4. Produce `docs/belly_defect_annotation_rubric.md`, a short expert-consultation checklist, and a small **blank** annotation template (CSV or JSON schema) with descriptive examples only; do not invent expert answers.
5. Design a second-review/adjudication protocol for borderline or uncertain cases and a versioned rubric ID.

## Acceptance criteria

- Structural defect claims are marked `PENDING EXPERT VERIFICATION` until signed/recorded confirmation exists.
- No fabricated defect label, grade, threshold, or consultation timestamp.
- Normal processing openings are a separate option, not automatically defects.

## Report back

List generated documents/schema and the exact questions we must ask the expert before training an automatic detector.
