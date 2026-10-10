"""
Alert notifier: Twilio SMS + Supabase detection logging.

Configure in .env:
  SMS_TO=+919354501373,+919876543210
  SUPABASE_LOGGING=true
  SUPABASE_URL=https://xxxx.supabase.co
  SUPABASE_SERVICE_ROLE_KEY=eyJ...

On violence detection notify() will:
  1. Insert a row into Supabase violence_alerts (if SUPABASE_LOGGING=true)
  2. Send SMS to all numbers in SMS_TO (if SMS_ENABLED=true)
  3. Send email via SMTP (if EMAIL_ENABLED=true) — by default only when SMS
     is off or fails (EMAIL_MODE=fallback); EMAIL_MODE=always sends both.
"""

from __future__ import annotations

import json
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
    EMAIL_MODE,
    EMAIL_SUBJECT,
    EMAIL_TO,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USER,
    parse_email_recipients,
    SMS_ENABLED,
    SMS_TO,
    SUPABASE_ANON_KEY,
    SUPABASE_LOGGING,
    SUPABASE_SERVICE_ROLE_KEY,
    SUPABASE_URL,
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_CONTENT_SID,
    TWILIO_SMS_FROM,
    TWILIO_SMS_MODE,
    TWILIO_SMS_TEMPLATE,
    TWILIO_SMS_USE_TEMPLATE,
    parse_sms_recipients,
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
class SmsSendResult:
    to: str
    sid: str | None = None
    ok: bool = False
    error: str | None = None


@dataclass
class EmailSendResult:
    ok: bool = False
    error: str | None = None


class AlertNotifier:
    """Send SMS via Twilio (email as optional fallback); log every detection to Supabase."""

    def __init__(
        self,
        sms_enabled: bool | None = None,
        recipients: list[str] | None = None,
        supabase_logging: bool | None = None,
        email_enabled: bool | None = None,
    ):
        self.email_enabled = email_enabled if email_enabled is not None else EMAIL_ENABLED
        self.email_recipients = parse_email_recipients(EMAIL_TO)
        self.sms_enabled = sms_enabled if sms_enabled is not None else SMS_ENABLED
        self.supabase_logging = (
            supabase_logging if supabase_logging is not None else SUPABASE_LOGGING
        )
        self.recipients = recipients if recipients is not None else parse_sms_recipients(SMS_TO)
        self._twilio = None
        self._supabase = None

        self._init_supabase()
        self._init_sms()
        self._init_email()

    @property
    def enabled(self) -> bool:
        """True if SMS, email or Supabase logging is active."""
        return self.sms_enabled or self.email_enabled or self._supabase is not None

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
        mode = "every alert" if EMAIL_MODE == "always" else "fallback when SMS fails"
        print(f"  [notifier] Email ready → {', '.join(self.email_recipients)} | {mode}")

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

    def _init_sms(self) -> None:
        if not self.sms_enabled:
            print("  [notifier] SMS disabled (SMS_ENABLED=false)")
            return

        if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_SMS_FROM):
            print("  [notifier] Twilio credentials missing — SMS disabled")
            self.sms_enabled = False
            return

        if not self.recipients:
            print("  [notifier] SMS_TO empty — SMS disabled")
            self.sms_enabled = False
            return

        try:
            from twilio.rest import Client
            self._twilio = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
            if TWILIO_SMS_MODE == "template" or (
                TWILIO_SMS_USE_TEMPLATE and not TWILIO_CONTENT_SID
            ):
                print(
                    f"  [notifier] SMS ready → {len(self.recipients)} recipient(s) "
                    f"| template: {TWILIO_SMS_TEMPLATE}"
                )
            elif TWILIO_CONTENT_SID and TWILIO_SMS_MODE == "content":
                print(
                    f"  [notifier] SMS ready → {len(self.recipients)} recipient(s) "
                    f"| ContentSid {TWILIO_CONTENT_SID[:8]}..."
                )
            elif TWILIO_CONTENT_SID:
                print(
                    f"  [notifier] SMS ready → {len(self.recipients)} recipient(s) "
                    f"| auto (ContentSid → fallback {TWILIO_SMS_TEMPLATE})"
                )
            elif TWILIO_SMS_USE_TEMPLATE:
                print(
                    f"  [notifier] SMS ready → {len(self.recipients)} recipient(s) "
                    f"| template: {TWILIO_SMS_TEMPLATE}"
                )
            else:
                print(f"  [notifier] SMS ready → {len(self.recipients)} recipient(s) | free-form body")
        except Exception as e:
            print(f"  [notifier] Twilio init failed: {e}")
            self.sms_enabled = False

    def _content_variables(self, event: AlertEvent) -> dict[str, str]:
        """Map alert fields to Content Template variables {{1}}, {{2}}, ..."""
        when = event.detected_at.astimezone().strftime("%d %b %Y, %I:%M:%S %p")
        return {
            "1": when,
            "2": f"{event.confidence:.1%}",
            "3": f"{event.camera_ip} (ch {event.channel})",
            "4": event.label,
        }

    def _try_create(self, to: str, kwargs: dict[str, Any]) -> SmsSendResult:
        msg = self._twilio.messages.create(**kwargs)
        return SmsSendResult(to=to, sid=msg.sid, ok=True)

    def _send_one_sms(self, to: str, event: AlertEvent) -> SmsSendResult:
        base = {"from_": TWILIO_SMS_FROM, "to": to}
        errors: list[str] = []

        def attempt(label: str, extra: dict[str, Any]) -> SmsSendResult | None:
            try:
                result = self._try_create(to, {**base, **extra})
                if label != "template":
                    print(f"  [notifier] SMS sent via {label}")
                return result
            except Exception as e:
                err = str(e).strip()
                errors.append(f"{label}: {err}")
                return None

        mode = TWILIO_SMS_MODE

        # India trial template: Body must be the template name string
        if mode == "template" or (
            mode == "auto"
            and TWILIO_SMS_USE_TEMPLATE
            and TWILIO_SMS_TEMPLATE == "sms_internal_alerts"
        ):
            r = attempt("template", {"body": TWILIO_SMS_TEMPLATE})
            if r:
                return r
            raise RuntimeError(errors[-1] if errors else "template send failed")

        if mode == "content" or (mode == "auto" and TWILIO_CONTENT_SID):
            # Try Content API — static template first (no variables)
            r = attempt("content", {"content_sid": TWILIO_CONTENT_SID})
            if r:
                return r
            # Then with variables {{1}}..{{4}}
            r = attempt(
                "content+vars",
                {
                    "content_sid": TWILIO_CONTENT_SID,
                    "content_variables": json.dumps(self._content_variables(event)),
                },
            )
            if r:
                return r

        if TWILIO_SMS_USE_TEMPLATE:
            r = attempt("template", {"body": TWILIO_SMS_TEMPLATE})
            if r:
                return r

        r = attempt("freeform", {"body": event.message_text()})
        if r:
            return r

        raise RuntimeError("; ".join(errors) if errors else "SMS send failed")

    def send_sms(self, event: AlertEvent) -> list[SmsSendResult]:
        if not self.sms_enabled or self._twilio is None:
            return []

        results: list[SmsSendResult] = []
        for to in self.recipients:
            try:
                result = self._send_one_sms(to, event)
                print(f"  [notifier] SMS sent → {to}  sid={result.sid}")
                results.append(result)
            except Exception as e:
                print(f"  [notifier] SMS failed → {to}: {e}")
                results.append(SmsSendResult(to=to, ok=False, error=str(e)))

        return results

    def log_supabase(
        self,
        event: AlertEvent,
        sms_ok: bool | None = None,
        sms_error: str | None = None,
    ) -> dict | None:
        if self._supabase is None:
            return None

        row = event.to_row()
        if sms_ok is None:
            row["whatsapp_status"] = "logged"
        else:
            row["whatsapp_status"] = "sent" if sms_ok else "failed"
        row["whatsapp_error"] = sms_error
        # Keep insert compatible with older schemas that lack Cloudinary columns.
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

        sms_results = self.send_sms(event) if self.sms_enabled else []
        any_sms_ok = any(r.ok for r in sms_results) if sms_results else None
        first_error = next((r.error for r in sms_results if r.error), None)

        # Email: always (if EMAIL_MODE=always) or only when SMS is off / all failed.
        email_result: EmailSendResult | None = None
        if self.email_enabled:
            sms_delivered = bool(sms_results) and any_sms_ok
            if EMAIL_MODE == "always" or not sms_delivered:
                if sms_results and not sms_delivered:
                    print("  [notifier] SMS failed — falling back to email")
                email_result = self.send_email(event)

        supabase_row = self.log_supabase(
            event,
            sms_ok=any_sms_ok if sms_results else None,
            sms_error=first_error,
        )

        email_ok = bool(email_result and email_result.ok)
        ok = bool(supabase_row) or any(r.ok for r in sms_results) or email_ok
        if not first_error and email_result and email_result.error:
            first_error = email_result.error

        return {
            "ok": ok,
            "sms": [{"to": r.to, "sid": r.sid, "ok": r.ok, "error": r.error} for r in sms_results],
            "email": (
                {"ok": email_result.ok, "error": email_result.error} if email_result else None
            ),
            "alert": supabase_row,
            "reason": None if ok else (first_error or "notify_failed"),
        }


SupabaseWhatsAppNotifier = AlertNotifier


def build_notifier_from_env() -> AlertNotifier | None:
    if not SMS_ENABLED and not SUPABASE_LOGGING and not EMAIL_ENABLED:
        return None
    notifier = AlertNotifier()
    return notifier if notifier.enabled else None
