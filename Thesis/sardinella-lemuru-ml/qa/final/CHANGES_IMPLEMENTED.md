# Changes implemented in the final-polish work

- Earlier phases: preserved lifecycle, model selection, tracking and grading behavior; strengthened synthetic tests and neutralized spreadsheet formula interpretation in CSV/XLSX exports (`src/api/export.py`).
- Phase 12: added default-off `FISH_RAW_PREVIEW_ENABLED` raw preview, a bounded subscriber-aware encoder and separate authorized endpoint; processed feed remains default. UI distinguishes processing rate from unmeasured browser preview/latency.
- Phase 13: one visible Settings and Export entry per viewport; Analytics identifies its Live disclosure and feed display controls are consolidated visually.
- Phase 14: show actual backend error instead of attributing every failure to the camera, and disable repeated Stop while stopping.
- Phase 15: validate export field selection/reversed date ranges and show errors inside the dialog, preserving open-ended ranges.
- Phase 17: added an optional read-only process/status soak monitor and short worker cleanup tests.

Scientific weights and model thresholds were not changed during these QA phases. New tests and phase evidence are in `qa/final/` and the progress tracker. Roll back raw preview by unsetting `FISH_RAW_PREVIEW_ENABLED` and restarting; other changes require a reviewed source revert against the actual dirty working tree.
