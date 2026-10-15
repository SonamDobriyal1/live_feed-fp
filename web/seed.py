"""Register a daycare tenant on the web dashboard."""

from __future__ import annotations

import argparse

import db as store


def main() -> None:
    parser = argparse.ArgumentParser(description="Register a daycare on the web dashboard")
    parser.add_argument("--ip", required=True, help="Camera IP (portal username)")
    parser.add_argument("--password", required=True, help="Camera password (portal password)")
    parser.add_argument("--name", required=True, help="Daycare display name")
    args = parser.parse_args()
    store.init_db()
    store.upsert_tenant(args.ip, args.password, args.name)
    print(f"Registered {args.name}  username={args.ip}")


if __name__ == "__main__":
    main()
