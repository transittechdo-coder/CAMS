"""Download the AI models CAMS needs: face detection, face recognition, person and object detection, and body pose (about 49 MB, once).

    python scripts/download_models.py

After this, CAMS works fully offline. The Windows installer already
contains the models, so end users never need to run this.
"""

from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

BASE = "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models"
MODELS = {
    "face_detection_yunet_2023mar.onnx": (
        f"{BASE}/face_detection_yunet/face_detection_yunet_2023mar.onnx",
        "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    ),
    "face_recognition_sface_2021dec.onnx": (
        f"{BASE}/face_recognition_sface/face_recognition_sface_2021dec.onnx",
        "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
    ),
    # body pose for the activity AI (MediaPipe Pose, 33 body points)
    "pose_estimation_mediapipe_2023mar.onnx": (
        f"{BASE}/pose_estimation_mediapipe/pose_estimation_mediapipe_2023mar.onnx",
        "9d89c599319a18fb7d2e28451a883476164543182bafca5f09eb2cf767ed2f3f",
    ),
    # person detection for suspicious-activity rules (NanoDet-Plus, COCO)
    "object_detection_nanodet_2022nov.onnx": (
        f"{BASE}/object_detection_nanodet/object_detection_nanodet_2022nov.onnx",
        "4b82da9944b88577175ee23a459dce2e26e6e4be573def65b1055dc2d9720186",
    ),
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    target = Path(__file__).resolve().parent.parent / "models"
    target.mkdir(exist_ok=True)
    for name, (url, digest) in MODELS.items():
        dest = target / name
        if dest.exists() and sha256(dest) == digest:
            print(f"ok       {name}")
            continue
        print(f"download {name} ...", flush=True)
        tmp = dest.with_suffix(".part")
        urllib.request.urlretrieve(url, tmp)
        got = sha256(tmp)
        if got != digest:
            tmp.unlink(missing_ok=True)
            print(f"ERROR: checksum mismatch for {name} ({got})", file=sys.stderr)
            return 1
        tmp.replace(dest)
        print(f"ok       {name}")
    print(f"Models ready in {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
