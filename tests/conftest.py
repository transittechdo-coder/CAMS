import os
import sys
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CACHE = ROOT / "tests" / ".cache"
SAMPLES = {
    # Public OpenCV sample images used only for automated tests.
    "face.jpg": "https://raw.githubusercontent.com/opencv/opencv/4.x/samples/data/lena.jpg",
    "video.avi": "https://raw.githubusercontent.com/opencv/opencv/4.x/samples/data/vtest.avi",
}


def sample(name: str) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / name
    if not p.exists():
        try:
            urllib.request.urlretrieve(SAMPLES[name], p)
        except Exception as exc:  # offline
            pytest.skip(f"test sample {name} unavailable: {exc}")
    return p


@pytest.fixture()
def system(tmp_path, monkeypatch):
    monkeypatch.setenv("CAMS_DATA_DIR", str(tmp_path / "data"))
    from cams.config import get_paths
    from cams.face_engine import models_present
    from cams.system import CamsSystem

    paths = get_paths()
    if not models_present(paths.models):
        pytest.skip("face models not downloaded (python scripts/download_models.py)")
    s = CamsSystem(paths, start_cameras=False)
    s.start()
    yield s
    s.stop()


@pytest.fixture()
def client(system):
    from fastapi.testclient import TestClient

    from cams.api import create_app

    with TestClient(create_app(system)) as c:
        yield c


@pytest.fixture()
def admin(client):
    r = client.post("/api/setup", json={"site_name": "Test School", "username": "admin", "password": "secret123"})
    assert r.status_code == 200, r.text
    return client
