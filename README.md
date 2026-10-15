# Daycare violence detection

Two separate services:

| Folder | Runs on | Responsibility |
|--------|---------|----------------|
| **`pi/`** | Raspberry Pi at each daycare | Live camera feed, YOLO, upload snapshot to Cloudinary, POST metadata to web |
| **`web/`** | One shared server / laptop / Render web | Login, dashboard, **Save / Delete**, midnight auto-purge |

The Pi never deletes Cloudinary assets or dashboard rows. All UI and delete logic lives in `web/`.

```
Camera ──► Pi (ML) ──► Cloudinary (image)
                 └──► Web API (metadata)
                        └──► Dashboard (Save / Delete)
                        └──► Browser push (Enable alerts)
```

## Env files (separate per service)

| File | Used by |
|------|---------|
| `pi/.env` | Raspberry Pi monitor |
| `web/.env` | Dashboard |

```bash
cp pi/.env.example pi/.env
cp web/.env.example web/.env
```

`PORTAL_INGEST_KEY` and `CLOUDINARY_*` must be the same in both files.

```bash
cd pi
pip3 install -r requirements.txt
cp .env.example .env
python3 violence_monitor.py --headless
```

## Web dashboard (once, for all daycares)

```bash
cd web
pip3 install -r requirements.txt
python3 seed.py --ip 122.175.45.21 --password 'CAMERA_PASSWORD' --name 'Sunshine Daycare'
python3 app.py
```

Open http://127.0.0.1:8080 — username = camera IP, password = camera password.

**3+ daycares:** host `web/` once (Render or VPS) and point every Pi at that URL. See **[WEB_DEPLOY.md](WEB_DEPLOY.md)**.

**Technical write-up:** [docs/Technical_Documentation.docx](docs/Technical_Documentation.docx) (regenerate with `python3 scripts/generate_tech_doc.py`).

**Save** keeps a detection after midnight. **Delete** removes it from the portal and Cloudinary immediately.
