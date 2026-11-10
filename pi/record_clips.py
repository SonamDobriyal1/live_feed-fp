#!/usr/bin/env python3
"""Record the live camera into 30-second clips for later labeling.

Clips land in pi/recordings/. Stop with Ctrl+C.

    python3 record_clips.py
    python3 record_clips.py --seconds 30 --subtype 0
    python3 record_clips.py --match-live
    python3 record_clips.py --max-gb 20

--match-live records the same picture the model sees (sub-stream, 416px, 5fps).
HD (subtype 0, default) is a master archive only.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from config import CAMERA_CHANNEL, CAMERA_IP, CAMERA_SUBTYPE, DECODE_FPS, DECODE_WIDTH
from stream_utils import (
    FFMPEG,
    build_rtsp_url,
    ffmpeg_input_opts,
    mask_url,
    probe_stream,
    scaled_even,
)

DEFAULT_DIR = Path(__file__).parent / "recordings"


def folder_bytes(folder: Path) -> int:
    return sum(p.stat().st_size for p in folder.glob("clip_*.mp4") if p.is_file())


def list_clips(folder: Path) -> list[Path]:
    return sorted(p for p in folder.glob("clip_*.mp4") if p.is_file())


def announce_saved(path: Path) -> None:
    mb = path.stat().st_size / (1024 * 1024) if path.exists() else 0
    print(f"  saved {path.name}  {mb:.1f} MB")


def ffmpeg_cmd(
    url: str,
    out_pattern: str,
    seconds: int,
    *,
    src_w: int,
    src_h: int,
    decode_width: int | None,
    fps: float | None,
    reencode: bool,
) -> list[str]:
    cmd = [
        FFMPEG,
        *ffmpeg_input_opts(),
        "-i", url,
        "-an",
        "-map", "0:v:0",
        "-f", "segment",
        "-segment_time", str(seconds),
        "-segment_format", "mp4",
        "-reset_timestamps", "1",
        "-strftime", "1",
    ]
    match_model = decode_width is not None or (fps is not None and fps > 0)
    if match_model:
        out_w, out_h = scaled_even(src_w, src_h, decode_width)
        filters = [f"scale={out_w}:{out_h}:flags=fast_bilinear"]
        if fps and fps > 0:
            filters.append(f"fps={fps}")
            cmd += ["-g", str(max(1, int(round(fps * seconds))))]
        cmd += [
            "-vf", ",".join(filters),
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
        ]
    elif reencode:
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p"]
    else:
        cmd += ["-break_non_keyframes", "1", "-c:v", "copy", "-tag:v", "hvc1"]
    cmd.append(out_pattern)
    return cmd


def record_session(
    url: str,
    folder: Path,
    seconds: int,
    max_gb: float | None,
    **ffmpeg_kwargs,
) -> int:
    pattern = str(folder / "clip_%Y%m%d_%H%M%S.mp4")
    already = set(list_clips(folder))
    if already:
        print(f"  already have {len(already)} clip(s) in {folder}")

    proc = subprocess.Popen(
        ffmpeg_cmd(url, pattern, seconds, **ffmpeg_kwargs),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    assert proc.stderr is not None
    current: Path | None = None
    saved = 0

    try:
        while True:
            code = proc.poll()
            clips = [p for p in list_clips(folder) if p not in already]
            if clips:
                newest = clips[-1]
                if current is None:
                    current = newest
                    print(f"  recording {newest.name} ...")
                elif newest != current:
                    announce_saved(current)
                    saved += 1
                    current = newest
                    print(f"  recording {newest.name} ...")

            if max_gb is not None and folder_bytes(folder) >= max_gb * (1024 ** 3):
                print(f"  reached --max-gb {max_gb:g}, stopping")
                break

            if code is not None:
                err = proc.stderr.read().decode(errors="replace").strip()
                if err:
                    print(f"  ffmpeg stopped: {err[-400:]}")
                return saved

            time.sleep(1)
    except KeyboardInterrupt:
        print("\n  stopping...")
        raise
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        if current is not None and current.exists():
            announce_saved(current)
            saved += 1
    return saved


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Save the live camera as 30-second MP4 clips for later labeling",
    )
    parser.add_argument("--seconds", type=int, default=30, help="Clip length (default 30)")
    parser.add_argument("--channel", type=int, default=CAMERA_CHANNEL)
    parser.add_argument(
        "--subtype",
        type=int,
        default=None,
        choices=[0, 1],
        help="0=main HD, 1=sub-stream (default 0, or .env subtype with --match-live)",
    )
    parser.add_argument(
        "--match-live",
        action="store_true",
        help=f"Same picture as the model: subtype {CAMERA_SUBTYPE}, {DECODE_WIDTH}px, {DECODE_FPS:.0f} fps",
    )
    parser.add_argument(
        "--decode-width",
        type=int,
        default=None,
        help="Max frame width (live monitor uses 416). Implies re-encode.",
    )
    parser.add_argument(
        "--fps",
        type=float,
        default=None,
        help="Saved frame rate (live monitor uses 5). Implies re-encode.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help=f"Output folder (default {DEFAULT_DIR} or {DEFAULT_DIR / 'live'} with --match-live)",
    )
    parser.add_argument(
        "--reencode",
        action="store_true",
        help="Re-encode H.264 instead of copying the camera codec (use if clips will not play)",
    )
    parser.add_argument(
        "--max-gb",
        type=float,
        default=None,
        help="Stop after the recordings folder reaches this size",
    )
    args = parser.parse_args()
    if args.seconds < 2:
        raise SystemExit("--seconds must be at least 2")

    if args.match_live:
        if args.subtype is None:
            args.subtype = CAMERA_SUBTYPE
        if args.decode_width is None:
            args.decode_width = DECODE_WIDTH
        if args.fps is None:
            args.fps = DECODE_FPS
        if args.out is None:
            args.out = DEFAULT_DIR / "live"
    else:
        if args.subtype is None:
            args.subtype = 0
        if args.out is None:
            args.out = DEFAULT_DIR

    if not Path(FFMPEG).exists() and not shutil.which("ffmpeg"):
        raise SystemExit("ERROR: ffmpeg not found. Install with: brew install ffmpeg  (or apt install ffmpeg)")

    folder = args.out.expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=True)

    url = build_rtsp_url(args.channel, args.subtype)
    print("Live clip recorder — no alerts are sent")
    print(f"  Camera: {CAMERA_IP}  channel {args.channel}  subtype {args.subtype}")
    print(f"  Clip length: {args.seconds}s")
    if args.decode_width or args.fps:
        print(
            f"  Saved as: ≤{args.decode_width or 'native'}px @ "
            f"{args.fps if args.fps else 'native'} fps  (model-matched)"
        )
    else:
        print("  Saved as: camera original (HD archive)")
    print(f"  Folder: {folder}")
    print(f"  URL: {mask_url(url)}")
    if args.subtype == CAMERA_SUBTYPE:
        print("  Note: violence_monitor.py uses this same subtype. Quit it if the camera refuses a second stream.")

    info = probe_stream(url)
    if not info:
        raise SystemExit("Could not open the camera stream.")
    print(f"  Stream: {info['width']}x{info['height']}  {info['codec']}  {info['fps_str']}")
    print("  Ctrl+C to stop\n")

    ffmpeg_kwargs = {
        "src_w": info["width"],
        "src_h": info["height"],
        "decode_width": args.decode_width,
        "fps": args.fps,
        "reencode": args.reencode,
    }
    total = 0
    try:
        while True:
            started = datetime.now().strftime("%H:%M:%S")
            print(f"  ffmpeg started at {started}")
            total += record_session(url, folder, args.seconds, args.max_gb, **ffmpeg_kwargs)
            if args.max_gb is not None and folder_bytes(folder) >= args.max_gb * (1024 ** 3):
                break
            print("  stream dropped, reconnecting in 2s...")
            time.sleep(2)
    except KeyboardInterrupt:
        pass

    n = len(list_clips(folder))
    gb = folder_bytes(folder) / (1024 ** 3)
    print(f"\nDone. {n} clip(s) in {folder}  ({gb:.2f} GB)")
    print("Label later into violence / non_violence, then copy into ml-model/data/.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
