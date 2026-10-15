"""Pi-only: upload snapshots to Supabase Storage and POST metadata to the web dashboard."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import urljoin

import cv2
import numpy as np

from config import (
    CAMERA_IP,
    DAYCARE_NAME,
    PORTAL_INGEST_KEY,
    PORTAL_URL,
    SUPABASE_ANON_KEY,
    SUPABASE_SERVICE_ROLE_KEY,
    SUPABASE_STORAGE_BUCKET,
    SUPABASE_URL,
)


def _folder_slug(camera_ip: str) -> str:
    return camera_ip.replace(".", "-").replace(":", "-")


def storage_configured() -> bool:
    return bool(SUPABASE_URL and (SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY))


def _storage_client():
    from supabase import create_client

    key = SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY
    return create_client(SUPABASE_URL, key)


def ensure_bucket(client) -> None:
    bucket = SUPABASE_STORAGE_BUCKET
    try:
        client.storage.get_bucket(bucket)
        return
    except Exception:
        pass
    client.storage.create_bucket(bucket, options={"public": True})


def upload_snapshot(
    frame_bgr: np.ndarray,
    detected_at: datetime,
    camera_ip: str = CAMERA_IP,
) -> dict[str, str]:
    if not storage_configured():
        raise RuntimeError("Supabase URL or key missing")

    ok, buf = cv2.imencode(".jpg", frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
    if not ok:
        raise RuntimeError("Failed to encode JPEG snapshot")

    stamp = detected_at.strftime("%Y%m%d_%H%M%S")
    object_path = f"{_folder_slug(camera_ip)}/alert_{stamp}.jpg"
    client = _storage_client()
    ensure_bucket(client)
    store = client.storage.from_(SUPABASE_STORAGE_BUCKET)
    store.upload(
        object_path,
        buf.tobytes(),
        file_options={"content-type": "image/jpeg", "upsert": "true"},
    )
    url = store.get_public_url(object_path)
    if isinstance(url, dict):
        url = url.get("publicUrl") or url.get("publicURL") or ""
    return {"public_id": object_path, "url": str(url).rstrip("?")}


def post_detection_to_web(payload: dict[str, Any], retries: int = 4) -> dict[str, Any] | None:
    if not PORTAL_URL or not PORTAL_INGEST_KEY:
        print("  [web] PORTAL_URL or PORTAL_INGEST_KEY missing — skip dashboard ingest")
        return None

    import json
    import time
    import urllib.error
    import urllib.request

    body = json.dumps(payload).encode("utf-8")
    url = urljoin(PORTAL_URL + "/", "api/detections")
    last_err = None
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Ingest-Key": PORTAL_INGEST_KEY,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {"ok": True}
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:300]
            print(f"  [web] ingest failed HTTP {e.code}: {detail}")
            return None
        except Exception as e:
            last_err = e
            wait = min(2 ** attempt, 8)
            print(f"  [web] ingest attempt {attempt}/{retries} failed: {e}")
            if attempt < retries:
                print(f"  [web] retrying in {wait}s — is `python3 app.py` running in web/?")
                time.sleep(wait)
    print(f"  [web] ingest gave up: {last_err}")
    return None


def publish_detection(
    frame_bgr: np.ndarray,
    detected_at: datetime,
    confidence: float,
    label: str,
    channel: int,
) -> dict[str, Any]:
    """Upload snapshot then notify the web service. Safe on a background thread."""
    out: dict[str, Any] = {"storage": None, "web": None}
    try:
        uploaded = upload_snapshot(frame_bgr, detected_at)
        out["storage"] = uploaded
        print(f"  [storage] Supabase → {uploaded['url']}")
    except Exception as e:
        print(f"  [storage] upload failed: {e}")
        uploaded = {"public_id": "", "url": ""}

    web = post_detection_to_web({
        "camera_ip": CAMERA_IP,
        "daycare_name": DAYCARE_NAME or CAMERA_IP,
        "detected_at": detected_at.isoformat(),
        "confidence": float(confidence),
        "label": label,
        "channel": channel,
        "snapshot_url": uploaded.get("url", ""),
        "cloudinary_public_id": uploaded.get("public_id", ""),
    })
    out["web"] = web
    if web:
        print(f"  [web] logged detection id={web.get('id', '?')}")
    return out
