# Model 2 schedule comparison

`src/evaluation/model2_schedule_benchmark.py` replays each supplied video through the existing whole-fish processing path for full-frame and crop inference at intervals 1, 2, 3 and 4. It preserves the default grading configuration and count-line behavior. It captures invocation counts, summed measured Model 2 and association times, finalized quality counts, count errors when independent truth is provided, and per-frame parent boxes and scheduled part evidence. Input and checkpoint hashes, image sizes, device, grading and tracking settings are recorded. It creates a new output directory and does not replace existing reports.

Prepare **unannotated**, fixed-resolution clips of the same physical camera setup, covering empty, one, three, and six or more fish, including reviewed difficult overlaps. Obtain independent expert fish counts, individual fish and part ownership, and grade/coverage truth before looking at the model results. Store that truth separately, with its reviewer and annotation provenance. Select and lock clips and configurations before running comparisons; match the same frames and physical fish across all conditions. A manifest example, with paths relative to the manifest:

```json
{
  "resolution": [640, 480],
  "clips": [
    {
      "id": "overlap-01",
      "path": "clips/overlap-01.mp4",
      "expert_crossings": 3,
      "expert_reviewer": "reviewer identifier",
      "truth_reference": "independent annotation reference",
      "system_prediction_visible": false,
      "scenario": "3 fish with overlap"
    }
  ]
}
```

From the project directory, run:

```powershell
python -m src.evaluation.model2_schedule_benchmark --manifest path/to/manifest.json --model1 models/fish_detector/weights/model1_fish_parent_detector.pt --model2 models/yolov26/model2_tamban_yolo26m_partdet_r03_devbest.pt --device cpu --output results/performance/model2_study_01
```

Use the exact checkpoint paths and device selected for the study; all combinations use the same files. For smoke testing only, `--max-frames 1 --modes full_frame crop --intervals 3` limits the run; this disables count-error comparison because the truth describes the complete clip. A run against one frame of an existing annotated video confirmed both checkpoints load and both modes execute on CPU; no fish was detected and no Model 2 inference occurred. It is **not** an A/B speed, accuracy, or ownership measurement. The original smoke report's absent timing values were normalized to null after the tool was updated to distinguish missing measurements from measured zero.

The JSONL trace contains each frame's detected parent boxes and scheduled per-track observations; crop part boxes are crop-local, with `crop_bounds` giving the frame-coordinate origin. Full-frame observations include conservative assignment summaries. When several scheduled fish share one frame, the same full-frame association may appear in multiple fish observations: deduplicate by frame and part before counting ambiguous or unassigned parts. Cropped evidence lacks an independent ownership decision and needs expert matching to the source fish. Match independent part labels and parent identities to the traces, then use `python -m src.evaluation.validation_study association --records <reviewed-links.json> --output <association-report.json>` for wrong, ambiguous and unassigned association counts. Independently compare per-fish final quality and coverage, count errors, and missed fish for each condition. Do not substitute model-derived labels for expert truth.

This replay is an exploratory comparison, not a completed acceptance study. It writes trace data during the run, does not synchronize asynchronous CUDA timing, uses live tracker wall-clock time while replaying, and runs each condition in fixed order without a separate warm-up. Those factors can bias timing and tracking comparisons. Repeat and counterbalance complete runs on the target hardware, independently verify decode completeness and tracker behavior, and collect real-camera measurements before selecting a setting. Fixed-order cold-start data, one frame, annotated input, or mock outputs cannot justify a recommendation. The `full_frame` mode with interval 3 remains the production default; no adaptive scheduler has been enabled.

Revert the benchmark by removing this evaluation script, its tests and its generated comparison artifacts. No production inference setting is changed by this tool.
