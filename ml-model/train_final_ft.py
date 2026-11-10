#!/usr/bin/env python3
"""Fine-tune the latest classifier on dataset_final.

Starts from best_newdata_ft.pt (falls back to best_action_ft.pt).
Does not overwrite best.pt, best_daycare_ft.pt, or best_action_ft.pt.
Only the classification head is trained.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from ultralytics import YOLO

ROOT = Path(__file__).parent
RUN_NAME = "violence_final_ft"
DATA = ROOT / "dataset_final"
WEIGHTS_DIR = ROOT / "violence_yolov8n_cls-4" / "weights"
CANDIDATES = (
    WEIGHTS_DIR / "best_newdata_ft.pt",
    WEIGHTS_DIR / "best_action_ft.pt",
)
EXPORT = WEIGHTS_DIR / "best_final_ft.pt"
PI_EXPORT = ROOT.parent / "pi" / "violence_yolov8n_cls-4" / "weights" / "best_final_ft.pt"


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


def starting_weights() -> Path:
    for path in CANDIDATES:
        if path.is_file():
            return path
    raise SystemExit("No starting checkpoint (best_newdata_ft.pt / best_action_ft.pt)")


def main() -> None:
    if not DATA.is_dir():
        raise SystemExit(f"Run prepare_final_ft.py first. Missing {DATA}")
    weights = starting_weights()
    if weights.name == "best.pt":
        raise SystemExit("Refusing to start from the original base weights")

    print(f"Starting from {weights}")
    model = YOLO(str(weights))
    print(f"Loaded classes: {dict(getattr(model, 'names', {}))}")
    model.train(
        data=str(DATA),
        epochs=8,
        patience=3,
        imgsz=224,
        batch=16,
        freeze=9,
        lr0=0.0003,
        lrf=0.1,
        optimizer="AdamW",
        weight_decay=0.0005,
        dropout=0.0,
        device=device(),
        workers=2,
        project=str(ROOT / "runs"),
        name=RUN_NAME,
        exist_ok=True,
        pretrained=True,
        verbose=True,
        plots=True,
        seed=0,
    )
    best = ROOT / "runs" / RUN_NAME / "weights" / "best.pt"
    if not best.is_file():
        raise SystemExit(f"Training finished but {best} is missing")
    EXPORT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(best, EXPORT)
    PI_EXPORT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(best, PI_EXPORT)
    print(f"Copied {best} -> {EXPORT}")
    print(f"Copied {best} -> {PI_EXPORT}")


if __name__ == "__main__":
    main()
