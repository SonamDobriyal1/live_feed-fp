"""Shared RTSPS helpers — URL building, probe, and ffmpeg pipe."""

from __future__ import annotations

import shutil
import subprocess
import threading
from collections import deque

from config import CAMERA_IP, CAMERA_PASS, CAMERA_USER, RTSP_PORT


def scaled_even(width: int, height: int, max_width: int | None) -> tuple[int, int]:
    """Even dimensions; optionally downscale by width (keeps aspect ratio)."""
    if width <= 0 or height <= 0:
        return 2, 2
    if max_width and width > max_width:
        w = max(2, max_width - (max_width % 2))
        h = max(2, int(height * w / width))
        h -= h % 2
        return w, h
    w = max(2, width - (width % 2))
    h = max(2, height - (height % 2))
    return w, h

FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
FFPROBE = shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"

_tls_verify_cache: dict[str, bool] = {}


def _accepts_tls_verify(binary: str) -> bool:
    """Probe whether a binary actually accepts -tls_verify (help text lies on Debian ffmpeg)."""
    if binary not in _tls_verify_cache:
        try:
            r = subprocess.run(
                [binary, "-tls_verify", "0"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            text = (r.stderr + r.stdout).lower()
            _tls_verify_cache[binary] = (
                "option tls_verify not found" not in text
                and "unrecognized option" not in text
            )
        except Exception:
            _tls_verify_cache[binary] = False
    return _tls_verify_cache[binary]


def ffmpeg_input_opts() -> list[str]:
    """ffmpeg input flags. Never pass -tls_verify here — Debian/Render rejects it."""
    return ["-loglevel", "warning", "-rtsp_transport", "tcp"]


def ffprobe_input_opts() -> list[str]:
    opts = ["-v", "error"]
    if _accepts_tls_verify(FFPROBE):
        opts += ["-tls_verify", "0"]
    return opts


def build_rtsp_url(channel: int = 1, subtype: int = 0) -> str:
    """Build RTSPS URL. Password is kept literal — this camera rejects %24 for $."""
    return (
        f"rtsps://{CAMERA_USER}:{CAMERA_PASS}@{CAMERA_IP}:{RTSP_PORT}"
        f"/video/live?channel={channel}&subtype={subtype}"
    )


def mask_url(url: str) -> str:
    if not CAMERA_PASS:
        return url
    return url.replace(CAMERA_PASS, "****")


def probe_stream(url: str, timeout: int = 30) -> dict | None:
    """Return video stream metadata, or None if unreachable."""
    masked = mask_url(url)
    print(f"  Probing: {masked}")
    proc = subprocess.Popen(
        [
            FFPROBE,
            *ffprobe_input_opts(),
            "-select_streams", "v:0",
            "-show_entries", "stream=codec_name,width,height,r_frame_rate",
            "-of", "csv=p=0",
            url,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        print(f"  Camera did not answer within {timeout}s — will retry")
        return None
    if proc.returncode != 0:
        err = (stderr or stdout or "").strip()
        if err:
            print(f"  ffprobe error: {err[:400]}")
        return None
    r_stdout = stdout

    lines = [ln.strip() for ln in (r_stdout or "").strip().split("\n") if ln.strip()]
    if not lines:
        return None

    # Prefer the first line with valid video dimensions.
    for line in lines:
        parts = line.split(",")
        if len(parts) < 3:
            continue
        width = int(parts[1]) if parts[1].isdigit() else 0
        height = int(parts[2]) if parts[2].isdigit() else 0
        if width > 0 and height > 0:
            return {
                "codec": parts[0],
                "width": width,
                "height": height,
                "fps_str": parts[3] if len(parts) > 3 else "25/1",
            }

    print(f"  ffprobe returned no video dimensions: {lines!r}")
    return None


class _StderrTail:
    """Background reader that keeps the last N stderr lines from ffmpeg."""

    def __init__(self, proc: subprocess.Popen, max_lines: int = 20):
        self._lines: deque[str] = deque(maxlen=max_lines)
        self._proc = proc
        self._thread = threading.Thread(target=self._drain, daemon=True)
        self._thread.start()

    def _drain(self) -> None:
        if self._proc.stderr is None:
            return
        for raw in iter(self._proc.stderr.readline, b""):
            line = raw.decode(errors="replace").strip()
            if line:
                self._lines.append(line)

    def tail(self) -> str:
        return "\n".join(self._lines)


_logged_ffmpeg_opts = False


def open_ffmpeg_pipe(
    url: str,
    width: int,
    height: int,
    out_width: int | None = None,
    out_fps: float | None = None,
) -> tuple[subprocess.Popen, _StderrTail, int, int]:
    """Decode RTSPS to raw BGR. Optionally downscale and drop FPS (Pi-friendly)."""
    global _logged_ffmpeg_opts
    out_w, out_h = scaled_even(width, height, out_width)
    filters = [f"scale={out_w}:{out_h}:flags=fast_bilinear"]
    if out_fps and out_fps > 0:
        filters.append(f"fps={out_fps}")
    vf = ",".join(filters)

    input_opts = ffmpeg_input_opts()
    if not _logged_ffmpeg_opts:
        extra = f" vf={vf}"
        print(f"  ffmpeg args: {' '.join(input_opts)} -i <url>{extra}")
        _logged_ffmpeg_opts = True
    cmd = [
        FFMPEG,
        *input_opts,
        "-i", url,
        "-an",
        "-threads", "2",
        "-vf", vf,
        "-f", "rawvideo",
        "-pix_fmt", "bgr24",
        "-",
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=max(out_w * out_h * 3 * 4, 1_000_000),
    )
    return proc, _StderrTail(proc), out_w, out_h


def log_stream_failure(proc: subprocess.Popen, stderr_tail: _StderrTail, got: int, expected: int) -> None:
    code = proc.poll()
    detail = stderr_tail.tail()
    print(
        f"  Stream read failed: got {got} bytes, expected {expected}"
        + (f", ffmpeg exit={code}" if code is not None else ", ffmpeg still running")
    )
    if detail:
        print(f"  ffmpeg stderr (last lines):\n{detail}")
