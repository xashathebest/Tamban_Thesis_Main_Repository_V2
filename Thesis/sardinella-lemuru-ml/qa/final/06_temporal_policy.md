# 06 — Temporal evidence and Tail-optional policy

This prompt predates the user's explicit subsequent instruction to implement `tail_optional_v1`. Accordingly this phase verifies the currently configured version 4.0 rather than restoring the historical fixed-weight default. Legacy `standard` remains available for comparisons. No grade thresholds, class definitions or trained weights were changed in this phase.

Live grading requires two distinct evidence-bearing frames by default. Each accepted frame must satisfy Body, Head, region-count and coverage requirements; an empty or low-confidence frame does not create evidence. The bounded candidate window advances during empty observations. Ambiguous association, uncertain parents or Model 2 unavailability clear active evidence; fresh clear frames can recover. Brief tracker gaps retain existing evidence until track timeout; expired/reused IDs start fresh. Still-image grading does not require two live frames. Ungraded is distinct from a trained Rejected-class prediction and from a lost track.

| Synthetic condition | Verified behavior |
|---|---|
| Body + Head, no Tail | Eligible subject to other gates; weights .625/.375/0. |
| Body alone; Body + Tail; Head + Tail; no parts | Ungraded with `UG_MISSING_PART_EVIDENCE`. |
| Zero confidence, even with part threshold zero | Does not count as an observed region. |
| Reliable Rejected Tail | Tail is evaluated and contributes Rejected evidence at its original weight. |
| One usable frame followed by an empty frame | Empty frame does not meet temporal evidence. |
| Ambiguous then clean / clean then ambiguous | Evidence is cleared on uncertainty and requires new clean evidence. |
| Short dropout / expired reused ID | Evidence is retained during the configured track timeout; expired identity starts fresh. |
| Equal grade support | The default zero margin uses deterministic class ordering; an explicitly positive minimum margin produces `UG_LOW_MARGIN`. This is existing policy, not proof of a scientifically valid tie-break. |

`tests/test_tail_optional_policy.py` gained explicit mandatory-region/zero-confidence and tie-margin cases; `tests/test_grading_engine.py` and `tests/test_runtime_diagnostics.py` cover temporal and dropout cases. Corrected command: `python -B -m pytest -q -p no:cacheprovider tests/test_grading_engine.py tests/test_tail_optional_policy.py tests/test_runtime_diagnostics.py --tb=short`: **58 passed, 53 subtests passed** (`06_temporal.log`). An initial command referenced a nonexistent `tests/test_grading_policy.py` and exited 4 without running tests; it was corrected before the reported run. No real fish or independent expert study was performed.
