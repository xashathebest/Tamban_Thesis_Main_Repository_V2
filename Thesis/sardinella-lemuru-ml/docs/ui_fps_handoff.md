# Inspection and performance handoff

## Operator quick-start

1. Start the local API as described in `README.md`, open the dashboard and confirm the detector, quality model, camera and tracker status. A tracker fallback warning means overlap behavior may differ; do not assume it is equivalent to ByteTrack.
2. Open Live Inspection and select Start. Monitor the feed, counted fish, grade and evidence; the optional raw preview is unannotated and does not represent faster AI inference.
3. Use History for session records and Review for fish needing a manual decision. Manual decisions are stored separately from the original AI verdict. Use Export for the selected records and fields.
4. Stop inspection when finished. Use camera settings/calibration deliberately, follow the profile confirmation and lock workflow, and verify physical readbacks on the actual device. Model and research settings should be changed only when allowed by the application.

## Interpreting measurements and results

- Capture FPS is a rate of frames acquired by the camera; a camera's reported FPS setting is not the same measurement. AI processing FPS describes processed/annotated publications; browser-visible preview FPS and capture-to-display age are not currently measured.
- Model 2 confidence is model evidence for a predicted part class. Weighted grade support combines eligible part evidence under the configured policy; neither is a validated percentage of fish quality.
- Ungraded means the system lacks enough eligible evidence for an automatic final grade. Rejected means trained Rejected-class evidence contributed under the grading rules; missing evidence alone does not establish a structural defect.
- The default Model 2 mode is `full_frame` at interval 3 unless configuration or startup environment overrides it. Session metadata records active settings and checkpoint identity. Tail-optional grading, including required Body and Head evidence, is documented in `README.md` and `configs/grading_engine.yaml`. Structural crack/belly-hole research is not a validated deployed override.

## Developer checks and rollback

Use `docs/runtime_baseline.md` for local target-machine collection and telemetry-overhead checks, `docs/model2_schedule_benchmark.md` for the comparison protocol and its limitations, and `results/performance/performance_report.md` for the current unmeasured comparison. `FISH_RUNTIME_TELEMETRY=0` disables the bounded sample recorder at startup; restore `1` for normal recording. `FISH_RAW_PREVIEW_ENABLED=1` offers the optional raw feed; restore `0` and restart to disable it. Both are startup settings, and the raw feed remains separate from grading. Refer to the README configuration table and actual runtime session metadata for other overrides.

Run `python -B tests/run_model_free_isolated.py` for the checkpoint-free regression and `node --check frontend/app.js` for JavaScript syntax. The optional actual-checkpoint tests and responsive browser tests are described in the optimization tracker. Keep measurement conditions, exact checkpoint hashes, environment and independent truth fixed when comparing candidate performance; do not select model sizes, gating or presets without a defensible accuracy and counting study.

Known blockers: independent labeled fish footage, representative target-camera performance and soak tests, CUDA/precision comparison, dependency-version reconciliation, accessibility field testing, and actual operator/defense-machine rehearsal. The prior release decision remains **NOT READY**; see `qa/final/FINAL_QA_REPORT.md` and `TAMBAN_UI_FPS_OPTIMIZATION_PROGRESS.md`.
