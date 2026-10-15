"""Web Push helpers: VAPID keys and incident alerts to subscribed browsers."""

from __future__ import annotations

import json
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

from config import DATA_DIR, DAYCARE_TZ, VAPID_MAILTO, VAPID_PRIVATE_KEY, VAPID_PUBLIC_KEY

import db as store

_VAPID_PATH = DATA_DIR / "vapid.json"
_keys_lock = threading.Lock()
_cached_keys: tuple[str, str] | None = None


def _b64url(raw: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _generate_vapid_keys() -> tuple[str, str]:
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization

    private_key = ec.generate_private_key(ec.SECP256R1())
    priv_bytes = private_key.private_numbers().private_value.to_bytes(32, "big")
    pub_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    return _b64url(pub_bytes), _b64url(priv_bytes)


def vapid_keys() -> tuple[str, str]:
    """Return (public, private) URL-safe VAPID keys, creating them once if needed."""
    global _cached_keys
    if _cached_keys:
        return _cached_keys
    with _keys_lock:
        if _cached_keys:
            return _cached_keys
        if VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY:
            _cached_keys = (VAPID_PUBLIC_KEY.strip(), VAPID_PRIVATE_KEY.strip())
            return _cached_keys
        if _VAPID_PATH.exists():
            data = json.loads(_VAPID_PATH.read_text())
            _cached_keys = (data["publicKey"], data["privateKey"])
            return _cached_keys
        public, private = _generate_vapid_keys()
        _VAPID_PATH.parent.mkdir(parents=True, exist_ok=True)
        _VAPID_PATH.write_text(json.dumps({"publicKey": public, "privateKey": private}, indent=2))
        print(f"  [push] generated VAPID keys → {_VAPID_PATH}")
        _cached_keys = (public, private)
        return _cached_keys


def public_key() -> str:
    return vapid_keys()[0]


def format_when(detected_at: datetime | str | None = None) -> str:
    tz = ZoneInfo(DAYCARE_TZ)
    if isinstance(detected_at, datetime):
        dt = detected_at
    elif detected_at:
        try:
            dt = datetime.fromisoformat(str(detected_at).replace("Z", "+00:00"))
        except ValueError:
            dt = datetime.now(tz)
    else:
        dt = datetime.now(tz)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    local = dt.astimezone(tz)
    hour = local.strftime("%I").lstrip("0") or "0"
    return f"{local.day} {local.strftime('%b %Y')}, {hour}:{local.strftime('%M %p')}"


def incident_body(detected_at: datetime | str | None, daycare_name: str) -> str:
    return (
        "Unusual/ safety incident detected at "
        f"{format_when(detected_at)} at {daycare_name}"
    )


def send_to_camera(
    camera_ip: str,
    title: str,
    body: str,
    url: str = "/dashboard",
    tag: str = "safety-incident",
) -> dict:
    """Send a Web Push to every browser subscribed for this daycare camera."""
    _, private = vapid_keys()
    rows = store.list_push_subscriptions(camera_ip)
    if not rows:
        print(f"  [push] {camera_ip}: no subscribed browsers")
        return {"ok": True, "sent": 0, "removed": 0}

    from pywebpush import WebPushException, webpush

    payload = json.dumps({"title": title, "body": body, "url": url, "tag": tag})
    claims = {"sub": VAPID_MAILTO}
    sent = 0
    removed = 0
    errors: list[str] = []

    for row in rows:
        subscription = {
            "endpoint": row["endpoint"],
            "keys": {"p256dh": row["p256dh"], "auth": row["auth"]},
        }
        try:
            webpush(
                subscription_info=subscription,
                data=payload,
                vapid_private_key=private,
                vapid_claims=claims,
            )
            sent += 1
        except WebPushException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (404, 410):
                store.delete_push_subscription(row["endpoint"])
                removed += 1
            else:
                errors.append(str(exc))
                print(f"  [push] send failed: {exc}")
        except Exception as exc:
            errors.append(str(exc))
            print(f"  [push] send failed: {exc}")

    print(f"  [push] {camera_ip}: sent={sent} stale_removed={removed}")
    return {
        "ok": sent > 0 or not errors,
        "sent": sent,
        "removed": removed,
        "error": errors[0] if errors and sent == 0 else None,
    }


def send_incident_push(
    camera_ip: str,
    daycare_name: str,
    detected_at: datetime | str | None,
) -> dict:
    return send_to_camera(
        camera_ip,
        title="Safety incident",
        body=incident_body(detected_at, daycare_name),
        url="/dashboard",
        tag=f"incident-{camera_ip}",
    )


def send_incident_push_async(
    camera_ip: str,
    daycare_name: str,
    detected_at: datetime | str | None,
) -> None:
    threading.Thread(
        target=send_incident_push,
        args=(camera_ip, daycare_name, detected_at),
        daemon=True,
        name="push-incident",
    ).start()
