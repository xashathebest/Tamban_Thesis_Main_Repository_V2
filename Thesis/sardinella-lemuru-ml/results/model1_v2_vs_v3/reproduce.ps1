# Run from Thesis/sardinella-lemuru-ml with an interpreter containing the project's ML dependencies.
# The original development and legacy datasets are required for a fresh evaluation.
param([string]$Python = '.venv/Scripts/python.exe')
& $Python -X utf8 -u -m src.evaluation.compare_model1_versions `
  --baseline 'models/fish_detector/weights/model1_v2_yolo26s_best.pt' `
  --candidate 'models/fish_detector/candidates/v3/model1_v3_yolo26s_best.pt' `
  --data 'C:/Users/User/Downloads/Tamban_Thesis_Main_Repository/Thesis/sardinella-lemuru-ml/notebooks/Tamban_Model1_Retrain/model1_v3/deduplicated/dataset/data.yaml' `
  --legacy-data 'C:/Users/User/Downloads/Tamban_Thesis_Main_Repository/Thesis/sardinella-lemuru-ml/notebooks/tamban_model1_1900_work/yolo_cleaned/data.yaml' `
  --training-csv 'results/model1_v2_vs_v3/provenance/results.csv' `
  --output 'results/model1_v2_vs_v3' --device 0
