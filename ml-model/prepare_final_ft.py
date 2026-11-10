#!/usr/bin/env python3
"""Build a fine-tune set from ml-model/final_data.

Does not delete source files. Filters:
  - skip identical *_r1 stills
  - skip aftermath stills (violence_022 / 023)
  - drop near-empty safe clips
  - keep a few clips per safe time-block
  - keep high-motion frames from violence videos (contact, not standing)
  - hold out whole violence clips for a real test
"""

from __future__ import annotations

import random
import re
import shutil
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).parent
SRC = ROOT / "final_data"
DST = ROOT / "dataset_final"
PRIOR_SAFE = (
    ROOT / "dataset_actions" / "train" / "non_violence",
    ROOT / "dataset_actions" / "val" / "non_violence",
)
HELD_OUT_FILE = ROOT / "held_out_final.txt"
SEED = 0
SAMPLE_FPS = 2.0
JPEG_QUALITY = 85
MAX_SAFE_PER_BLOCK = 6
STATIC_MOTION = 1.2
VIOLENCE_REPEAT = 1
SAFE_TRAIN_FRAMES = 16
SAFE_VAL_FRAMES = 8
WEAK_STILLS = {"violence_022", "violence_023"}
HOLD_OUT = (
    "clip_20261104_112548.mp4",
    "clip_20261104_165534.mp4",
)
# Confirmed false alarms: empty room + kids playing. Never drop these.
KEEP_SAFE = {
    "clip_20261104_135225.mp4",
    "clip_20261104_122717.mp4",
}
KEEP_SAFE_FRAMES = 40
KEEP_SAFE_REPEAT = 2


def downscale(frame, long_side: int = 640):
    height, width = frame.shape[:2]
    longest = max(height, width)
    if longest <= long_side:
        return frame
    scale = long_side / longest
    return cv2.resize(
        frame,
        (max(1, int(width * scale)), max(1, int(height * scale))),
        interpolation=cv2.INTER_AREA,
    )


def write_jpg(frame, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(dest), frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])


def clip_time(path: Path) -> datetime | None:
    match = re.search(r"clip_(\d{8})_(\d{6})", path.name)
    if not match:
        return None
    return datetime.strptime(match.group(1) + match.group(2), "%Y%m%d%H%M%S")


def read_frames(video: Path) -> tuple[list, float]:
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 5.0
    frames = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frames.append(frame)
    cap.release()
    return frames, float(fps)


def frame_motion(frames: list) -> np.ndarray:
    if not frames:
        return np.zeros(0)
    diffs = [0.0]
    prev = cv2.resize(cv2.cvtColor(frames[0], cv2.COLOR_BGR2GRAY), (160, 90))
    for frame in frames[1:]:
        gray = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (160, 90))
        diffs.append(float(np.mean(cv2.absdiff(prev, gray))))
        prev = gray
    return np.convolve(np.array(diffs), np.ones(3) / 3, mode="same")


def mean_motion(video: Path) -> float:
    frames, _ = read_frames(video)
    scores = frame_motion(frames)
    return float(scores.mean()) if len(scores) else 0.0


def violence_frames(video: Path) -> list:
    frames, fps = read_frames(video)
    if not frames:
        return []
    scores = frame_motion(frames)
    step = max(1, int(round(fps / SAMPLE_FPS)))
    thresh = max(float(np.percentile(scores, 55)), 2.5)
    picked = [
        downscale(frames[i])
        for i in range(0, len(frames), step)
        if scores[i] >= thresh
    ]
    if len(picked) < 8:
        picked = [downscale(frames[i]) for i in range(0, len(frames), step)]
    return picked[:20]


def safe_frames(video: Path, limit: int = 8) -> list:
    frames, fps = read_frames(video)
    if not frames:
        return []
    step = max(1, int(round(fps / SAMPLE_FPS)))
    sampled = [downscale(frames[i]) for i in range(0, len(frames), step)]
    if len(sampled) <= limit:
        return sampled
    indexes = np.linspace(0, len(sampled) - 1, limit, dtype=int)
    return [sampled[i] for i in indexes]


def unique_stills(folder: Path) -> list[Path]:
    stills = []
    for path in sorted(folder.glob("*.jpg")):
        stem = path.stem
        if re.search(r"_r\d+$", stem):
            continue
        if stem in WEAK_STILLS:
            continue
        stills.append(path)
    return stills


def pick_safe_clips(clips: list[Path]) -> list[Path]:
    scored = []
    for path in clips:
        motion = mean_motion(path)
        print(f"  safe {path.name}  motion={motion:.2f}")
        if motion < STATIC_MOTION and path.name not in KEEP_SAFE:
            print("    drop (empty / static)")
            continue
        if path.name in KEEP_SAFE:
            print("    keep (confirmed false alarm)")
        scored.append((path, motion, clip_time(path)))

    scored.sort(key=lambda item: item[2] or datetime.min)
    kept: list[Path] = []
    block: list[tuple[Path, float, datetime | None]] = []

    def flush() -> None:
        if not block:
            return
        block.sort(key=lambda item: item[1], reverse=True)
        chosen = block[:MAX_SAFE_PER_BLOCK]
        chosen.sort(key=lambda item: item[2] or datetime.min)
        kept.extend(path for path, _motion, _ts in chosen)
        for path, _motion, _ts in block:
            if path.name in KEEP_SAFE and path not in kept:
                kept.append(path)

    for item in scored:
        if not block:
            block.append(item)
            continue
        prev_ts = block[-1][2]
        cur_ts = item[2]
        if prev_ts and cur_ts and (cur_ts - prev_ts).total_seconds() <= 90:
            block.append(item)
        else:
            flush()
            block = [item]
    flush()
    return kept


def reset_split() -> None:
    if DST.exists():
        shutil.rmtree(DST)
    for split in ("train", "val"):
        for label in ("non_violence", "violence"):
            (DST / split / label).mkdir(parents=True)


def count(split: str, label: str) -> int:
    return len(list((DST / split / label).glob("*.jpg")))


def main() -> None:
    random.seed(SEED)
    violence_dir = SRC / "violence"
    safe_dir = SRC / "non-violence"
    if not violence_dir.is_dir() or not safe_dir.is_dir():
        raise SystemExit(f"Expected {violence_dir} and {safe_dir}")

    reset_split()

    prior_copied = 0
    for folder in PRIOR_SAFE:
        if not folder.is_dir():
            continue
        split = "val" if folder.parent.name == "val" else "train"
        for path in sorted(folder.glob("*.jpg")):
            if re.search(r"_r\d+", path.stem):
                continue
            dest = DST / split / "non_violence" / f"prior_{path.name}"
            if dest.exists():
                continue
            try:
                dest.hardlink_to(path)
            except OSError:
                shutil.copy2(path, dest)
            prior_copied += 1
    print(f"Prior calm frames copied: {prior_copied}")

    print("Selecting safe clips")
    safe_clips = pick_safe_clips(sorted(safe_dir.glob("*.mp4")))
    for name in KEEP_SAFE:
        extra = safe_dir / name
        if extra.is_file() and extra not in safe_clips:
            safe_clips.append(extra)
            print(f"  force-add {name}")
    if len(safe_clips) < 6:
        raise SystemExit("Not enough active safe clips after filtering")
    order = safe_clips[:]
    random.shuffle(order)
    val_n = max(2, int(round(len(order) * 0.2)))
    val_safe = {path for path in order[:val_n] if path.name not in KEEP_SAFE}
    for path in safe_clips:
        forced = path.name in KEEP_SAFE
        split = "train" if forced else ("val" if path in val_safe else "train")
        limit = KEEP_SAFE_FRAMES if forced else (
            SAFE_TRAIN_FRAMES if split == "train" else SAFE_VAL_FRAMES
        )
        frames = safe_frames(path, limit=limit)
        repeats = KEEP_SAFE_REPEAT if forced else 1
        for copy_i in range(repeats):
            suffix = "" if copy_i == 0 else f"_r{copy_i}"
            for index, frame in enumerate(frames):
                write_jpg(
                    frame,
                    DST / split / "non_violence" / f"{path.stem}{suffix}_{index:03d}.jpg",
                )
        print(f"  keep {path.name} -> {split} ({len(frames)} frames x{repeats})")

    videos = sorted(violence_dir.glob("*.mp4"))
    if not videos:
        raise SystemExit(f"No violence videos in {violence_dir}")
    missing = [name for name in HOLD_OUT if not (violence_dir / name).is_file()]
    if missing:
        raise SystemExit(f"Hold-out clip missing: {missing}")

    print("Sampling violence clips")
    held_lines = []
    for video in videos:
        frames = violence_frames(video)
        if not frames:
            print(f"  skip {video.name} (unreadable)")
            continue
        hold = video.name in HOLD_OUT
        split = "val" if hold else "train"
        repeats = 1 if hold else VIOLENCE_REPEAT
        written = 0
        for copy_i in range(repeats):
            suffix = "" if copy_i == 0 else f"_r{copy_i}"
            for index, frame in enumerate(frames):
                write_jpg(
                    frame,
                    DST / split / "violence" / f"{video.stem}{suffix}_{index:03d}.jpg",
                )
                written += 1
        tag = "HOLD-OUT val" if hold else "train"
        print(f"  {video.name}: {len(frames)} motion frames -> {tag}")
        if hold:
            held_lines.append(video.name)

    stills = unique_stills(violence_dir)
    for path in stills:
        image = cv2.imread(str(path))
        if image is None:
            continue
        write_jpg(downscale(image), DST / "train" / "violence" / f"{path.stem}.jpg")
    print(f"  stills kept in train: {len(stills)} (skipped _r1 and aftermath)")

    HELD_OUT_FILE.write_text("\n".join(held_lines) + "\n")
    print(f"\nheld-out violence clips: {', '.join(held_lines)}")
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
    print(f"dataset: {DST}")


if __name__ == "__main__":
    main()
