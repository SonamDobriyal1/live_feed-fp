"""
MJPEG HTTP Stream Viewer for CP Plus / Dahua cameras.

Many CP Plus cameras expose an MJPEG stream over HTTP — the simplest
way to view live video without RTSP or WebSocket complexity.

Usage:
    python3 mjpeg_viewer.py
    python3 mjpeg_viewer.py --channel 1
    python3 mjpeg_viewer.py --save output.mp4
"""

import argparse
import base64
import ssl
import sys
import time
import urllib.request

import cv2
import numpy as np

from config import CAMERA_IP, CAMERA_USER, CAMERA_PASS

MJPEG_PATHS = [
    "/cgi-bin/mjpg/video.cgi?channel={ch}&subtype=1",
    "/cgi-bin/video.cgi?channel={ch}&subtype=1",
    "/mjpg/video.mjpg",
    "/video/mjpg.cgi?ch={ch}",
    "/cgi-bin/CGIStream.cgi?cmd=GetMJStream&channel={ch}",
    "/streaming/channels/{ch}02/httppreview",   # Hikvision compatible
    "/cgi-bin/realmonitor.cgi?action=getStream&channel={ch}&subtype=1",
]


def make_auth_header() -> dict:
    creds = base64.b64encode(f"{CAMERA_USER}:{CAMERA_PASS}".encode()).decode()
    return {"Authorization": f"Basic {creds}"}


def try_mjpeg_url(url: str) -> urllib.request.addinfourl | None:
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        req = urllib.request.Request(url, headers=make_auth_header())
        resp = urllib.request.urlopen(req, context=ctx, timeout=6)

        content_type = resp.headers.get("Content-Type", "")
        if "multipart" in content_type or "mjpeg" in content_type or resp.status == 200:
            return resp
        resp.close()
    except Exception:
        pass
    return None


def find_mjpeg_stream(channel: int = 1) -> tuple[urllib.request.addinfourl, str] | tuple[None, None]:
    for scheme in ("http", "https"):
        for path_tpl in MJPEG_PATHS:
            path = path_tpl.format(ch=channel)
            url = f"{scheme}://{CAMERA_IP}{path}"
            print(f"  Trying: {url}")
            resp = try_mjpeg_url(url)
            if resp:
                print(f"  ✓ Working MJPEG stream: {url}")
                return resp, url
            print(f"  ✗ Failed")
    return None, None


def read_mjpeg_frames(resp: urllib.request.addinfourl):
    """Generator: yields raw JPEG bytes from an MJPEG HTTP stream."""
    boundary = None
    content_type = resp.headers.get("Content-Type", "")
    if "boundary=" in content_type:
        boundary = content_type.split("boundary=")[-1].strip().encode()

    buf = b""
    while True:
        chunk = resp.read(8192)
        if not chunk:
            break
        buf += chunk

        while True:
            start = buf.find(b"\xff\xd8")
            end = buf.find(b"\xff\xd9", start + 2) if start != -1 else -1
            if start != -1 and end != -1:
                yield buf[start: end + 2]
                buf = buf[end + 2:]
            else:
                break


def display_mjpeg(resp: urllib.request.addinfourl, save_path: str = None):
    writer = None
    frame_count = 0
    start = time.time()

    print("\nStream running. Press 'q' to quit, 's' for snapshot.")
    for jpeg_bytes in read_mjpeg_frames(resp):
        arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None:
            continue

        frame_count += 1
        elapsed = time.time() - start
        fps = frame_count / elapsed if elapsed > 0 else 0

        if writer is None and save_path:
            h, w = frame.shape[:2]
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter(save_path, fourcc, 10.0, (w, h))
            print(f"Recording to {save_path}")

        cv2.putText(frame, f"FPS: {fps:.1f}  Frames: {frame_count}",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.putText(frame, time.strftime("%Y-%m-%d %H:%M:%S"),
                    (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 2)

        if writer:
            writer.write(frame)
        cv2.imshow("CP Plus MJPEG Feed", frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        elif key == ord("s"):
            fn = f"snapshot_{time.strftime('%Y%m%d_%H%M%S')}.png"
            cv2.imwrite(fn, frame)
            print(f"Snapshot saved: {fn}")

    if writer:
        writer.release()
    cv2.destroyAllWindows()
    resp.close()


def main():
    parser = argparse.ArgumentParser(description="CP Plus MJPEG HTTP Stream Viewer")
    parser.add_argument("--channel", type=int, default=1, help="Camera channel (default: 1)")
    parser.add_argument("--url", help="Use a specific MJPEG URL")
    parser.add_argument("--save", metavar="FILE", help="Save recording to MP4")
    args = parser.parse_args()

    print("=" * 55)
    print("  CP Plus MJPEG Stream Viewer")
    print(f"  Camera: {CAMERA_IP}  Channel: {args.channel}")
    print("=" * 55)

    if args.url:
        resp = try_mjpeg_url(args.url)
        if not resp:
            print(f"ERROR: Could not connect to {args.url}")
            sys.exit(1)
    else:
        print("\nSearching for MJPEG stream...")
        resp, url = find_mjpeg_stream(args.channel)
        if not resp:
            print("\nERROR: No working MJPEG stream found.")
            print("Try: python3 rtsp_viewer.py  (for RTSP)")
            sys.exit(1)

    display_mjpeg(resp, save_path=args.save)


if __name__ == "__main__":
    main()
