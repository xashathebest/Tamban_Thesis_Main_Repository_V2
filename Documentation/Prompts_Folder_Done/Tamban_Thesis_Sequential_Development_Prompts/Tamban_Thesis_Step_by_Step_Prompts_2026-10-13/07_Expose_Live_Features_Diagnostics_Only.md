# PROMPT 07 - Add Read-Only Live Feature Diagnostics With Provenance

Make existing Tamban image measurements visible in the application's diagnostic output **without changing A/B/C/Rejected/Ungraded decisions**. Current production grading uses Model 2 weighted body-part confidence; the richer masked features are research-only. Inspect the present API contracts and frontend before editing.

## Tasks

1. Find current live HSV/ROI statistics in `src/inference/grading_engine.py` and existing API and frontend result schemas.
2. Extend structured diagnostic output to include the available brightness / saturation / color proxies and, only if actually computable, additional reflectance/texture measurements. Reuse established extractors instead of duplicating formulas.
3. Attach `measurement_source` (e.g., masked fish pixels, part crop, or rectangular ROI), `fish_id`, frame/image ID, algorithm version, and missing-value reason. Never calculate a fake measurement when the required mask is absent.
4. Present the values under a clearly labeled **Supporting Image Measurements** section. Indicate `not used for final grade` in UI/export until a validated fusion rule exists.
5. Add API serialization, invalid-input, and graded-result regression tests. Respect performance limits by profiling optional texture computations and supporting an off switch.

## Acceptance criteria

- For identical Model 2 evidence, turning diagnostics on or off produces **exactly the same verdict and weighted score**.
- Per-fish provenance is preserved in crowded scenes; no cross-fish measurements.
- No claim of physical cracks, torn belly, or expert-approved feature thresholds is introduced.

## Report back

Files changed, sample sanitized response payload, latency measurements if runnable, and tests/results.
