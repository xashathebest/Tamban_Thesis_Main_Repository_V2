# PROMPT 15 (OPTIONAL) - Add a Read-Only Expert Validation Sidebar

Build a small **Expert Validation** section in our existing Tamban grading application's sidebar, as a research-documentation feature. This is **not** part of AI inference, and it must not change grading results. We have consent paperwork for consultations, but you must **verify the allowed recording/display scope** before exposing anything beyond authorized users.

## Tasks

1. Inspect the current frontend and API conventions. Add a lightweight sidebar route/item and a read-only list/detail view using the existing styling and UI framework.
2. Use a structured manifest of *real* clips with fields: rule ID, title, research question, consultation date, original filename, original start/end time, clipped filename/length, exact quote/transcript or paraphrase label, validation status (`proposed`, `expert-confirmed`, `experimentally-validated`), and reviewer.
3. Include categories for body emphasis/50-30-20 hypothesis, physical missing head, missing tail, belly defects, and A/B/C distinctions. Use **empty-state examples only**, not fabricated videos, quotes or timestamps.
4. Restrict video content and its metadata to authorized research roles. Do not copy original recordings into publicly served frontend assets, commit private files, or generate guessed public URLs. Use secure storage or a local/authorized media endpoint as suitable to the actual deployment.
5. Display a disclaimer: the expert clip documents what the expert said, **not** proof that a mathematical weighting rule is optimal. Differentiate exact expert claims from researcher interpretation.
6. Test missing files, unauthorized access, bad manifest entries, link to original time span, and responsive navigation.

## Acceptance criteria

- A panelist can locate a topic-specific clip and its original recording timestamp quickly **with authorized access**.
- The grading endpoint, model pipeline and inference outputs are unchanged.
- No personal recording becomes public by default.

## Report back

Files changed, access model, manifest schema, screenshots/test results where available, and outstanding privacy/consent checks.
