# Pi service — live feed + ML

Runs on a Raspberry Pi next to the camera. It does **not** host the dashboard.

1. Pull the RTSPS live feed
2. Run YOLOv8 violence detection (pauses 15 minutes after an alert)
3. Upload a JPEG to Cloudinary
4. POST metadata to the **web** service (`PORTAL_URL`), which sends browser push alerts

```bash
cd pi
pip3 install -r requirements.txt
cp .env.example .env
python3 violence_monitor.py --headless
```

Set `PORTAL_URL` and `PORTAL_INGEST_KEY` to match `web/`. For multiple sites use the **public** dashboard URL from **[WEB_DEPLOY.md](../WEB_DEPLOY.md)** — not `127.0.0.1`. Cloudinary keys must match the web service so images land in the same account (folder per camera IP).

Delete / save is **not** implemented here.
