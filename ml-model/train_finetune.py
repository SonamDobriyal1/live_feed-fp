"""Fine-tune the violence classifier on daycare false alarms.

Only the classification head is trained. The backbone stays frozen so the
model can learn this camera's safe scenes without a full retrain.
"""

from __future__ import annotations

from pathlib import Path

from ultralytics import YOLO

ROOT = Path(__file__).parent
WEIGHTS = ROOT / "violence_yolov8n_cls-4" / "weights" / "best.pt"


def main() -> None:
    model = YOLO(str(WEIGHTS))
    model.train(
        data=str(ROOT / "dataset"),
        epochs=20,
        patience=5,
        imgsz=224,
        batch=32,
        freeze=9,
        lr0=0.001,
        lrf=0.1,
        optimizer="AdamW",
        weight_decay=0.0005,
        dropout=0.0,
        device="cpu",
        workers=2,
        project=str(ROOT / "runs"),
        name="violence_daycare_ft",
        exist_ok=True,
        pretrained=True,
        verbose=True,
        plots=True,
    )


if __name__ == "__main__":
    main()
