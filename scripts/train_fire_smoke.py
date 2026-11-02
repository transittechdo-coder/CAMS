"""Train the fire / smoke checker (the "second opinion" behind CAMS fire and smoke alarms).

How it works: MobileNetV2 (OpenCV model zoo, Apache 2.0) turns a picture into 1280 numbers that
describe what is in it. A team of small neural networks (256 -> 64 -> 3, three of them with different
starting points) learns from those numbers whether a picture shows fire, smoke or nothing special.
CAMS averages their answers. Only the small networks are trained here; they are saved to
cams/data/fire_smoke_head.npz (about 4 MB) and shipped with CAMS.

The pictures are cut the way CAMS cuts them: the flame-like or hazy spot plus what is around it
(1.3x to 4x its size), sometimes flipped, blurred, made low-resolution or noisy like CCTV.

Training pictures (v1.9.1, about 140 000 after repeats):
  * FIRE-SMOKE-DATASET (DeepQuestAI on GitHub): fire, smoke and normal pictures.
  * Indoor fire-smoke dataset (Shahriar-RL on GitHub): labelled fire and smoke boxes in rooms.
  * Real CCTV fires (night market, highway, a living-room curtain fire).
  * "Not fire" from normal video, about 41 000 pictures: every flame-coloured, glowing or hazy spot
    the rules find, plus random parts of the view. From customers' own camera clips (classroom,
    shop, street in the rain, school hall, office), older test clips (shopping centre, street,
    corridor, warehouse, film) and the Intel IoT sample videos (CC-BY 4.0: shops, offices, roads,
    factories). Customer clips count three times.
  * Earlier "hard" look-alikes (traffic cones, lit shop signs, lamps), three times.

    python scripts/train_fire_smoke.py FEATURES_DIR [--seeds 3] [--without u_retail,lr]

FEATURES_DIR holds the MobileNetV2 numbers of the pictures (made with FireSmokeAI.features):
  feats_fsd.npz (X, Y), feats_cctv.npz (pos_* / neg_* arrays), feats_hardneg.npz,
  feats_neg2/<video>.npy (not fire), feats_pos2.npz (X, Y: 1 fire, 2 smoke), feats_lr.npz (optional).
--without leaves sources out, for a fair test on a video the AI has never seen.
"""

from __future__ import annotations

import argparse
import collections
import glob
import os
from pathlib import Path

import numpy as np
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler

OUT = Path(__file__).resolve().parent.parent / "cams" / "data" / "fire_smoke_head.npz"


def load(folder: str, skip: set[str]):
    f = lambda name: os.path.join(folder, name)
    parts = []                                         # (X, Y, times repeated, name)
    d = np.load(f("feats_fsd.npz"))
    parts.append((d["X"], d["Y"], 1, "fsd"))
    c = np.load(f("feats_cctv.npz"))
    for k in c.files:
        parts.append((c[k], np.full(len(c[k]), 1 if k.startswith("pos_") else 0), 2, "c_" + k))
    hn = np.load(f("feats_hardneg.npz"))
    for k in hn.files:
        parts.append((hn[k], np.zeros(len(hn[k]), int), 3, "h_" + k))
    for p in sorted(glob.glob(f("feats_neg2/*.npy"))):
        name = os.path.basename(p)[:-4]
        X = np.load(p).astype(np.float32)
        parts.append((X, np.zeros(len(X), int), 3 if name.startswith("u_") else 2, name))
    p = np.load(f("feats_pos2.npz"))
    parts.append((p["X"].astype(np.float32), p["Y"], 1, "indoor"))
    if os.path.exists(f("feats_lr.npz")):
        lr = np.load(f("feats_lr.npz"))
        parts.append((lr["X"].astype(np.float32), lr["Y"], 3, "lr"))
    Xs, Ys = [], []
    for X, Y, k, name in parts:
        if name in skip or any(name.endswith(s) for s in skip) or len(X) == 0:
            continue
        Xs += [X] * k
        Ys += [Y] * k
    return np.concatenate(Xs).astype(np.float32), np.concatenate(Ys)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("features")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--without", default="")
    a = ap.parse_args()
    X, Y = load(a.features, set(filter(None, a.without.split(","))))
    print("training pictures:", len(Y), dict(collections.Counter(Y.tolist())), flush=True)
    sc = StandardScaler().fit(X)
    Xt = sc.transform(X)
    out = {"mean": sc.mean_.astype(np.float32), "scale": sc.scale_.astype(np.float32),
           "classes": np.array(["none", "fire", "smoke"])}
    for s in range(a.seeds):
        m = MLPClassifier(hidden_layer_sizes=(256, 64), alpha=1e-3, max_iter=60, early_stopping=True,
                          n_iter_no_change=6, batch_size=256, random_state=s).fit(Xt, Y)
        print(f"model {s}: validation accuracy {m.best_validation_score_:.4f}", flush=True)
        for i, (w, b) in enumerate(zip(m.coefs_, m.intercepts_), 1):
            out[f"m{s}_w{i}"] = w.astype(np.float32)
            out[f"m{s}_b{i}"] = b.astype(np.float32)
    np.savez_compressed(a.out, **out)
    print(f"saved {a.out} ({os.path.getsize(a.out) // 1024} KB)")


if __name__ == "__main__":
    main()
