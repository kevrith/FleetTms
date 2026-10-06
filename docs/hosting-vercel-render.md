# Hosting on Vercel, Render (free) and Supabase

A low-cost way to put FleetTms online for a demo or pilot: the web app on Vercel, the API on Render's free plan, the database on Supabase. For a real launch with paying customers use `docs/deployment.md` instead; the limits below are why.

| Part | Where | Files |
|---|---|---|
| Web app | Vercel | `vercel.json` |
| API and background jobs | Render free web service | `render.yaml`, `apps/api/start-render.sh` |
| Redis (job queue, rate limits) | Render free Key Value | `render.yaml` |
| Photos | Cloudflare R2 (private bucket) | `render.yaml` |
| Database | Supabase | none; the API migrates it on start |

## 1. Database (Supabase)

1. Create a project. Keep the database password somewhere safe (it is never put in the repository).
2. Press **Connect** and copy the **Session pooler** connection string (host like `aws-0-<region>.pooler.supabase.com`, port 5432, user `postgres.<project-ref>`). Do not use the "Direct connection": it is IPv6 only and Render's free plan cannot reach it. Do not use the Transaction pooler (port 6543): it breaks prepared statements.
3. Put your password into the string where it says `[YOUR-PASSWORD]`. The `postgresql://` form is fine; the API converts it.

TimescaleDB is not needed: the GPS table is an ordinary table when it is missing.

## 2. Photo storage (Cloudflare R2)

1. Cloudflare dashboard > **R2 Object Storage**. R2 asks for a payment card to switch on, but the free allowance (10 GB, no charge for downloads) covers a pilot.
2. **Create bucket**, e.g. `fleettms-photos`. Leave it **private**: do not enable the public `r2.dev` address or a custom domain. The API reads the files and hands out short-lived signed links.
3. Your **Account ID** is shown on the R2 overview page. The endpoint is `https://<account id>.r2.cloudflarestorage.com`.
4. **Manage API Tokens > Create API token**: permission **Object Read & Write**, applied to the one bucket only. Copy the **Access Key ID** and **Secret Access Key** (the secret is shown once).
5. These four values go into Render in step 3: `S3_BUCKET` (the bucket name), `S3_ENDPOINT_URL`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`. `render.yaml` already sets `STORAGE_BACKEND=s3`, `S3_REGION=auto` and `S3_FORCE_PATH_STYLE=true`.

## 3. API and Redis (Render)

1. Push the repository to GitHub (`render.yaml` and `vercel.json` must be on the branch you deploy).
2. Render dashboard: **New > Blueprint**, pick the repository. It creates `fleettms-api` and `fleettms-redis` on the free plan.
3. When asked for the values marked `sync: false`:
   - `DATABASE_URL`: the Session pooler string from step 1.
   - `PUBLIC_API_URL`: `https://fleettms-api.onrender.com` (use the address Render shows for the service; if the name was taken it has a suffix).
   - `CORS_ORIGINS`, `PUBLIC_WEB_URL`, `WEB_APP_URL`: the Vercel address from step 4. You do not have it yet: put a placeholder, then edit them after step 4 and let the service redeploy.
4. Wait for the first deploy. It runs `alembic upgrade head`, starts the background worker and serves the API. Open `https://<your-api>/health`: `database` and `redis` should both say `up`.
5. Create the first platform admin. In the service's **Shell** tab (not available on the free plan: run it from your own machine instead, with `DATABASE_URL` and `REDIS_URL` pointing at the hosted ones, and `PLATFORM_ADMIN_EMAIL`, `PLATFORM_ADMIN_NAME`, `PLATFORM_ADMIN_PASSWORD` set in your shell): `python -m app.cli create-platform-admin`.

## 4. Web app (Vercel)

1. **Add New > Project**, import the same repository. Leave **Root Directory** as the repository root: `vercel.json` sets the install, build and output.
2. Environment variable: `VITE_API_URL` = the Render address, e.g. `https://fleettms-api.onrender.com` (no trailing slash).
3. Deploy. Copy the Vercel address (`https://<name>.vercel.app`) into Render's `CORS_ORIGINS`, `PUBLIC_WEB_URL` and `WEB_APP_URL`, save, and let Render redeploy.
4. Open the Vercel address and sign in. A change to `VITE_API_URL` needs a redeploy on Vercel, because it is baked in at build time.

The phone app needs the same API address in its own build settings.

## What the free plans mean

- **The API sleeps after 15 minutes without traffic** and takes about a minute to wake: the first request after a quiet spell is slow. The scheduled jobs (reminders, reports, eTIMS sending, retention) run only while it is awake, so none of them can be relied on. Use a paid instance for anything real.
- **Photos are kept in R2**, not on the instance, because free instances have no disk.
- **Redis is not persistent** on the free plan: usage counts and queued jobs can be lost on a restart.
- **Supabase pauses a free project after a week without activity**; restore it from the dashboard.
- **Memory is 512 MB**, so the API runs one worker process, not four.
- `ENVIRONMENT` is `staging`. With `production` the API refuses to start until Africa's Talking SMS credentials are set (otherwise sign-in codes would go nowhere) and every address is https. Switch it once those exist.
- `TRUST_PROXY_HEADERS` is on so each visitor has their own rate limit. Behind Render a client can still send a forged first address; fine for a demo, revisit before launch.
- The mobile app, M-Pesa, eTIMS, WhatsApp and card payments all need their own keys set in Render's environment tab; none are required to open the site.

## Settings go in the dashboards only

Never put real values in `render.yaml`, `vercel.json` or any file in the repository. Secrets are entered in Render's and Vercel's environment settings. `JWT_SECRET` is generated by Render.
