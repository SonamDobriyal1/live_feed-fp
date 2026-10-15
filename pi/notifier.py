"""
Alert notifier: optional email + Supabase detection logging.

Push notifications are sent by the web dashboard when the Pi POSTs a
detection to PORTAL_URL. This module no longer sends SMS.

Configure in .env:
  SUPABASE_LOGGING=true
  SUPABASE_URL=https://xxxx.supabase.co
  SUPABASE_SERVICE_ROLE_KEY=eyJ...
  EMAIL_ENABLED=true   (optional SMTP)

On violence detection notify() will:
  1. Insert a row into Supabase violence_alerts (if SUPABASE_LOGGING=true)
  2. Send email via SMTP (if EMAIL_ENABLED=true)
"""

from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from datetime import datetime, timezone
from typing import Any

from config import (
    EMAIL_BODY,
    EMAIL_ENABLED,
    EMAIL_FROM,
    EMAIL_SUBJECT,
    EMAIL_TO,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USER,
    parse_email_recipients,
    SUPABASE_ANON_KEY,
    SUPABASE_LOGGING,
    SUPABASE_SERVICE_ROLE_KEY,
    SUPABASE_URL,
)


@dataclass
class AlertEvent:
    detected_at: datetime
    confidence: float
    label: str
    camera_ip: str
    channel: int = 1
    snapshot_path: str | None = None
    clip_path: str | None = None
    snapshot_url: str | None = None
    cloudinary_public_id: str | None = None

    def message_text(self) -> str:
        when = self.detected_at.astimezone().strftime("%d %b %Y, %I:%M:%S %p")
        return (
            "Possible Violence Detected\n\n"
            f"Time: {when}\n"
            f"Confidence: {self.confidence:.1%}\n"
            f"Camera: {self.camera_ip} (ch {self.channel})\n"
            f"Label: {self.label}\n\n"
            "Please verify on the live feed."
        )

    def to_row(self) -> dict[str, Any]:
        return {
            "detected_at": self.detected_at.astimezone(timezone.utc).isoformat(),
            "camera_ip": self.camera_ip,
            "channel": self.channel,
            "confidence": float(self.confidence),
            "label": self.label,
            "snapshot_path": self.snapshot_path,
            "clip_path": self.clip_path,
            "snapshot_url": self.snapshot_url,
            "cloudinary_public_id": self.cloudinary_public_id,
            "message": self.message_text(),
            "whatsapp_status": "pending",
        }


@dataclass
class EmailSendResult:
    ok: bool = False
    error: str | None = None


class AlertNotifier:
    """Log every detection to Supabase; optionally email staff."""

    def __init__(
        self,
        supabase_logging: bool | None = None,
        email_enabled: bool | None = None,
    ):
        self.email_enabled = email_enabled if email_enabled is not None else EMAIL_ENABLED
        self.email_recipients = parse_email_recipients(EMAIL_TO)
        self.supabase_logging = (
            supabase_logging if supabase_logging is not None else SUPABASE_LOGGING
        )
        self._supabase = None

        self._init_supabase()
        self._init_email()

    @property
    def enabled(self) -> bool:
        """True if email or Supabase logging is active."""
        return self.email_enabled or self._supabase is not None

    def _init_email(self) -> None:
        if not self.email_enabled:
            return
        if not (SMTP_USER and SMTP_PASSWORD):
            print("  [notifier] EMAIL_ENABLED=true but SMTP_USER/SMTP_PASSWORD missing — email disabled")
            self.email_enabled = False
            return
        if not self.email_recipients:
            print("  [notifier] EMAIL_TO empty — email disabled")
            self.email_enabled = False
            return
        print(f"  [notifier] Email ready → {', '.join(self.email_recipients)}")

    def send_email(self, event: AlertEvent | None = None) -> EmailSendResult:
        """Send the alert email via SMTP. Returns a result; never raises."""
        if not self.email_enabled:
            return EmailSendResult(ok=False, error="email disabled")
        try:
            msg = EmailMessage()
            msg["Subject"] = EMAIL_SUBJECT
            msg["From"] = EMAIL_FROM
            msg["To"] = ", ".join(self.email_recipients)
            when_dt = event.detected_at if event else datetime.now(timezone.utc)
            when = when_dt.astimezone().strftime("%d %b %Y, %I:%M:%S %p")
            msg.set_content(f"{EMAIL_BODY}\n\nDate & Time: {when}")

            context = ssl.create_default_context()
            if SMTP_PORT == 465:
                with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context, timeout=20) as s:
                    s.login(SMTP_USER, SMTP_PASSWORD)
                    s.send_message(msg)
            else:
                with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as s:
                    s.starttls(context=context)
                    s.login(SMTP_USER, SMTP_PASSWORD)
                    s.send_message(msg)
            print(f"  [notifier] Email sent → {', '.join(self.email_recipients)}")
            return EmailSendResult(ok=True)
        except Exception as e:
            print(f"  [notifier] Email failed: {e}")
            return EmailSendResult(ok=False, error=str(e))

    def _init_supabase(self) -> None:
        if not self.supabase_logging:
            return
        if not SUPABASE_URL:
            print("  [notifier] SUPABASE_LOGGING=true but SUPABASE_URL missing")
            return

        key = SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY
        if not key:
            print("  [notifier] SUPABASE_LOGGING=true but no Supabase key in .env")
            return

        try:
            from supabase import create_client
            self._supabase = create_client(SUPABASE_URL, key)
            print(f"  [notifier] Supabase logging → {SUPABASE_URL}")
        except Exception as e:
            print(f"  [notifier] Supabase init failed: {e}")

    def log_supabase(self, event: AlertEvent, **_ignored: Any) -> dict | None:
        if self._supabase is None:
            return None

        row = event.to_row()
        row["whatsapp_status"] = "logged"
        row["whatsapp_error"] = None
        extra_keys = ("snapshot_url", "cloudinary_public_id")
        attempts = [row, {k: v for k, v in row.items() if k not in extra_keys}]

        try:
            last_err = None
            for payload in attempts:
                try:
                    resp = self._supabase.table("violence_alerts").insert(payload).execute()
                    inserted = (resp.data or [None])[0]
                    print(f"  [notifier] Logged to Supabase id={inserted.get('id') if inserted else '?'}")
                    return inserted
                except Exception as e:
                    last_err = e
            print(f"  [notifier] Supabase insert failed: {last_err}")
            return None
        except Exception as e:
            print(f"  [notifier] Supabase insert failed: {e}")
            return None

    def notify(self, event: AlertEvent) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "reason": "disabled"}

        email_result: EmailSendResult | None = None
        if self.email_enabled:
            email_result = self.send_email(event)

        supabase_row = self.log_supabase(event)
        email_ok = bool(email_result and email_result.ok)
        ok = bool(supabase_row) or email_ok
        first_error = email_result.error if email_result and email_result.error else None

        return {
            "ok": ok,
            "email": (
                {"ok": email_result.ok, "error": email_result.error} if email_result else None
            ),
            "alert": supabase_row,
            "reason": None if ok else (first_error or "notify_failed"),
        }


SupabaseWhatsAppNotifier = AlertNotifier


def build_notifier_from_env() -> AlertNotifier | None:
    if not SUPABASE_LOGGING and not EMAIL_ENABLED:
        return None
    notifier = AlertNotifier()
    return notifier if notifier.enabled else None
