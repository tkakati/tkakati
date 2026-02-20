# Deployment Runbook (Railway + Vercel)

## Prerequisites
- Clerk app created with production keys
- GitHub repo connected to Railway and Vercel
- Backend root: `backend`
- Frontend root: `frontend`

## 1) Prepare production env values

You need these values first:
- `CLERK_ISSUER` (from Clerk JWT settings)
- `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` (Clerk frontend key)
- `CLERK_SECRET_KEY` (Clerk backend key)
- `ALLOWED_ORIGINS` (your Vercel domain, e.g. `https://your-app.vercel.app`)
- `NEXT_PUBLIC_APP_URL` (same Vercel domain)

## 2) Deploy Postgres + Backend API on Railway

### A. Create Railway project/services
- Service 1: API (root `backend`)
- Service 2: Worker (root `backend`)
- Add Railway Postgres plugin

### B. API service settings
- Build: Dockerfile
- Dockerfile path: `backend/Dockerfile`
- Start command:
  - `sh -c 'alembic -c alembic.ini upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT'`

### C. Worker service settings
- Build: Dockerfile
- Dockerfile path: `backend/Dockerfile`
- Start command:
  - `sh -c 'alembic -c alembic.ini upgrade head && python -m app.worker'`

### D. Railway env vars for API + Worker
- `DATABASE_URL` = Railway Postgres connection string
- `API_HOST=0.0.0.0`
- `API_PORT=8000`
- `ALLOWED_ORIGINS=https://<your-vercel-domain>`
- `CLERK_ISSUER=<your-clerk-issuer>`
- `CLERK_AUDIENCE=<optional, only if your JWT template sets aud>`
- `COLLECTOR_QUERIES=hiring,software engineer,backend engineer,full stack engineer`
- `COLLECTOR_DAYS_BACK=7`
- `COLLECTOR_TIMEOUT_SECONDS=15`
- `COLLECTOR_MAX_RETRIES=3`
- `SCHEDULER_INTERVAL_HOURS=6`

## 3) Deploy Frontend on Vercel

### A. Project settings
- Framework: Next.js
- Root directory: `frontend`

### B. Vercel env vars
- `NEXT_PUBLIC_API_BASE_URL=https://<your-railway-api-domain>`
- `NEXT_PUBLIC_APP_URL=https://<your-vercel-domain>`
- `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=<your-clerk-publishable-key>`
- `CLERK_SECRET_KEY=<your-clerk-secret-key>`

## 4) Clerk configuration
- Add your Vercel domain to Clerk allowed origins/redirects.
- Ensure issued JWT `iss` matches `CLERK_ISSUER` configured in backend.
- If `aud` is present in JWT template, set `CLERK_AUDIENCE` in Railway.

## 5) Production smoke test
1. Open `https://<your-vercel-domain>` -> should redirect to sign-in when logged out.
2. Sign in successfully.
3. Click `Run collector now` -> new row appears in Runs panel.
4. Verify posts table populates.
5. Click CSV download -> file contains:
   - `post_url,title,company,query_used,first_seen,created_at`
6. Re-run collector -> inserted count should drop with dedupe behavior.
7. Wait for worker interval (e.g. 6 hours) and verify automatic run row appears.

## 6) Immediate hardening after go-live
- Restrict `ALLOWED_ORIGINS` to only production frontend domain.
- Rotate and re-save Clerk secret keys in Railway/Vercel.
- Set Railway health check path to `/health`.
