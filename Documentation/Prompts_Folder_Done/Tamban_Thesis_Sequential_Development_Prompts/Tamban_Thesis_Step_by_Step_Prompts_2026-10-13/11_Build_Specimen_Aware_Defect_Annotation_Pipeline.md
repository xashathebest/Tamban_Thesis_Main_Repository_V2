# PROMPT 11 - Build a Reproducible Belly-Defect Annotation Data Pipeline

Implement **data ingestion, QA and export** for expert-reviewed belly-hole/tear annotations in our Tamban thesis project. This step follows the belly-defect rubric. Do not train a new neural model and do not invent labels.

## Tasks

1. Inspect the existing dataset/manifests/COCO export structure, image IDs, parent fish IDs, and annotation code; reuse compatible formats.
2. Add a small, documented annotation schema for `fish_id`, `specimen_id`, `capture_group_id`, image/frame source, `belly_defect_type`, presence, severity, visibility, polygon or box, reviewer, rubric version, and expert-grade effect.
3. Implement validators for malformed polygons/boxes, duplicate or orphan image references, no physical-fish association, conflicting review labels, missing provenance, and label/version drift. Preserve an explicit `unknown` value.
4. Add deterministic fish/specimen-aware split generation, ensuring no fish or capture group crosses train/validation/test. Flag insufficient examples of normal openings or severe defects.
5. Add optional data preview/export with bounding overlays for human inspection (only if images are available). Keep raw consented source records separate from public training exports.
6. Add synthetic schema/validator tests and a clear sample manifest with **dummy** records only, labeled as examples.

## Acceptance criteria

- The pipeline rejects leakage-prone or incorrectly linked records.
- No training begins or metrics are claimed if real expert-confirmed annotations are absent.
- A user can import, validate and export a new annotated batch reproducibly.

## Report back

Files changed, command examples, test results, actual available label counts, and remaining dataset gaps.
