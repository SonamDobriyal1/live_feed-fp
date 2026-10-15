"""
Probe the CP Plus camera to discover available streaming endpoints.
Run this first to see what services are open.
"""

import socket
import ssl
import urllib.request
import urllib.error
import base64
import json
import sys
from config import CAMERA_IP, CAMERA_USER, CAMERA_PASS

PORTS_TO_SCAN = [80, 443, 554, 8080, 8443, 37777, 8000, 8888, 1935]


def check_port(ip: str, port: int, timeout: float = 2.0) -> bool:
    try:
        sock = socket.create_connection((ip, port), timeout=timeout)
        sock.close()
        return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def http_get(url: str, auth: tuple = None, verify_ssl: bool = False) -> tuple[int, str]:
    try:
        ctx = ssl.create_default_context()
        if not verify_ssl:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

        req = urllib.request.Request(url)
        if auth:
            credentials = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
            req.add_header("Authorization", f"Basic {credentials}")

        with urllib.request.urlopen(req, context=ctx, timeout=5) as resp:
            body = resp.read(4096).decode("utf-8", errors="replace")
            return resp.status, body
    except urllib.error.HTTPError as e:
        try:
            body = e.read(2048).decode("utf-8", errors="replace")
        except Exception:
            body = str(e)
        return e.code, body
    except Exception as e:
        return 0, str(e)


def probe_dahua_rpc(ip: str) -> dict | None:
    """Try Dahua JSON-RPC login to detect firmware."""
    import urllib.parse

    payload = json.dumps({
        "method": "global.login",
        "params": {
            "userName": CAMERA_USER,
            "password": "",
            "clientType": "Web3.0",
            "loginType": "Direct",
            "authorityType": "Default",
        },
        "id": 1,
    }).encode()

    for scheme in ("http", "https"):
        url = f"{scheme}://{ip}/RPC2_Login"
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            req = urllib.request.Request(url, data=payload,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, context=ctx, timeout=5) as resp:
                data = json.loads(resp.read())
                return {"url": url, "response": data}
        except Exception:
            pass
    return None


def probe_mjpeg(ip: str) -> list[str]:
    """Check for MJPEG HTTP streams."""
    working = []
    paths = [
        "/cgi-bin/mjpg/video.cgi?channel=1&subtype=1",
        "/mjpg/video.mjpg",
        "/video/mjpg.cgi",
        "/cgi-bin/CGIStream.cgi?cmd=GetMJStream&channel=1",
    ]
    for scheme in ("http", "https"):
        for path in paths:
            url = f"{scheme}://{ip}{path}"
            code, _ = http_get(url, auth=(CAMERA_USER, CAMERA_PASS))
            if code in (200, 206):
                working.append(url)
    return working


def main():
    print("=" * 60)
    print(f"  CP Plus Camera Probe: {CAMERA_IP}")
    print("=" * 60)

    # 1. Port scan
    print("\n[1] Scanning common ports...")
    open_ports = []
    for port in PORTS_TO_SCAN:
        is_open = check_port(CAMERA_IP, port)
        status = "OPEN  ✓" if is_open else "closed"
        print(f"    Port {port:5d}: {status}")
        if is_open:
            open_ports.append(port)

    if not open_ports:
        print("\n  ERROR: No ports reachable. Check network/VPN connectivity.")
        sys.exit(1)

    # 2. HTTP fingerprint
    print("\n[2] HTTP fingerprinting...")
    for port in [p for p in open_ports if p in (80, 8080, 443, 8443)]:
        scheme = "https" if port in (443, 8443) else "http"
        url = f"{scheme}://{CAMERA_IP}:{port}/" if port not in (80, 443) else f"{scheme}://{CAMERA_IP}/"
        code, body = http_get(url)
        print(f"    {url}: HTTP {code}")
        if "dahua" in body.lower() or "cp plus" in body.lower() or "dss" in body.lower():
            print("    → Dahua/CP Plus firmware detected!")
        code_auth, _ = http_get(url, auth=(CAMERA_USER, CAMERA_PASS))
        if code_auth == 200 and code_auth != code:
            print(f"    → Auth works! HTTP {code_auth} with credentials")

    # 3. Dahua RPC detection
    print("\n[3] Probing Dahua JSON-RPC endpoint...")
    result = probe_dahua_rpc(CAMERA_IP)
    if result:
        print(f"    Endpoint: {result['url']}")
        print(f"    Response: {json.dumps(result['response'], indent=6)}")
    else:
        print("    Not reachable or non-Dahua device.")

    # 4. MJPEG streams
    print("\n[4] Checking MJPEG HTTP streams...")
    mjpeg_urls = probe_mjpeg(CAMERA_IP)
    if mjpeg_urls:
        for url in mjpeg_urls:
            print(f"    WORKING: {url}")
    else:
        print("    No MJPEG streams found via HTTP.")

    # 5. Summary
    print("\n[5] RTSP stream URLs to try:")
    from config import RTSP_URLS
    for url in RTSP_URLS[:3]:
        print(f"    {url}")

    print("\n[6] Next steps:")
    if 554 in open_ports:
        print("    ✓ RTSP port 554 is open → run: python3 rtsp_viewer.py")
    if open_ports:
        print("    ✓ Web port open → run: python3 websocket_client.py")
    print("    ✓ Auto-detect mode → run: python3 live_feed.py")
    print()


if __name__ == "__main__":
    main()
