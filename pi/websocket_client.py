"""
WebSocket Live Feed Client for CP Plus / Dahua cameras.

CP Plus web portals typically use one of:
  1. Dahua JSMPEG WebSocket (/videostream or /websocket)
  2. Dahua RPC2 WebSocket (/RPC2_WebSocket) with binary H.264/JPEG frames
  3. MJPEG-over-WebSocket

This client:
  - Discovers the correct WebSocket endpoint automatically
  - Decodes the binary stream (JPEG frames or raw H.264 via jsmpeg)
  - Displays frames using OpenCV
  - Can save to MP4 or individual frames

Usage:
    python3 websocket_client.py
    python3 websocket_client.py --port 8080
    python3 websocket_client.py --ws ws://223.230.3.31/videostream
    python3 websocket_client.py --save recording.mp4
"""

import asyncio
import argparse
import base64
import hashlib
import json
import random
import struct
import ssl
import sys
import time
import threading

import cv2
import numpy as np
import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from config import CAMERA_IP, CAMERA_USER, CAMERA_PASS

# ──────────────────────────────────────────────────────────────────────────────
# Dahua binary WebSocket frame header magic bytes
# ──────────────────────────────────────────────────────────────────────────────
DAHUA_MAGIC_HEAD = b"\xff\x00\x00\x00"
DAHUA_MAGIC_DATA = b"\x00\x00\x00\x00"

# JSMPEG stream header
JSMPEG_MAGIC = b"jsmp"


class FrameDisplay:
    """Thread-safe frame display using OpenCV."""

    def __init__(self, title: str = "CP Plus Live Feed", save_path: str = None):
        self.title = title
        self.latest_frame = None
        self.lock = threading.Lock()
        self.running = True
        self.frame_count = 0
        self.start_time = time.time()
        self.writer = None
        self.save_path = save_path

    def push_frame(self, frame: np.ndarray):
        with self.lock:
            self.latest_frame = frame
            self.frame_count += 1

    def run(self):
        print("Display window opened. Press 'q' to quit, 's' for snapshot.")
        while self.running:
            with self.lock:
                frame = self.latest_frame

            if frame is not None:
                elapsed = time.time() - self.start_time
                fps = self.frame_count / elapsed if elapsed > 0 else 0

                disp = frame.copy()
                cv2.putText(disp, f"FPS: {fps:.1f}  Frames: {self.frame_count}",
                            (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                cv2.putText(disp, time.strftime("%Y-%m-%d %H:%M:%S"),
                            (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 2)

                if self.writer is None and self.save_path:
                    h, w = disp.shape[:2]
                    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                    self.writer = cv2.VideoWriter(self.save_path, fourcc, 25.0, (w, h))
                    print(f"Recording to {self.save_path}")

                if self.writer:
                    self.writer.write(disp)

                cv2.imshow(self.title, disp)

            key = cv2.waitKey(30) & 0xFF
            if key == ord("q"):
                self.running = False
            elif key == ord("s"):
                if frame is not None:
                    fn = f"snapshot_{time.strftime('%Y%m%d_%H%M%S')}.png"
                    cv2.imwrite(fn, frame)
                    print(f"Snapshot: {fn}")

        if self.writer:
            self.writer.release()
        cv2.destroyAllWindows()


# ──────────────────────────────────────────────────────────────────────────────
# Frame decoders
# ──────────────────────────────────────────────────────────────────────────────

def decode_jpeg_frame(data: bytes) -> np.ndarray | None:
    """Decode a raw JPEG byte blob."""
    arr = np.frombuffer(data, dtype=np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    return frame


def find_jpeg_in_blob(data: bytes) -> np.ndarray | None:
    """Search for a JPEG inside a binary blob (handles Dahua framing)."""
    start = data.find(b"\xff\xd8")
    end = data.rfind(b"\xff\xd9")
    if start != -1 and end != -1 and end > start:
        return decode_jpeg_frame(data[start: end + 2])
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Dahua RPC2 WebSocket authentication
# ──────────────────────────────────────────────────────────────────────────────

def md5_hex(s: str) -> str:
    return hashlib.md5(s.encode()).hexdigest().upper()


async def dahua_ws_login(ws) -> bool:
    """Perform Dahua WebSocket login handshake."""
    # Step 1: request challenge
    login_req = json.dumps({
        "method": "global.login",
        "params": {
            "userName": CAMERA_USER,
            "password": "",
            "clientType": "Web3.0",
            "loginType": "Direct",
            "authorityType": "Default",
        },
        "id": 1,
        "session": 0,
    })
    await ws.send(login_req)
    raw = await asyncio.wait_for(ws.recv(), timeout=5)
    resp = json.loads(raw)
    print(f"  Login challenge: {resp}")

    if "params" not in resp:
        return False

    params = resp["params"]
    realm = params.get("realm", "")
    random_str = params.get("random", "")
    session = resp.get("session", 0)

    # Step 2: compute hash
    pass1 = md5_hex(f"{CAMERA_USER}:{realm}:{CAMERA_PASS}")
    pass2 = md5_hex(f"{CAMERA_USER}:{random_str}:{pass1}")

    auth_req = json.dumps({
        "method": "global.login",
        "params": {
            "userName": CAMERA_USER,
            "password": pass2,
            "clientType": "Web3.0",
            "loginType": "Direct",
            "authorityType": "Default",
        },
        "id": 2,
        "session": session,
    })
    await ws.send(auth_req)
    raw = await asyncio.wait_for(ws.recv(), timeout=5)
    resp = json.loads(raw)
    print(f"  Auth response: {resp}")

    return resp.get("result", False)


async def dahua_start_monitor(ws, session, channel: int = 1):
    """Send Dahua real-time monitor start request."""
    req = json.dumps({
        "method": "monitor.startMoniton",
        "params": {
            "object": {
                "Channel": channel - 1,
                "StreamType": 0,
                "TransCodec": 0,
            }
        },
        "id": 3,
        "session": session,
    })
    await ws.send(req)
    raw = await asyncio.wait_for(ws.recv(), timeout=5)
    print(f"  Monitor start: {raw[:200]}")


# ──────────────────────────────────────────────────────────────────────────────
# WebSocket stream handlers
# ──────────────────────────────────────────────────────────────────────────────

async def handle_binary_stream(ws, display: FrameDisplay):
    """Generic binary WebSocket stream — try JPEG extraction from each message."""
    print("  Receiving binary frames...")
    async for message in ws:
        if isinstance(message, bytes):
            frame = find_jpeg_in_blob(message)
            if frame is not None:
                display.push_frame(frame)
        if not display.running:
            break


async def connect_dahua_rpc_ws(url: str, display: FrameDisplay, channel: int = 1):
    """Connect using Dahua RPC2 WebSocket protocol."""
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    extra = {"ssl": ssl_ctx} if url.startswith("wss") else {}

    headers = {
        "Authorization": "Basic " + base64.b64encode(
            f"{CAMERA_USER}:{CAMERA_PASS}".encode()).decode(),
        "Origin": f"http://{CAMERA_IP}",
    }

    async with websockets.connect(url, additional_headers=headers,
                                   subprotocols=["dcp.ip.dahua.com"],
                                   **extra) as ws:
        print(f"  Connected to Dahua RPC WS: {url}")
        logged_in = await dahua_ws_login(ws)
        if not logged_in:
            print("  Login failed — trying to receive stream anyway...")
        await handle_binary_stream(ws, display)


async def connect_generic_ws(url: str, display: FrameDisplay):
    """Connect to a generic WebSocket stream endpoint."""
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    extra = {"ssl": ssl_ctx} if url.startswith("wss") else {}

    credentials = base64.b64encode(f"{CAMERA_USER}:{CAMERA_PASS}".encode()).decode()
    headers = {
        "Authorization": f"Basic {credentials}",
        "Origin": f"http://{CAMERA_IP}",
    }

    async with websockets.connect(url, additional_headers=headers, **extra) as ws:
        print(f"  Connected: {url}")
        await handle_binary_stream(ws, display)


async def probe_ws_endpoints(display: FrameDisplay, port: int = 80, channel: int = 1):
    """Try each known WebSocket endpoint until one works."""
    scheme = "wss" if port in (443, 8443) else "ws"
    port_str = "" if port in (80, 443) else f":{port}"

    endpoints = [
        f"{scheme}://{CAMERA_IP}{port_str}/RPC2_WebSocket",
        f"{scheme}://{CAMERA_IP}{port_str}/websocket",
        f"{scheme}://{CAMERA_IP}{port_str}/videostream",
        f"{scheme}://{CAMERA_IP}{port_str}/live/ch{channel:02d}",
        f"{scheme}://{CAMERA_IP}{port_str}/ws",
        f"{scheme}://{CAMERA_IP}{port_str}/stream",
    ]

    for url in endpoints:
        try:
            print(f"\nTrying WS endpoint: {url}")
            await asyncio.wait_for(connect_generic_ws(url, display), timeout=30)
            return  # success
        except asyncio.TimeoutError:
            print(f"  Timeout")
        except (ConnectionClosed, WebSocketException, OSError) as e:
            print(f"  Failed: {e}")
        except Exception as e:
            print(f"  Error: {e}")

    print("\nNo working WebSocket endpoint found.")
    print("Hint: Run probe.py first, or check the browser DevTools (F12 → Network → WS)")
    display.running = False


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="CP Plus WebSocket Live Feed")
    parser.add_argument("--ws", help="WebSocket URL (skip auto-detect)")
    parser.add_argument("--port", type=int, default=80, help="HTTP port (default 80)")
    parser.add_argument("--channel", type=int, default=1, help="Camera channel")
    parser.add_argument("--save", metavar="FILE", help="Save to MP4 file")
    args = parser.parse_args()

    print("=" * 55)
    print("  CP Plus WebSocket Live Feed")
    print(f"  Camera: {CAMERA_IP}  Port: {args.port}  Channel: {args.channel}")
    print("=" * 55)

    display = FrameDisplay(save_path=args.save)
    display_thread = threading.Thread(target=display.run, daemon=True)
    display_thread.start()

    async def run():
        if args.ws:
            await connect_generic_ws(args.ws, display)
        else:
            await probe_ws_endpoints(display, port=args.port, channel=args.channel)

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        display.running = False
        display_thread.join(timeout=3)


if __name__ == "__main__":
    main()
