# Runtime HTTP, viewer, export and accuracy validation

This validation uses the current unchanged CPU Model 1, Model 2 and MobileSAM checkpoints through the actual `/api/analyze-image` endpoint, then real Chrome 156. It runs an isolated temporary server/database on an ephemeral port. The existing port-8000 service and training processes are not restarted or reconfigured. All model operations stay on CPU and CUDA remains uninitialized.

## Actual source and measured behavior

Source: `Dried Fish Quality Grading.v7i.coco-segmentation/test/WIN_20260823_21_45_11_Pro_jpg.rf.01a0867ea638f10c1ffa3acd30d37830.jpg`, native 640 by 640, SHA-256 `a9c8cf263bcc09ea65c54141be6f23223e4fa34e5e639231a6f48596c2e0e51b`.

The single actual HTTP analysis produces nine Model 1 parents, 17 raw Model 2 part candidates, nine MobileSAM candidate masks, and eight masks requiring review. Final grades are one Class C and eight Ungraded. This is 11.1% automatic grading coverage among detected parents, not measured accuracy.

Instrumentation confirms exactly one Model 1 call, one Model 2 call, one shared SAM image embedding, nine mask prompts, and zero GrabCut executions. Boxes/Masks switches, highlighting, opacity, zoom, debug overlays, delayed image preparation, error handling, legacy mask reuse, HTTP normalization, and CSV export do not change those counts or recorded grades. Both checkpoint hashes remain identical.

The decoded-frame-to-results wall time is **5,075.612 ms** on CPU, including shared segmentation **1,961.776 ms** and Model 2 inference **907.608 ms**. This is one observed run, not repeated throughput or deployment-GPU performance. Segmentation includes model loading, one shared embedding and sequential prompts; nested stages must not be added together as independent costs.

All fish retain the same complete native raw-part trace. Accepted visible boxes agree with their recorded parent assignments, with a maximum output-rounding difference of **0.004897 pixels**. Every accepted debug overlay matches that fish's actual assigned parts. The source frame, coordinate space and native dimensions agree across API results, candidate masks and debug overlays.

The actual HTTP/Chrome run passed **46 checks**, four lifecycle checks and mobile layout checks. It exercises both original annotated bounding boxes and shaded real MobileSAM silhouettes in the main viewer, every existing visibility control, per-fish selection, reset, loading/elapsed time and visible errors. The final frontend was subsequently replayed with the exact recorded real image/masks/results in Chrome: **16 checks passed**, zero fetches, no repeated model execution, no grade changes, and a 390-pixel mobile layout without horizontal overflow.

Artifacts under `results/qa/runtime_e2e/ui/` include `actual_e2e.json`, the actual API payloads and instrumentation, original/box/mask comparison images, desktop/mobile screenshots, complete CSV/XLSX files, the browser-downloaded CSV, and `recorded/` screenshots from the final frontend replay.

## Confirmed defects fixed in this validation

### Excel silently truncated real evidence

The actual nine-fish results contain 45 selected full-evidence values longer than Excel's cell limit. Before correction, `openpyxl` silently trimmed those values to 32,767 characters. This affected anatomical association JSON, decision lists, inference provenance, complete analysis and complete fish events. The truncated JSON could no longer be parsed or used to reconstruct rejected anatomy. CSV preserved those records.

The writer now intercepts long values before assigning cells. An oversized JSON cell contains a valid `xlsx_extended_evidence` reference object with the source cell key, appended sheet, chunk count, original character count, SHA-256 and an explicit indication that the cell itself is not the complete value. The original text is stored in order on the append-only **Extended Evidence** sheet, in chunks of at most 30,000 UTF-16 units. Supplementary Unicode characters are kept intact. Oversized plain text receives an explicit human-readable reference. Chunk strings retain the existing spreadsheet formula protection.

Existing column order, small cells and ordinary workbook sheet order remain unchanged. The extra sheet exists only when needed. For reconstruction, select rows matching the reference's `record_key`, order by `Chunk number`, concatenate `Text chunk` exactly, and verify the UTF-8 SHA-256 and original character count before parsing JSON.

Using the same actual results and the captured task-start exporter gives **45 silently truncated cells before and zero after**. Every one of the **347 fields for all nine fish** matches the backend CSV and either matches directly or reconstructs exactly from XLSX. The browser CSV's grades and anatomical/raw diagnostics also match. Source events remain unchanged. The original and repaired exporters are compared on identical actual data; no extra neural inference is needed.

### Video structural overlays used the wrong Fish ID namespace

The existing preview remaps source detector IDs to stable video display IDs. Structural overlay rendering still compared `surface_damage.parent_track_id` against the display ID only. A source Fish 1 displayed as Fish 2 therefore lost its own overlay; a neighboring source Fish 2 could coincidentally pass the numeric check.

Rendering now checks the verified source parent ID when a source namespace is present. It preserves explicitly retained `source_parent_id`, withholds unverified identities, and still requires matching frame, valid native coordinates and the existing structural evidence status. Photo behavior and grading are unchanged. The exact six-case reproduction initially had three failures and three passes; all six now pass, including correct ownership, remapped ownership, neighboring/colliding IDs, wrong frame and missing source proof. Cache versions were refreshed for the frontend.

## Grading accuracy and ground-truth inventory

No independent parent-to-part ownership truth or blind whole-fish expert grades were supplied for these runtime images. Therefore fish-level accuracy, conditional accuracy on automatically graded fish, overall accuracy counting Ungraded as no automatic credit, ownership precision/recall, and false association rate are **unmeasured/null**. Eight Ungraded outcomes do not establish eight incorrect grades, and one automatic grade does not establish one correct grade.

Inspected supporting material:

- `docs/independent_validation_protocol.md` and `docs/validation_preflight/report.md` explicitly record the independent fish-level study as blocked.
- `docs/independent_fish_manifest_template.csv` contains only a header; it supplies no specimen labels.
- `results/stabilization/validation_readiness.json` has pending association, counting/model and end-to-end gates. This runtime engineering validation does not turn them into independent scientific passes.
- The historical dataset-independence audit records training/test lineage overlap and incomplete near-duplicate verification; it is not current certification.
- The COCO files contain individual anatomical part classes/boxes, not independently adjudicated fish parents or final fish grades. The test export lacks Class A part annotations, preventing four-grade fish-level claims even if labels were incorrectly aggregated.
- The expert consultation library is empty/default-disabled and is a research reference library, not per-fish grade ground truth. Folder class names and model predictions cannot fill the missing truth records.

The existing `src/evaluation/fish_level_validation.py` can calculate conditional grading accuracy and overall accuracy including abstention once actual physical-fish truth records are provided. `src/evaluation/end_to_end_validation.py` adds parent/counting and crowded/isolated subgroup metrics when the manifest supplies them. These tools deliberately do not manufacture expert truth from detector output. A reviewed sample needs original frame/fish identity, source/augmentation lineage, blind expert final grade, explicit parent/part ownership, overlap/visibility state and the recorded system result for the same physical fish.

## Files and reproducibility

Production changes in this workstream: `src/api/export.py`, `frontend/app.js`, `frontend/index.html`. No model, threshold, grading weight, annotation, calibration or training file is changed.

New tests/tools: `tests/test_runtime_e2e_export_roundtrip.py`, `tests/test_runtime_e2e_video_structure_ui.py`, `tests/runtime_e2e_api_browser_smoke.py`, `tests/runtime_e2e_recorded_ui_smoke.py`, and this report. The focused export/UI suites passed **57 tests** in 3.71 seconds; the broader export compatibility selection independently passed 57 tests including existing historical/session export cases. JavaScript syntax passed.

Run `python -B tests/runtime_e2e_api_browser_smoke.py` explicitly for a new real-model CPU HTTP/Chrome pass. Run `python -B tests/runtime_e2e_recorded_ui_smoke.py` to reuse its saved actual payload and source preview without further inference. Run the two `test_runtime_e2e_*` modules with pytest for deterministic export and video-identity regressions. The existing Chrome smoke environment supports `TAMBAN_CHROME_NO_SANDBOX=1` where the local sandbox prevents Chrome startup; this affects only the isolated headless test process.
