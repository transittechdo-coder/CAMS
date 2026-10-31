"""Train the fire / smoke checker (the "second opinion" behind CAMS fire and smoke alarms).

How it works: MobileNetV2 (OpenCV model zoo, Apache 2.0) turns a picture into 1280 numbers that
describe what is in it. A small neural network (one hidden layer of 128) learns from those numbers
whether the picture shows fire, smoke or nothing special. Only the small network is trained here;
it is saved to cams/data/fire_smoke_head.npz (about 0.7 MB) and shipped with CAMS.

Training pictures:
  * FIRE-SMOKE-DATASET (DeepQuestAI on GitHub): 3000 pictures of fire, smoke and normal scenes,
    each also cut, flipped, blurred and made low-resolution like CCTV.
  * Normal CCTV video (shopping centre, street, corridor, warehouse, night market...): the bright
    and orange spots that used to start false fire alarms are cut out and taught as "not fire".
  * Real CCTV fires.
  * "Hard" look-alikes: every spot the checker itself wrongly called fire or smoke in normal videos
    (traffic cones, lit shop signs, lamps...), taught as "not fire" three times over.

    python scripts/train_fire_smoke.py feats_fsd.npz feats_cctv.npz feats_hardneg.npz

The two .npz files hold the MobileNetV2 numbers of the pictures (made with the same preparation as
cams/emergency.py: resize to 224 x 224, RGB, ImageNet mean / std, layer "472").
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler

NEGATIVE_CCTV = ["neg_mall", "neg_tree", "neg_megamind", "neg_corridor", "neg_street", "neg_warehouse",
                 "neg_market_night_train", "neg_market_night"]
FIRE_CCTV = ["pos_market_fire", "pos_highway_fire"]


def main(fsd: str, cctv: str, hardneg: str) -> None:
    d, c, hn = np.load(fsd), np.load(cctv), np.load(hardneg)
    neg = np.concatenate([c[k] for k in NEGATIVE_CCTV])
    hard = np.concatenate([hn[k] for k in hn.files])
    fire = np.concatenate([c[k] for k in FIRE_CCTV])
    X = np.concatenate([d["X"], neg, neg, hard, hard, hard, fire, fire])
    Y = np.concatenate([d["Y"], np.zeros(2 * len(neg) + 3 * len(hard), int), np.ones(2 * len(fire), int)])
    sc = StandardScaler().fit(X)
    m = MLPClassifier(hidden_layer_sizes=(128,), alpha=1e-2, max_iter=300, early_stopping=True, random_state=0)
    m.fit(sc.transform(X), Y)
    out = Path(__file__).resolve().parent.parent / "cams" / "data" / "fire_smoke_head.npz"
    np.savez_compressed(out, mean=sc.mean_.astype(np.float32), scale=sc.scale_.astype(np.float32),
                        w1=m.coefs_[0].astype(np.float32), b1=m.intercepts_[0].astype(np.float32),
                        w2=m.coefs_[1].astype(np.float32), b2=m.intercepts_[1].astype(np.float32),
                        classes=np.array(["none", "fire", "smoke"]))
    print(f"saved {out} ({out.stat().st_size // 1024} KB), trained on {len(Y)} pictures")


if __name__ == "__main__":
    main(*sys.argv[1:4])
