#!/usr/bin/env python3
"""Post a few live camera frames to the dashboard.

Uses the same path as a real alert: Supabase Storage, then
POST /api/detections. The cards are labeled "test" so they are not
shown as safety incidents. Subscribed browsers still get the portal's
incident push, because that is what the ingest endpoint always sends.

Quit live_preview.py first. The camera usually allows one stream.

    python3 test_dashboard_snapshots.py
    python3 test_dashboard_snapshots.py --count 3 --gap 2
"""

from __future__ import annotations

import argparse
import time
from datetime import datetime

import numpy as np

from cloud_store import publish_detection
from config import CAMERA_CHANNEL, CAMERA_IP, CAMERA_SUBTYPE, DAYCARE_NAME, PORTAL_URL
from stream_utils import (
    build_rtsp_url,
    log_stream_failure,
    open_ffmpeg_pipe,
    probe_stream,
)


def grab_frames(count: int, gap: float, channel: int, subtype: int) -> list[np.ndarray]:
    url = build_rtsp_url(channel, subtype)
    info = probe_stream(url)
    if not info:
        raise SystemExit("Could not open the camera stream. Quit live_preview.py if it is running.")

    proc, stderr_tail, width, height = open_ffmpeg_pipe(
        url, info["width"], info["height"], out_width=416, out_fps=5,
    )
    frame_size = width * height * 3
    frames: list[np.ndarray] = []
    next_take = time.time()
    try:
        while len(frames) < count:
            raw = proc.stdout.read(frame_size)
            if len(raw) != frame_size:
                log_stream_failure(proc, stderr_tail, len(raw), frame_size)
                break
            if time.time() < next_take:
                continue
            frame = np.frombuffer(raw, dtype=np.uint8).reshape((height, width, 3)).copy()
            frames.append(frame)
            next_take = time.time() + gap
            print(f"  grabbed frame {len(frames)}/{count}")
    finally:
        proc.kill()
        proc.wait(timeout=5)
    if len(frames) < count:
        raise SystemExit(f"Only grabbed {len(frames)} of {count} frames.")
    return frames


def main() -> None:
    parser = argparse.ArgumentParser(description="Post random live frames to the dashboard")
    parser.add_argument("--count", type=int, default=3, help="How many frames to post")
    parser.add_argument("--gap", type=float, default=2.0, help="Seconds between frames")
    parser.add_argument("--channel", type=int, default=CAMERA_CHANNEL)
    parser.add_argument("--subtype", type=int, default=CAMERA_SUBTYPE, choices=[0, 1])
    args = parser.parse_args()
    if args.count < 1:
        raise SystemExit("--count must be at least 1")

    print("Dashboard snapshot test")
    print(f"  Camera: {CAMERA_IP}  channel {args.channel}")
    print(f"  Portal: {PORTAL_URL or '(PORTAL_URL missing)'}")
    print(f"  Daycare: {DAYCARE_NAME or CAMERA_IP}")
    print(f"  Posting {args.count} frame(s). Subscribed browsers will get a push for each one.")

    frames = grab_frames(args.count, args.gap, args.channel, args.subtype)
    posted = 0
    for index, frame in enumerate(frames, start=1):
        result = publish_detection(
            frame,
            datetime.now().astimezone(),
            confidence=0.0,
            label="test",
            channel=args.channel,
        )
        web = result.get("web") or {}
        if web.get("ok"):
            posted += 1
            print(f"  posted {index}/{args.count} as detection id={web.get('id')}")
        else:
            print(f"  post {index}/{args.count} did not reach the dashboard")

    print(f"Done. {posted}/{args.count} on the dashboard. Refresh the portal.")
    if posted != args.count:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
