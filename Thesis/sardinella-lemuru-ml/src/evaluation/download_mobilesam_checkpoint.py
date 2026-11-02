"""Download only the optional official MobileSAM asset; never detector weights."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import urllib.request

from src.inference.mobilesam_backend import OFFICIAL_CHECKPOINT_SHA256, OFFICIAL_CHECKPOINT_URL, ROOT


def main():
    directory = (ROOT / "models/experimental/mobilesam").resolve()
    directory.mkdir(parents=True, exist_ok=True)
    target = (directory / "mobile_sam.pt").resolve()
    assert target.is_relative_to(directory)
    if target.exists():
        data = target.read_bytes()
    else:
        request = urllib.request.Request(OFFICIAL_CHECKPOINT_URL, headers={"User-Agent": "Tamban-MobileSAM-experimental"})
        with urllib.request.urlopen(request, timeout=90) as response:
            data = response.read(64 * 1024 * 1024)
    actual = hashlib.sha256(data).hexdigest()
    if actual != OFFICIAL_CHECKPOINT_SHA256:
        raise RuntimeError("Official MobileSAM checksum mismatch; no checkpoint was written or overwritten.")
    if not target.exists():
        target.write_bytes(data)
    record = {"checkpoint": target.relative_to(ROOT).as_posix(), "source_url": OFFICIAL_CHECKPOINT_URL,
              "provider": "Official Ultralytics MobileSAM asset", "bytes": len(data), "sha256": actual,
              "model": "MobileSAM Tiny-ViT", "precision": "FP32", "ownership_validated": False}
    (directory / "checkpoint.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
