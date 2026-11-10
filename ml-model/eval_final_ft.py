#!/usr/bin/env python3
"""Score held-out final_data clips the same way the live monitor does."""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
from ultralytics import YOLO

ROOT = Path(__file__).parent
SRC = ROOT / "final_data"
WEIGHTS = ROOT / "violence_yolov8n_cls-4" / "weights" / "best_final_ft.pt"
HELD_OUT_FILE = ROOT / "held_out_final.txt"
INFER_SIZE = 224
CONF = 0.60
SAMPLE_FPS = 2.0


def device() -> str:
    try:
        import torch

        if torch.cuda.is_available():
            return "0"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


def letterbox_like_monitor(frame_bgr):
    height, width = frame_bgr.shape[:2]
    long_side = max(height, width)
    if long_side > 640:
        scale = 640 / long_side
        frame_bgr = cv2.resize(
            frame_bgr,
            (max(1, int(width * scale)), max(1, int(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
    return frame_bgr


def score_video(model, video: Path) -> dict:
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 5.0
    step = max(1, int(round(fps / SAMPLE_FPS)))
    names = dict(model.names)
    violence_idx = next(
        (i for i, n in names.items() if "violence" in n.lower() and "non" not in n.lower()),
        1,
    )
    n = 0
    hits = 0
    confs = []
    index = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if index % step == 0:
            results = model.predict(
                letterbox_like_monitor(frame),
                verbose=False,
                imgsz=INFER_SIZE,
                device=device(),
            )
            probs = results[0].probs
            raw = probs.data.cpu().numpy()
            violence_conf = float(raw[violence_idx])
            top1 = int(probs.top1)
            confs.append(violence_conf)
            n += 1
            if top1 == violence_idx and violence_conf >= CONF:
                hits += 1
        index += 1
    cap.release()
    mean = sum(confs) / len(confs) if confs else 0.0
    return {"n": n, "hits": hits, "mean": mean}


def main() -> None:
    weights = Path(sys.argv[1]) if len(sys.argv) > 1 else WEIGHTS
    if not weights.is_file():
        raise SystemExit(f"Missing {weights}")
    model = YOLO(str(weights))
    held = []
    if HELD_OUT_FILE.is_file():
        held = [line.strip() for line in HELD_OUT_FILE.read_text().splitlines() if line.strip()]
    print(f"Weights: {weights}")
    print(f"Held-out: {held or '(none listed)'}\n")

    violence_dir = SRC / "violence"
    safe_dir = SRC / "non-violence"
    rows = []
    for name in (
        "clip_20261104_135225.mp4",
        "clip_20261104_122717.mp4",
    ):
        path = safe_dir / name
        if path.is_file():
            rows.append(("FA check", path))
    for name in held:
        path = violence_dir / name
        if path.is_file():
            rows.append(("HOLD violence", path))
    for path in sorted(violence_dir.glob("*.mp4")):
        if path.name not in held:
            rows.append(("train violence", path))
    safe = sorted(safe_dir.glob("*.mp4"))
    # A few active and a few empty-looking safes if present.
    for path in safe[:3] + safe[-3:]:
        rows.append(("safe", path))

    print(f"{'role':<16} {'file':<42} {'hits':>8} {'mean':>8}")
    for role, path in rows:
        stats = score_video(model, path)
        rate = f"{stats['hits']}/{stats['n']}"
        print(f"{role:<16} {path.name:<42} {rate:>8} {stats['mean']:.2%}")
        if role == "HOLD violence" and stats["hits"] < 8:
            print("  warning: held-out clip would likely not confirm an alert (need 8 hits / 45s)")
        if role == "FA check" and stats["hits"] >= 8:
            print("  warning: this false-alarm clip would still fire on the live monitor")


if __name__ == "__main__":
    main()
