"""Download the AI models CAMS needs: face detection, face recognition, person and object detection, body pose
and number plates (about 59 MB, once).

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
    # number plates: reader (CCT-XS v1, fast-plate-ocr project, MIT licence)
    "plate_reader_cct_xs_v1.onnx": (
        "https://github.com/ankandrew/cnn-ocr-lp/releases/download/arg-plates/cct_xs_v1_global.onnx",
        "c1ae2ae031b10f8ab7ed6e3cdaf8d9c753477e299dbad3579c8f705a7d882134",
    ),
}

# number plates: finder (YOLOv9-tiny, open-image-models project, MIT licence). Its built-in
# duplicate-removal step fails in OpenCV, so it is cut off here and CAMS does that step itself.
PLATE_FINDER = (
    "https://github.com/ankandrew/open-image-models/releases/download/assets/yolo-v9-t-384-license-plates-end2end.onnx",
    "888397b96d761c89db40bc9c305838e8652660f5e282c2cadebbe8d2951a77a8",
    "plate_detector_yolov9t_384.onnx",
    "/end2end/Transpose_output_0",
)


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
    url, digest, name, cut_at = PLATE_FINDER
    dest = target / name
    if dest.exists():
        print(f"ok       {name}")
    else:
        print(f"download {name} ...", flush=True)
        raw = target / "plate_finder_end2end.part"
        urllib.request.urlretrieve(url, raw)
        if sha256(raw) != digest:
            raw.unlink(missing_ok=True)
            print(f"ERROR: checksum mismatch for {name}", file=sys.stderr)
            return 1
        try:
            import onnx.utils
        except ImportError:
            raw.unlink(missing_ok=True)
            print("ERROR: the onnx package is needed once to prepare the plate finder: pip install onnx", file=sys.stderr)
            return 1
        onnx.utils.extract_model(str(raw), str(dest), ["images"], [cut_at])
        raw.unlink(missing_ok=True)
        print(f"ok       {name}")
    print(f"Models ready in {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
