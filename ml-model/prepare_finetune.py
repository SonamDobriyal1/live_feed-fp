"""Build a fine-tune set from ml-model/data.

One alert timestamp is one event. Safe daycare frames are the hard
negatives. The newest violence event is held out and never trained on.
"""

from __future__ import annotations

import random
import shutil
from pathlib import Path

import cv2

ROOT = Path(__file__).parent
SRC = ROOT / "data"
DST = ROOT / "dataset"
SEED = 0
VAL_FRACTION = 0.2
VIOLENCE_COPIES = 20
FRAMES_PER_CLIP = 6


def event_id(path: Path) -> str:
    name = path.name
    while name.lower().startswith("copy of "):
        name = name[8:]
    return Path(name).stem


def unique_images(folder: Path) -> dict[str, Path]:
    chosen: dict[str, Path] = {}
    for path in sorted(folder.iterdir()):
        if not path.is_file() or path.name.startswith("."):
            continue
        if path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            continue
        chosen.setdefault(event_id(path), path)
    return chosen


def clip_for(image: Path) -> Path | None:
    candidate = image.with_suffix(".mp4")
    if candidate.exists():
        return candidate
    copied = image.with_name(f"Copy of {image.stem}.mp4")
    return copied if copied.exists() else None


def sample_frames(video: Path, count: int) -> list:
    cap = cv2.VideoCapture(str(video))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if total <= 0:
        cap.release()
        return []
    indexes = {int(total * (i + 1) / (count + 1)) for i in range(count)}
    frames = []
    for index in sorted(indexes):
        cap.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = cap.read()
        if ok:
            frames.append(frame)
    cap.release()
    return frames


def reset_split() -> None:
    if DST.exists():
        shutil.rmtree(DST)
    for split in ("train", "val"):
        for label in ("non_violence", "violence"):
            (DST / split / label).mkdir(parents=True)


def link(src: Path, dest: Path) -> None:
    dest.hardlink_to(src) if not dest.exists() else None


def main() -> None:
    random.seed(SEED)
    safe = unique_images(SRC / "non_violence")
    violent = unique_images(SRC / "violence")
    if len(violent) < 2:
        raise SystemExit("Need at least 2 unique violence images.")

    held_out = sorted(violent)[-1]
    train_violence = [key for key in sorted(violent) if key != held_out]
    safe_ids = sorted(safe)
    random.shuffle(safe_ids)
    val_n = max(1, int(len(safe_ids) * VAL_FRACTION))
    val_safe = set(safe_ids[:val_n])

    reset_split()
    for key in safe_ids:
        split = "val" if key in val_safe else "train"
        link(safe[key], DST / split / "non_violence" / f"{key}.jpg")

    for key in train_violence:
        image = violent[key]
        for copy_i in range(VIOLENCE_COPIES):
            link(image, DST / "train" / "violence" / f"{key}_{copy_i}.jpg")
        video = clip_for(image)
        if video is None:
            continue
        for frame_i, frame in enumerate(sample_frames(video, FRAMES_PER_CLIP)):
            out = DST / "train" / "violence" / f"{key}_frame{frame_i}.jpg"
            cv2.imwrite(str(out), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])

    held_image = violent[held_out]
    link(held_image, DST / "val" / "violence" / f"{held_out}.jpg")
    (ROOT / "held_out_violence.txt").write_text(held_out + "\n")

    def count(split: str, label: str) -> int:
        return len(list((DST / split / label).glob("*")))

    print(f"held-out violence event: {held_out}")
    print(
        "train",
        f"non_violence={count('train', 'non_violence')}",
        f"violence={count('train', 'violence')}",
    )
    print(
        "val",
        f"non_violence={count('val', 'non_violence')}",
        f"violence={count('val', 'violence')}",
    )


if __name__ == "__main__":
    main()
