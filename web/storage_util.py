"""Delete detection frames. New files live in Supabase Storage."""

from __future__ import annotations

from config import (
    CLOUDINARY_API_KEY,
    CLOUDINARY_API_SECRET,
    CLOUDINARY_CLOUD_NAME,
    SUPABASE_SERVICE_ROLE_KEY,
    SUPABASE_STORAGE_BUCKET,
    SUPABASE_URL,
)


def storage_configured() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)


def _client():
    from supabase import create_client

    return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


def _destroy_supabase(object_path: str) -> bool:
    if not storage_configured():
        print("  [web] Supabase storage is not configured — frame left in place")
        return False
    try:
        _client().storage.from_(SUPABASE_STORAGE_BUCKET).remove([object_path])
        return True
    except Exception as e:
        print(f"  [web] Supabase storage delete failed: {e}")
        return False


def _destroy_cloudinary(public_id: str) -> bool:
    if not (CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET):
        return False
    try:
        import cloudinary
        import cloudinary.uploader

        cloudinary.config(
            cloud_name=CLOUDINARY_CLOUD_NAME,
            api_key=CLOUDINARY_API_KEY,
            api_secret=CLOUDINARY_API_SECRET,
            secure=True,
        )
        cloudinary.uploader.destroy(public_id, invalidate=True)
        return True
    except Exception as e:
        print(f"  [web] Cloudinary delete failed: {e}")
        return False


def destroy_asset(object_path: str) -> bool:
    if not object_path:
        return False
    # New uploads store a file path such as 122-175-45-21/alert_20260924_170024.jpg.
    # Older rows store a Cloudinary public id with no image extension.
    if object_path.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
        return _destroy_supabase(object_path)
    return _destroy_cloudinary(object_path)
