#!/usr/bin/env python3
"""Send a one-off test SMS through Twilio using credentials from pi/.env.

Usage:
    python scripts/send_test_sms.py
    python scripts/send_test_sms.py --to +919354501373 --body "custom text"
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client

ENV_PATH = Path(__file__).resolve().parent.parent / "pi" / ".env"
DEFAULT_TO = "+919354501373"
DEFAULT_BODY = "Alert: Possible unsafe incident at daycare, please check"


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a test SMS via Twilio")
    parser.add_argument("--to", default=DEFAULT_TO)
    parser.add_argument("--body", default=DEFAULT_BODY)
    args = parser.parse_args()

    load_dotenv(ENV_PATH)
    sid = os.getenv("TWILIO_ACCOUNT_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    sender = os.getenv("TWILIO_SMS_FROM")
    if not (sid and token and sender):
        print(f"Missing TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_SMS_FROM in {ENV_PATH}")
        return 1

    client = Client(sid, token)
    try:
        msg = client.messages.create(from_=sender, to=args.to, body=args.body)
    except TwilioRestException as e:
        print(f"FAILED (HTTP {e.status}, code {e.code}): {e.msg}")
        print(f"More info: {e.uri}")
        return 1

    print(f"Queued: sid={msg.sid} status={msg.status} to={args.to}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
