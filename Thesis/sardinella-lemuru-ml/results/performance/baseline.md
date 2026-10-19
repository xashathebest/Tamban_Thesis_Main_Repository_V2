# Live baseline status

**Not measured.** On 2026-10-18 the local API on `127.0.0.1:8000` refused the
collector connection. No running inspection, live camera settings, capture FPS,
processed FPS, or stage bottleneck could be verified. The empty, one-fish and
overlapping-fish scenarios all remain unmeasured. A reported approximately
5 FPS therefore cannot yet be classified as capture or processed FPS.

The collector's own Python reported a CPU-only PyTorch build; this does not
establish the device configuration of the API or the inspection machine.
The configured Model 1 and selected Model 2 checkpoint files exist locally, but
their presence does not prove that the models loaded or ran successfully.
See the generated `baseline_20261018_005322_empty.json` for the failed
collection and `../../docs/runtime_baseline.md` for the live procedure.

No baseline/optimized comparison or fish-level accuracy conclusion is possible
until the real scenarios are measured with the production camera and models.
