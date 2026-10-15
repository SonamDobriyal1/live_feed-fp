"""
CP Plus Camera Live Feed — Auto-Detection Entry Point

Automatically discovers the best streaming method available:
  1. RTSP (best quality, lowest latency)
  2. MJPEG over HTTP (easy, no extra codecs)
  3. WebSocket (for web-portal-based streams)

Usage:
    python3 live_feed.py                       # auto-detect everything
    python3 live_feed.py --channel 2           # channel 2
    python3 live_feed.py --method rtsp         # force RTSP
    python3 live_feed.py --method mjpeg        # force MJPEG
    python3 live_feed.py --method websocket    # force WebSocket
    python3 live_feed.py --save recording.mp4  # save to file
    python3 live_feed.py --snapshot            # one frame then exit
    python3 live_feed.py --list-channels       # probe channels 1–4
"""

import argparse
import socket
import sys
import subprocess
import time

from config import CAMERA_IP, CAMERA_USER, CAMERA_PASS, RTSP_PORT


def check_port(ip: str, port: int, timeout: float = 2.0) -> bool:
    try:
        s = socket.create_connection((ip, port), timeout=timeout)
        s.close()
        return True
    except Exception:
        return False


def auto_detect_method() -> str:
    """Return the best streaming method based on open ports."""
    print(f"\nDetecting available services on {CAMERA_IP}...")

    if check_port(CAMERA_IP, RTSP_PORT):
        print(f"  ✓ RTSP port {RTSP_PORT} is open → using RTSP")
        return "rtsp"

    for port in (80, 8080):
        if check_port(CAMERA_IP, port):
            print(f"  ✓ HTTP port {port} is open → using MJPEG")
            return "mjpeg"

    for port in (443, 8443):
        if check_port(CAMERA_IP, port):
            print(f"  ✓ HTTPS port {port} is open → using MJPEG")
            return "mjpeg"

    print("  ! No known ports open — defaulting to RTSP (may fail)")
    return "rtsp"


def run_rtsp(channel: int, subtype: int, save: str, snapshot: bool):
    from rtsp_viewer import find_working_stream, display_stream, save_snapshot

    print("\n[ RTSP Mode ]")
    cap, url = find_working_stream(channel, subtype)
    if not cap:
        print("RTSP failed. Falling back to MJPEG...")
        run_mjpeg(channel, save, snapshot)
        return

    if snapshot:
        ts = time.strftime("%Y%m%d_%H%M%S")
        save_snapshot(cap, f"snapshot_{ts}.png")
        cap.release()
    else:
        display_stream(cap, save_path=save)


def run_mjpeg(channel: int, save: str, snapshot: bool):
    from mjpeg_viewer import find_mjpeg_stream, display_mjpeg
    import cv2

    print("\n[ MJPEG Mode ]")
    resp, url = find_mjpeg_stream(channel)
    if not resp:
        print("MJPEG failed. Falling back to WebSocket...")
        run_websocket(channel, save)
        return

    if snapshot:
        from mjpeg_viewer import read_mjpeg_frames
        import numpy as np
        for jpeg_bytes in read_mjpeg_frames(resp):
            arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frame is not None:
                fn = f"snapshot_{time.strftime('%Y%m%d_%H%M%S')}.png"
                cv2.imwrite(fn, frame)
                print(f"Snapshot saved: {fn}")
                resp.close()
                return
    else:
        display_mjpeg(resp, save_path=save)


def run_websocket(channel: int, save: str):
    import asyncio
    from websocket_client import probe_ws_endpoints, FrameDisplay
    import threading

    print("\n[ WebSocket Mode ]")
    display = FrameDisplay(save_path=save)
    t = threading.Thread(target=display.run, daemon=True)
    t.start()

    async def run():
        await probe_ws_endpoints(display, channel=channel)

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
    finally:
        display.running = False
        t.join(timeout=3)


def probe_channels(max_channels: int = 4):
    """Check which channels have active streams."""
    from rtsp_viewer import build_rtsp_urls, try_open_stream

    print(f"\nProbing channels 1–{max_channels} via RTSP...\n")
    working = []
    for ch in range(1, max_channels + 1):
        url = build_rtsp_urls(ch, 0)[0]
        masked = url.replace(CAMERA_PASS, "****")
        print(f"  Channel {ch}: {masked}")
        cap = try_open_stream(url, timeout=4)
        if cap:
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            print(f"    ✓ ACTIVE — {w}x{h} @ {fps:.1f} fps")
            working.append(ch)
            cap.release()
        else:
            print(f"    ✗ No stream")

    print(f"\nWorking channels: {working if working else 'None found'}")


def main():
    parser = argparse.ArgumentParser(
        description="CP Plus Camera Live Feed — Auto-Detection",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 live_feed.py                        # auto-detect + display
  python3 live_feed.py --channel 2            # camera channel 2
  python3 live_feed.py --method rtsp          # force RTSP
  python3 live_feed.py --method mjpeg         # force MJPEG HTTP
  python3 live_feed.py --method websocket     # force WebSocket
  python3 live_feed.py --save clip.mp4        # record to file
  python3 live_feed.py --snapshot             # save single frame PNG
  python3 live_feed.py --list-channels        # probe all channels
        """,
    )
    parser.add_argument("--channel", type=int, default=1, help="Camera channel (default: 1)")
    parser.add_argument("--subtype", type=int, default=0, choices=[0, 1],
                        help="RTSP subtype: 0=main (HD), 1=sub (lower res)")
    parser.add_argument("--method", choices=["auto", "rtsp", "mjpeg", "websocket"],
                        default="auto", help="Streaming method")
    parser.add_argument("--save", metavar="FILE", help="Save stream to MP4 file")
    parser.add_argument("--snapshot", action="store_true", help="Capture one frame and exit")
    parser.add_argument("--list-channels", action="store_true", help="Probe available channels")
    args = parser.parse_args()

    print("=" * 60)
    print("  CP Plus Camera Live Feed")
    print(f"  Target: {CAMERA_IP}  User: {CAMERA_USER}")
    print("=" * 60)

    if args.list_channels:
        import cv2
        probe_channels()
        return

    method = args.method
    if method == "auto":
        method = auto_detect_method()

    if method == "rtsp":
        run_rtsp(args.channel, args.subtype, args.save, args.snapshot)
    elif method == "mjpeg":
        run_mjpeg(args.channel, args.save, args.snapshot)
    elif method == "websocket":
        run_websocket(args.channel, args.save)


if __name__ == "__main__":
    main()
