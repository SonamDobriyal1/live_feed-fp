#!/usr/bin/env python3
"""Verify Supabase connection and violence_alerts table."""

from datetime import datetime, timezone

from config import SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_URL
from notifier import AlertEvent, AlertNotifier


def main() -> int:
    print("Supabase setup check")
    print(f"  URL: {SUPABASE_URL or '(missing)'}")

    if not SUPABASE_URL or not (SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY):
        print("\nERROR: Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in .env")
        return 1

    notifier = AlertNotifier(supabase_logging=True)
    if not notifier._supabase:
        print("\nERROR: Could not connect to Supabase")
        return 1

    event = AlertEvent(
        detected_at=datetime.now(timezone.utc),
        confidence=0.01,
        label="setup_test",
        camera_ip="test",
        channel=0,
        snapshot_path="setup_check",
    )
    row = notifier.log_supabase(event)

    if row:
        print("\nOK: violence_alerts table exists and insert works.")
        print(f"    Test row id: {row.get('id')}")
        return 0

    print("\nERROR: Insert failed — table probably missing.")
    print("\nFix: open Supabase Dashboard → SQL Editor → run supabase/schema.sql")
    print(f"     Project: {SUPABASE_URL}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
