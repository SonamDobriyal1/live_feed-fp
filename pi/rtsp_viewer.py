"""
RTSPS Live Feed Viewer for CP Plus camera.
Confirmed stream: rtsps://admin@122.175.45.21:554/video/live?channel=1&subtype=0
Resolution: 2560x1440 (4MP) | Codec: H.265/HEVC | FPS: 25

Uses ffmpeg subprocess to pipe decoded frames to OpenCV (required because
the pip opencv-python on macOS ARM does not include FFMPEG/HEVC support).

Usage:
    python3 rtsp_viewer.py                     # display live feed
    python3 rtsp_viewer.py --channel 2         # channel 2
    python3 rtsp_viewer.py --subtype 1         # sub-stream (lower res)
    python3 rtsp_viewer.py --save output.mp4   # record to file
    python3 rtsp_viewer.py --snapshot          # save one frame as PNG
    python3 rtsp_viewer.py --headless          # no display (record/snapshot only)
"""

import argparse
import subprocess
import sys
import time
import shutil
import os

import cv2
import numpy as np

from config import CAMERA_IP, CAMERA_USER, CAMERA_PASS, RTSP_PORT

FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"


def build_url(channel: int = 1, subtype: int = 0) -> str:
    return (f"rtsps://{CAMERA_USER}:{CAMERA_PASS}@{CAMERA_IP}:{RTSP_PORT}"
            f"/video/live?channel={channel}&subtype={subtype}")


def probe_stream(url: str) -> dict | None:
    """Return stream info dict or None if unreachable."""
    ffprobe = shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"
    masked = url.replace(CAMERA_PASS, "****")
    print(f"  Probing: {masked}")
    r = subprocess.run(
        [ffprobe, "-v", "error", "-tls_verify", "0",
         "-show_entries", "stream=codec_name,width,height,r_frame_rate",
         "-of", "csv=p=0", url],
        capture_output=True, text=True, timeout=10,
    )
    if r.returncode == 0 and r.stdout.strip():
        parts = r.stdout.strip().split("\n")[0].split(",")
        return {
            "codec": parts[0] if len(parts) > 0 else "?",
            "width": int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0,
            "height": int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0,
            "fps_str": parts[3] if len(parts) > 3 else "25/1",
        }
    return None


def open_ffmpeg_pipe(url: str, width: int, height: int) -> subprocess.Popen:
    """Open ffmpeg process that outputs raw BGR frames to stdout."""
    cmd = [
        FFMPEG,
        "-loglevel", "error",
        "-tls_verify", "0",          # skip TLS cert check
        "-rtsp_transport", "tcp",
        "-i", url,
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",  # ensure even dimensions
        "-f", "rawvideo",
        "-pix_fmt", "bgr24",
        "-",
    ]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            bufsize=10 * width * height * 3)


def run_viewer(url: str, info: dict, save_path: str = None,
               snapshot: bool = False, headless: bool = False):
    w, h = info["width"], info["height"]
    if w == 0 or h == 0:
        w, h = 1920, 1080  # fallback

    # For snapshot just grab one frame
    if snapshot:
        proc = open_ffmpeg_pipe(url, w, h)
        raw = proc.stdout.read(w * h * 3)
        proc.terminate()
        if len(raw) == w * h * 3:
            frame = np.frombuffer(raw, dtype=np.uint8).reshape((h, w, 3))
            fn = f"snapshot_{time.strftime('%Y%m%d_%H%M%S')}.png"
            cv2.imwrite(fn, frame)
            print(f"Snapshot saved: {fn}")
        else:
            print("Failed to capture frame.")
        return

    writer = None
    if save_path:
        fps_num, fps_den = (info["fps_str"].split("/") + ["1"])[:2]
        fps = float(fps_num) / float(fps_den)
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(save_path, fourcc, fps, (w, h))
        print(f"Recording to {save_path}  ({w}x{h} @ {fps:.1f} fps)")

    frame_size = w * h * 3
    frame_count = 0
    start = time.time()
    masked = url.replace(CAMERA_PASS, "****")
    print(f"\nStream: {masked}")
    print(f"Resolution: {w}x{h}  Codec: {info['codec']}  FPS: {info['fps_str']}")
    if not headless:
        print("Press 'q' to quit, 's' to save snapshot\n")

    while True:
        proc = open_ffmpeg_pipe(url, w, h)
        try:
            while True:
                raw = proc.stdout.read(frame_size)
                if len(raw) != frame_size:
                    print("Stream interrupted, reconnecting in 2s...")
                    time.sleep(2)
                    break

                frame = np.frombuffer(raw, dtype=np.uint8).reshape((h, w, 3))
                frame_count += 1
                elapsed = time.time() - start
                fps_live = frame_count / elapsed if elapsed > 0 else 0

                if writer:
                    writer.write(frame)

                if not headless:
                    disp = frame.copy()
                    cv2.putText(disp, f"FPS: {fps_live:.1f}  Frames: {frame_count}",
                                (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
                    cv2.putText(disp, time.strftime("%Y-%m-%d %H:%M:%S"),
                                (10, 65), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 255), 2)
                    cv2.putText(disp, f"{w}x{h} {info['codec'].upper()}",
                                (10, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 200, 0), 2)
                    cv2.imshow("CP Plus Live Feed", disp)
                    key = cv2.waitKey(1) & 0xFF
                    if key == ord("q"):
                        raise KeyboardInterrupt
                    elif key == ord("s"):
                        fn = f"snapshot_{time.strftime('%Y%m%d_%H%M%S')}.png"
                        cv2.imwrite(fn, frame)
                        print(f"Snapshot saved: {fn}")
        except KeyboardInterrupt:
            break
        finally:
            proc.terminate()

    if writer:
        writer.release()
        print(f"\nRecording saved: {save_path}")
    if not headless:
        cv2.destroyAllWindows()


def main():
    parser = argparse.ArgumentParser(description="CP Plus RTSPS Live Feed Viewer")
    parser.add_argument("--channel", type=int, default=1, help="Camera channel (default: 1)")
    parser.add_argument("--subtype", type=int, default=0, choices=[0, 1],
                        help="0=main stream HD, 1=sub-stream lower res")
    parser.add_argument("--save", metavar="FILE", help="Record to MP4 file")
    parser.add_argument("--snapshot", action="store_true", help="Save one frame PNG and exit")
    parser.add_argument("--headless", action="store_true", help="No display window (record only)")
    args = parser.parse_args()

    print("=" * 55)
    print("  CP Plus RTSPS Live Feed")
    print(f"  {CAMERA_IP}  Channel: {args.channel}  {'Sub' if args.subtype else 'Main'}-stream")
    print("=" * 55)

    if not shutil.which("ffmpeg") and not os.path.exists("/opt/homebrew/bin/ffmpeg"):
        print("ERROR: ffmpeg not found. Install with: brew install ffmpeg")
        sys.exit(1)

    url = build_url(args.channel, args.subtype)
    print("\nProbing stream...")
    info = probe_stream(url)
    if not info:
        print("ERROR: Could not connect to stream.")
        print("Make sure you are on the correct network and the IP/credentials are right.")
        sys.exit(1)

    print(f"  Connected! {info['width']}x{info['height']} {info['codec'].upper()} @ {info['fps_str']} fps\n")
    run_viewer(url, info, save_path=args.save, snapshot=args.snapshot, headless=args.headless)


if __name__ == "__main__":
    main()
