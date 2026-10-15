"""Web dashboard configuration. Independent from the Pi ML service."""

import os
from pathlib import Path

from dotenv import load_dotenv

_ENV_FILE = Path(__file__).parent / ".env"
# Local: web/.env. Render/VPS: process environment only (no file required).
if _ENV_FILE.exists():
    load_dotenv(_ENV_FILE, override=True)

DAYCARE_TZ = os.getenv("DAYCARE_TZ", "Asia/Kolkata")

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_STORAGE_BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET", "detections")

# Only used to delete frames that were uploaded before the Supabase switch.
CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME", "")
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY", "")
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET", "")

PORTAL_INGEST_KEY = os.getenv("PORTAL_INGEST_KEY", "")
PORTAL_SECRET_KEY = os.getenv("PORTAL_SECRET_KEY", "change-me-in-production")
# Render injects PORT; local default is 8080.
PORTAL_PORT = int(os.getenv("PORT") or os.getenv("PORTAL_PORT", "8080"))
PORTAL_DEBUG = os.getenv("PORTAL_DEBUG", "false").lower() in ("1", "true", "yes")
DATA_DIR = Path(os.getenv("DATA_DIR") or (Path(__file__).parent / "data"))
# Optional first-boot tenants: ip|password|Daycare Name;ip|password|Other
WEB_TENANTS = os.getenv("WEB_TENANTS", "")

# Web Push (VAPID). Empty keys are generated once and stored in DATA_DIR/vapid.json.
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_MAILTO = os.getenv("VAPID_MAILTO", "mailto:alerts@localhost")
