# Deploy the shared dashboard (3+ daycares)

ML runs on each Raspberry Pi. This service is **one public website** that all Pis post to.

```
Pi A, Pi B, Pi C  ──HTTPS──►  https://daycare-dashboard.onrender.com
                                 login: camera IP + camera password
```

`127.0.0.1:8080` only works when the Pi and dashboard are the same computer.

---

## Option A — Render (recommended)

1. Push this repo to GitHub.
2. [Render Dashboard](https://dashboard.render.com) → **New** → **Blueprint** → select `render.yaml`.
   Or **New** → **Web Service** → Docker:
   - Dockerfile path: `./web/Dockerfile`
   - Docker context: `.`
   - Region: **Singapore**
   - Plan: **Starter** (needed for a persistent disk so logins survive deploys)
3. Set environment variables:

| Variable | Notes |
|----------|--------|
| `PORTAL_INGEST_KEY` | Long random string. **Same value on every Pi** (`pi/.env`) |
| `PORTAL_SECRET_KEY` | Session cookie secret (Blueprint can generate this) |
| `CLOUDINARY_CLOUD_NAME` | Same Cloudinary account as the Pis |
| `CLOUDINARY_API_KEY` | Secret |
| `CLOUDINARY_API_SECRET` | Secret |
| `DAYCARE_TZ` | `Asia/Kolkata` |
| `DATA_DIR` | `/var/data` (already set in Blueprint) |
| `WEB_TENANTS` | Register all daycares on first boot (see below) |
| `VAPID_PUBLIC_KEY` | Optional. Leave empty to auto-generate on first boot (stored on the disk) |
| `VAPID_PRIVATE_KEY` | Optional pair for the public key |
| `VAPID_MAILTO` | Optional `mailto:alerts@your-domain.com` |

4. Attach a **1 GB disk** at `/var/data` (Blueprint already does this). Without it, SQLite (logins + saved detections) is wiped on every deploy.

5. After deploy, copy the service URL, e.g. `https://daycare-dashboard.onrender.com`.

### Register 3 daycares (`WEB_TENANTS`)

Format: `CAMERA_IP|CAMERA_PASSWORD|Display Name` separated by `;`

```
192.168.1.50|SiteACamPass|Sunshine Delhi;192.168.0.20|SiteBCamPass|Sunshine Noida;10.0.0.15|SiteCCamPass|Sunshine Gurgaon
```

Or SSH/Render Shell after live:

```bash
cd /app
python3 seed.py --ip 192.168.1.50 --password 'SiteACamPass' --name 'Sunshine Delhi'
python3 seed.py --ip 192.168.0.20 --password 'SiteBCamPass' --name 'Sunshine Noida'
python3 seed.py --ip 10.0.0.15 --password 'SiteCCamPass' --name 'Sunshine Gurgaon'
```

Username on the website is the **camera IP**. Password is the **camera password** you seeded.

---

## Option B — VPS (Ubuntu)

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip
cd /opt
git clone YOUR_REPO live_feed
cd live_feed/web
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env: PORTAL_INGEST_KEY, PORTAL_SECRET_KEY, CLOUDINARY_*, WEB_TENANTS
```

Run with gunicorn (or copy `deploy/daycare-dashboard.service`):

```bash
DATA_DIR=/var/lib/daycare-dashboard
sudo mkdir -p "$DATA_DIR"
gunicorn --bind 0.0.0.0:8080 --workers 1 --threads 4 app:app
```

Put Nginx + HTTPS in front (Certbot). Then every Pi uses:

```env
PORTAL_URL=https://dashboard.yourdomain.com
PORTAL_INGEST_KEY=the-same-key-as-on-the-server
```

---

## Point each Pi at the live URL

On **every** Pi, `pi/.env`:

```env
DAYCARE_NAME=Sunshine Delhi
CAMERA_IP=192.168.1.50
CAMERA_USER=admin
CAMERA_PASS=that-site-camera-password

PORTAL_URL=https://daycare-dashboard.onrender.com
PORTAL_INGEST_KEY=same-as-web
CLOUDINARY_CLOUD_NAME=...
CLOUDINARY_API_KEY=...
CLOUDINARY_API_SECRET=...
```

Change `DAYCARE_NAME` / `CAMERA_*` per site. Keep `PORTAL_URL`, `PORTAL_INGEST_KEY`, and Cloudinary keys the same.

Check from the Pi:

```bash
curl -sS https://YOUR-DASHBOARD/health
# {"ok": true, "service": "daycare-dashboard"}
```

Then:

```bash
cd pi
python3 violence_monitor.py --headless
```

Staff open the dashboard URL and log in with **their** camera IP + camera password. They only see that site’s detections.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `[web] ingest failed: Connection refused` | Dashboard not running, or Pi still has `PORTAL_URL=http://127.0.0.1:8080` |
| `unknown camera_ip` | Seed that camera IP (`WEB_TENANTS` or `seed.py`) |
| `unauthorized` | `PORTAL_INGEST_KEY` on Pi ≠ web |
| Login forgotten after redeploy | Add the `/var/data` disk on Render |
| Health check fails | Confirm `/health` returns 200 |
