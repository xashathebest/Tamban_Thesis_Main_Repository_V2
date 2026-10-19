"""Run tests in a temporary source copy that contains no model checkpoints."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--focus", help="Optional unittest module, e.g. test_multi_model_selection")
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="tamban-model-free-") as temporary:
        target = Path(temporary) / "project"
        target.mkdir()
        def ignore(_directory, names):
            return {name for name in names if name in {"__pycache__", ".pytest_cache", ".git"}
                    or Path(name).suffix.lower() in {".pt", ".pth", ".onnx", ".joblib", ".pyc", ".sqlite3"}}
        for directory in ("src", "tests", "configs", "models", "frontend", "docs", "camera"):
            path = source / directory
            if path.is_dir():
                shutil.copytree(path, target / directory, ignore=ignore)
        forbidden = [path for path in target.rglob("*") if path.is_file() and path.suffix.lower() in {".pt", ".pth", ".onnx", ".joblib"}]
        if forbidden:
            raise RuntimeError(f"Checkpoint unexpectedly copied: {forbidden[0]}")
        env = {key: value for key, value in os.environ.items() if not key.startswith(("FISH_", "LEMURU_", "EXPERT_LIBRARY_"))}
        env.update(PYTHONDONTWRITEBYTECODE="1", YOLO_CONFIG_DIR=str(Path(temporary) / "ultralytics"))
        for key in ("RUN_REAL_MODEL_TESTS", "RUN_CHECKPOINT_SMOKE"):
            env.pop(key, None)
        command = [sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests", "--tb=short"]
        if args.focus:
            command[command.index("tests")] = f"tests/{args.focus}.py"
        print("Running in a temporary source copy with no checkpoints:", " ".join(command), flush=True)
        return subprocess.run(command, cwd=target, env=env, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
