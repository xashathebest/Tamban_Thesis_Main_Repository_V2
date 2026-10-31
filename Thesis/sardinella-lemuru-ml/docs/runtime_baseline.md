# Collecting a clean live runtime baseline

This procedure observes a running inspection using local GET requests. It does
not start or stop the inspection, open another camera, change model settings,
or enable debug capture. Use the inspection machine, the actual camera and
installed checkpoints. Leave **Enable bounded debug capture** off: it changes
Model 2 candidate collection and can save research artifacts.

1. In PowerShell, change to the repository project directory and start the API
   with the project launcher. It uses the project-local Python environment;
   missing `lap` continues with IoU tracking and is recorded in backend logs:

   ```powershell
   Set-Location 'C:\Users\User\Downloads\Tamban_Thesis_Main_Repository\Thesis\sardinella-lemuru-ml'
   .\run_dashboard.ps1
   ```

   Open the dashboard, check both models are ready, and start an inspection
   using the normal production configuration.
2. In a second PowerShell window, use the same directory and project Python.
   Prepare the empty conveyor and run:

   ```powershell
   Set-Location 'C:\Users\User\Downloads\Tamban_Thesis_Main_Repository\Thesis\sardinella-lemuru-ml'
   $thesisPython = '.\.venv\Scripts\python.exe'
   & $thesisPython -m src.evaluation.runtime_benchmark --scenario empty --warmup 15 --duration 90
   ```

3. Prepare one fish, then multiple overlapping fish. Run each command after the
   scene is in place, keeping the configuration and environment constant:

   ```powershell
   & $thesisPython -m src.evaluation.runtime_benchmark --scenario one_fish --warmup 15 --duration 90
   & $thesisPython -m src.evaluation.runtime_benchmark --scenario overlap --warmup 15 --duration 90
   ```

Each command creates uniquely named JSON and Markdown reports under
`results/performance`. The scenario is an operator declaration; it is not
verified by the collector. A stopped camera, unavailable model, active debug
capture, changed session/configuration, or absent frame activity yields
`NOT_MEASURED`. Confirm the output status and record lighting, fish arrangement,
camera identity and other conditions externally. Keep the files for comparison.
The collector is bounded to at most 120 seconds and an interval of at least
0.25 seconds. It records local Python/PyTorch hardware information separately
from the API's actual model-device assignments. Run it on the same machine as
the API; a different collector environment may have a different PyTorch build.

The camera FPS readback is a device-reported setting; measured capture FPS is
calculated from captured-frame counter changes. `processed_frame_per_second` is
the published annotated-frame rate. Queue `processed_frames_per_second` counts
frames taken from the queue and can include failed processing; the queue's
`dropped_frames_delta` counts stale frames replaced before processing. None of
these is browser-visible preview FPS or fish per minute.

Timing p50/p95 values are the server's **final rolling windows**, not percentiles
over the entire collection. Check their sample counts and the sampled windows in
the JSON. Windows may include warmup or a previous scene; stages can overlap,
and missing stage data means not measured. Host timing on CUDA may omit
asynchronous work. Do not add stage times or assert a bottleneck from a single
largest number; compare repeat runs and validate the suspected bottleneck with
appropriate profiling. No accuracy, fish counting, ownership, or grading claim
follows from FPS alone. Record labelled fish-level outcomes independently.

## Checking runtime-recording overhead

The `FISH_RUNTIME_TELEMETRY` startup variable controls only the bounded sample
recorder. It defaults to `1`. Setting it to `0` disables recording, not the
monotonic clock reads or queue accounting; it does not disable inference,
debug capture, or the camera. Restart the API for each setting. With the API
stopped, set `$env:FISH_RUNTIME_TELEMETRY = '1'` for the first run, then `0`
for the second. Start the API using the same Python and configuration, start the
inspection, leave debug capture off, use the same scene and wait at least 15
seconds. Verify `runtime_diagnostics.performance.recording_enabled` in
`/api/status` matches the intended setting.

In a separate PowerShell window, sample the dashboard's smoothed published FPS
once per second for 90 seconds, saving a distinct CSV for each run:

```powershell
$samples = @(1..90 | ForEach-Object {
    $status = Invoke-RestMethod http://127.0.0.1:8000/api/status
    if ($status.inspection_status -ne 'running' -or $status.camera_status -ne 'connected' -or
        $status.runtime_diagnostics.enabled -or $status.runtime_diagnostics.paused -or
        $status.model_info.detector.status -ne 'ready' -or $status.model_info.quality.status -ne 'ready') {
        throw 'Inspection, model, camera or debug state invalid; discard this run.'
    }
    [pscustomobject]@{ time = (Get-Date).ToString('o'); fps = $status.fps;
        recording = $status.runtime_diagnostics.performance.recording_enabled;
        session = $status.durable_session.session_id; model2 = $status.active_model2_id }
    Start-Sleep -Seconds 1
})
$samples | Export-Csv -NoTypeInformation -Path 'results/performance/recording_on.csv'
$samples.fps | Measure-Object -Average -Minimum -Maximum
```

Use `recording_off.csv` for the second run. Check each CSV for a constant
recording setting, session and model; preserve both runs' camera settings and
checkpoint hashes. Repeat or alternate runs to account for noise. This FPS is
the app's smoothed annotated publication rate sampled by status polling; it is
not browser paint FPS, a frame-by-frame percentile, or a substitute for the
clean counter-delta baseline. API polling adds overhead equally to both runs.
Re-enable recording with `$env:FISH_RUNTIME_TELEMETRY = '1'` before restarting
normally. CUDA stage timings need a separate synchronized profiling experiment;
these host measurements alone do not validate completed GPU latency.
