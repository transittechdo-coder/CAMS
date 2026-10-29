"""Colour for black-and-white (infrared night) CCTV video."""

import time

import cv2
import numpy as np
import pytest

onnx = pytest.importorskip("onnx")
from onnx import TensorProto, helper, numpy_helper  # noqa: E402

from cams import colour  # noqa: E402


def tiny_colour_model(path):
    """A stand-in for colorizer.onnx with the same input and output: L (1x1x256x256) -> ab (1x2x64x64).
    It paints bright parts orange-ish and dark parts blue-ish, which is enough to test the pipeline."""
    w = np.zeros((2, 1, 4, 4), np.float32)
    w[0, 0] = 0.6 / 16      # a grows with brightness
    w[1, 0] = 1.2 / 16      # b grows with brightness
    b = np.array([-20.0, -45.0], np.float32)
    node = helper.make_node("Conv", ["input", "w", "b"], ["output"], kernel_shape=[4, 4], strides=[4, 4])
    graph = helper.make_graph([node], "tiny_colour",
                              [helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 1, 256, 256])],
                              [helper.make_tensor_value_info("output", TensorProto.FLOAT, [1, 2, 64, 64])],
                              [numpy_helper.from_array(w, "w"), numpy_helper.from_array(b, "b")])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 8
    onnx.save(model, str(path))
    return path


def night_frame(w=640, h=360):
    img = np.zeros((h, w), np.uint8)
    cv2.rectangle(img, (0, 0), (w, h // 2), 40, -1)
    cv2.rectangle(img, (0, h // 2), (w, h), 170, -1)
    cv2.circle(img, (w // 2, h // 2), 60, 230, -1)
    return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)


def saturation(img):
    return float(cv2.cvtColor(img, cv2.COLOR_BGR2HSV)[..., 1].mean())


def test_black_and_white_detection():
    assert colour.is_grey(night_frame())
    tinted = night_frame().astype(np.int16)
    tinted[..., 1] += 3                     # infrared cameras often add a faint tint
    assert colour.is_grey(np.clip(tinted, 0, 255).astype(np.uint8))
    day = night_frame().copy()
    day[:, :, 2] = 220                      # red-ish daylight scene
    assert not colour.is_grey(day)


def test_model_check_and_colourise(tmp_path):
    good = tiny_colour_model(tmp_path / "c.onnx")
    assert colour.check_model(good) is None
    junk = tmp_path / "junk.onnx"
    junk.write_bytes(b"not a model" * 200)
    assert "not a colour model" in colour.check_model(junk)
    m = colour.ColourModel(good)
    ab = m.predict_ab(night_frame())
    assert ab.shape == (64, 64, 2)
    out = colour.colourise(night_frame(), ab)
    assert out.shape == (360, 640, 3) and saturation(out) > 25
    # the sharp brightness of the picture is kept
    grey_in = cv2.cvtColor(colour.enhance_light(night_frame()), cv2.COLOR_BGR2GRAY).astype(int)
    grey_out = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY).astype(int)
    assert np.abs(grey_in - grey_out).mean() < 12


def _night_video(path, frames=40):
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (640, 360))
    for i in range(frames):
        f = night_frame()
        cv2.putText(f, str(i), (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        vw.write(f)
    vw.release()


def test_live_colour_for_night_camera(admin, system, tmp_path):
    assert admin.get("/api/colour").json()["installed"] is False
    bad = admin.post("/api/colour/model", files={"file": ("x.onnx", b"nope" * 500, "application/octet-stream")})
    assert bad.status_code == 400
    model = tiny_colour_model(tmp_path / "colorizer.onnx")
    r = admin.post("/api/colour/model", files={"file": ("colorizer.onnx", model.read_bytes(), "application/octet-stream")})
    assert r.status_code == 200 and r.json()["installed"]

    vid = tmp_path / "night.avi"
    _night_video(vid)
    cid = admin.post("/api/cameras", json={"name": "Back gate (night)", "source": str(vid), "colour_mode": "auto"}).json()["id"]
    end = time.time() + 20
    best = 0.0
    while time.time() < end:
        s = admin.get(f"/api/cameras/{cid}/snapshot.jpg")
        if s.status_code == 200:
            img = cv2.imdecode(np.frombuffer(s.content, np.uint8), cv2.IMREAD_COLOR)
            best = max(best, saturation(img))
            if best > 25:
                break
        time.sleep(0.3)
    assert best > 25, "the black-and-white camera is shown in colour"
    assert admin.get("/api/cameras").json()[0]["live"]["colour"] is True
    assert admin.get("/api/colour").json()["last_ms"] > 0

    # turned off: back to black and white
    cam = admin.get("/api/cameras").json()[0]
    cam["colour_mode"] = "off"
    assert admin.put(f"/api/cameras/{cid}", json=cam).status_code == 200
    time.sleep(0.5)
    img = cv2.imdecode(np.frombuffer(admin.get(f"/api/cameras/{cid}/snapshot.jpg").content, np.uint8), cv2.IMREAD_COLOR)
    assert saturation(img) < best / 2
    cam["colour_mode"] = "rainbow"
    assert admin.put(f"/api/cameras/{cid}", json=cam).status_code == 400


def test_auto_leaves_colour_cameras_alone(system):
    system.colour.model = colour.ColourModel(tiny_colour_model(system.paths.data / "t.onnx"))
    system.colour._modes[99] = "auto"
    day = np.zeros((360, 640, 3), np.uint8)
    day[:] = (30, 160, 60)
    out, coloured = system.colour.apply(99, day)
    assert coloured is False and np.array_equal(out, day)


def test_download_with_progress(system, tmp_path, monkeypatch):
    monkeypatch.setattr(colour, "MODEL_MIN_BYTES", 10)
    src = tiny_colour_model(tmp_path / "src.onnx")

    def fake_fetch(url, dest, progress):
        data = src.read_bytes()
        progress["total"] = len(data)
        dest.write_bytes(data)
        progress["done"] = len(data)

    system.colour.start_download(fetch=fake_fetch)
    end = time.time() + 10
    while system.colour.download["running"] and time.time() < end:
        time.sleep(0.1)
    st = system.colour.status()
    assert st["installed"] and not st["download"]["error"]

    def no_internet(url, dest, progress):
        raise OSError("no route")

    system.colour.model_path.unlink()
    system.colour.load()
    system.colour.start_download(fetch=no_internet)
    end = time.time() + 10
    while system.colour.download["running"] and time.time() < end:
        time.sleep(0.1)
    assert "internet" in system.colour.status()["download"]["error"]
