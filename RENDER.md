# Render — daycare dashboard (not the ML worker)

Violence detection runs on **Raspberry Pis at each site**. Render only hosts the **shared web dashboard**.

Full steps (3 locations, env vars, `WEB_TENANTS`, Pi `PORTAL_URL`): **[WEB_DEPLOY.md](WEB_DEPLOY.md)**

Quick path:

1. Blueprint this repo (`render.yaml`) or Web Service + `./web/Dockerfile`
2. Set `PORTAL_INGEST_KEY`, Cloudinary keys, `WEB_TENANTS`
3. Attach disk at `/var/data`
4. On each Pi set `PORTAL_URL=https://<service>.onrender.com`
