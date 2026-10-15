# Deployment Guide

Run the violence monitor 24/7 on a server. When violence is detected, the Pi
posts the event to the web dashboard, which sends a browser push notification.

## 1. Configure `.env`

```bash
cp .env.example .env
```

Edit `.env`:

| Variable | Required | Example |
|----------|----------|---------|
| `CAMERA_IP` | Yes | `122.175.45.21` |
| `CAMERA_USER` | Yes | `admin` |
| `CAMERA_PASS` | Yes | your password |
| `PORTAL_URL` | Yes | `http://127.0.0.1:8080` or the public dashboard URL |
| `PORTAL_INGEST_KEY` | Yes | same value as `web/.env` |
| `DEPLOY_HEADLESS` | Yes | `true` |

Staff enable alerts on the dashboard after login (**Enable alerts**). That
browser then receives: `Unusual/ safety incident detected at <date time> at <daycare name>`.

## 2. Install & test locally

```bash
pip3 install -r requirements.txt

# Log a test detection to Supabase (no camera)
python3 violence_monitor.py --test-log

# Run live monitor (headless if DEPLOY_HEADLESS=true)
python3 violence_monitor.py
```

## 3. Deploy with Docker (local / VPS)

```bash
docker compose up -d --build
docker compose logs -f
```

## 4. Deploy on Render (cloud, headless)

No live feed — worker runs ML and posts detections to the dashboard. See **[RENDER.md](RENDER.md)**.

1. Push repo to GitHub (include `pi/violence_yolov8n_cls-4/weights/best.pt`)
2. Render → New → Blueprint (or Background Worker + Docker)
3. Set `CAMERA_*`, `PORTAL_URL`, `PORTAL_INGEST_KEY` in Environment
4. Region: **Singapore**, Plan: **Starter**

## 5. Deploy on a VPS (systemd)

```bash
sudo cp deploy/violence-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable violence-monitor
sudo systemctl start violence-monitor
sudo journalctl -u violence-monitor -f
```

Edit the service file paths if your install directory differs.

## 6. What happens on detection

1. YOLOv8 classifies frames from the camera RTSPS stream
2. After 2 consecutive violence hits (above threshold), an alert fires
3. Snapshot + clip saved to `alerts/`
4. Dashboard sends a push notification to browsers that enabled alerts
5. Optional: row logged to Supabase if `SUPABASE_LOGGING=true`

## Supabase logging (every detection)

1. Create a Supabase project → **SQL Editor** → run **`supabase/schema.sql`**
2. In `.env`:
   ```env
   SUPABASE_LOGGING=true
   SUPABASE_URL=https://YOUR_REF.supabase.co
   SUPABASE_SERVICE_ROLE_KEY=eyJ...
   ```
3. Verify:
   ```bash
   python3 setup_supabase.py
   python3 violence_monitor.py --test-log
   ```
4. Check **Table Editor → violence_alerts** for new rows.

On Render, set the same vars + `SUPABASE_LOGGING=true`.

## 8. Troubleshooting

| Issue | Fix |
|-------|-----|
| No push notification | Log into the dashboard over HTTPS or localhost and click **Enable alerts** |
| Camera unreachable | Server must reach camera IP (VPN/LAN/port forward) |
| Supabase insert failed / 404 | Run `supabase/schema.sql` in new project's SQL Editor |
