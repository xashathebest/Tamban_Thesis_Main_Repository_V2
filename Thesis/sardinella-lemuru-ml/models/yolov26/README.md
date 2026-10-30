# YOLOv26 Models

This folder contains the YOLOv26-M checkpoint used as **Model 2** (the
part-quality detector) in the Tamban *Sardinella lemuru* grading system.

## Active checkpoint

| File | SHA-256 (prefix) | Size | Runtime status |
|------|-----------------|------|----------------|
| `model2_tamban_yolo26m_partdet_r03_devbest.pt` | `f74cd336b6ba` | 42 MB | Active default Model 2 (`yolo26m_partdet`) |

The active selection, full checksum, input size (768), and class contract are
defined in [`../MODEL_REGISTRY.json`](../MODEL_REGISTRY.json). The checkpoint is
active in the Analyze Image and live-inspection flows, but still requires
independent fish-level validation before any biological performance claim.

## Classes (12-class part schema)

| ID | Name |
|----|------|
| 0 | Grade_A_Body |
| 1 | Grade_A_Head |
| 2 | Grade_A_Tail |
| 3 | Grade_B_Body |
| 4 | Grade_B_Head |
| 5 | Grade_B_Tail |
| 6 | Grade_C_Body |
| 7 | Grade_C_Head |
| 8 | Grade_C_Tail |
| 9 | Rejected_Body |
| 10 | Rejected_Head |
| 11 | Rejected_Tail |

## Run the active runtime

From the repository root, the registry selects this checkpoint automatically:

```powershell
.\.venv\Scripts\python.exe -m src.api
```

Set `FISH_QUALITY_MODEL_PATH` only when intentionally testing a different,
compatible Model 2 checkpoint.

## Part-detection compatibility check

The active checkpoint can be evaluated against a COCO export with the
production Model 2 adapter, exact class mapping, 768-pixel input, and the
deployment confidence of 0.25:

```powershell
.\.venv\Scripts\python.exe -m src.evaluation.evaluate_active_model2_parts `
  --dataset-root "Dried Fish Quality Grading.v7i.coco-segmentation" `
  --splits train valid test `
  --device cpu `
  --operating-confidence 0.25 `
  --training-manifest "..\..\Other Files\data\training_manifest.csv"
```

The report is written to
`results/evaluation/active_model2_coco_part_compatibility.json`. It measures
only the 12 independent part boxes; it does not measure fish ownership, final
fish grades, or fish-level accuracy. The supplied v7 validation/test exports
overlap a historical training manifest, so their values are explicitly labeled
development/compatibility evidence rather than independent accuracy.
