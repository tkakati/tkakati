# Hiring Post Collector Monorepo

Polished v1 monorepo for collecting and reviewing recent hiring posts.

## Stack
- Backend: FastAPI + SQLAlchemy + Alembic
- Database: PostgreSQL
- Frontend: Next.js (App Router)
- Auth: Clerk
- Hosting: Railway (API + worker + Postgres), Vercel (frontend)

## Project Structure
- `backend/`: API, collector service, scheduler worker, migrations
- `frontend/`: dashboard UI + Next API routes + Clerk integration
- `.env.example`: env template for local + deploy
- `docker-compose.yml`: local full stack

## Implemented Features (Steps 3-12)
- SQLAlchemy models + Alembic migrations for `posts`, `runs`, and `hiring_signals`
- Collector pipeline with:
  - LinkedIn-focused web search via Serper API
  - role targeting for PM tracks from `COLLECTOR_QUERIES`
  - hiring-language filtering via `COLLECTOR_HIRING_TERMS`
  - block-list filtering via `COLLECTOR_BLOCK_TERMS`
  - GPT-based company extraction (`OPENAI_COMPANY_MODEL`, default `gpt-5.2`)
  - LLM hiring signal classification (`OPENAI_SIGNAL_MODEL`, default `gpt-4o`)
  - async batched signal scoring + storage in `hiring_signals`
  - company-level signal aggregation logs (strong-signal count + average strength)
  - 7-day filtering (`COLLECTOR_DAYS_BACK`)
  - retries/backoff (`COLLECTOR_MAX_RETRIES`)
  - request timeout (`COLLECTOR_TIMEOUT_SECONDS`)
  - duplicate-safe inserts on `post_url`
  - structured run logs and metrics
- API endpoints with OpenAPI docs:
  - `GET /posts`
  - `POST /collector/run`
  - `GET /runs`
  - `GET /export.csv`
- Scheduler/worker entrypoints:
  - one-shot: `python -m app.scheduler`
  - loop worker: `python -m app.worker`
- Next.js dashboard:
  - posts table + filters + pagination
  - run collector button
  - CSV download
  - run history panel
- Clerk auth:
  - dashboard protected in frontend middleware
  - backend endpoints protected with Clerk JWT verification
- Deploy config files for Railway/Vercel

## Environment Setup
1. Copy env file:
   - `cp .env.example .env`
2. Fill Clerk values:
   - `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`
   - `CLERK_SECRET_KEY`
   - `CLERK_ISSUER` (e.g. `https://<your-subdomain>.clerk.accounts.dev`)
   - optionally `CLERK_AUDIENCE` if your JWT template sets `aud`
3. Adjust collector targeting (optional):
   - `COLLECTOR_QUERIES` (comma-separated roles)
   - `COLLECTOR_HIRING_TERMS` (comma-separated hiring intent terms)
   - `COLLECTOR_BLOCK_TERMS` (comma-separated exclusions)
   - `OPENAI_API_KEY` + `OPENAI_COMPANY_MODEL`
   - `OPENAI_SIGNAL_MODEL` + `SIGNAL_CLASSIFIER_CONCURRENCY`
   - `SERPER_API_KEY`

## Run Locally (Docker)
1. `cp .env.example .env`
2. `docker compose up --build`
3. Open:
   - Frontend: `http://localhost:3000`
   - Backend docs: `http://localhost:8000/docs`

## Run Locally (Manual)

### 1) Start Postgres
Use Docker or a local Postgres instance and point `DATABASE_URL` to it.

### 2) Backend
1. `cd backend`
2. `python3 -m venv .venv && source .venv/bin/activate`
3. `pip install -r requirements.txt`
4. `cp ../.env.example .env`
5. `alembic -c alembic.ini upgrade head`
6. `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`

### 3) Worker (optional local scheduler)
1. `cd backend`
2. `source .venv/bin/activate`
3. `python -m app.worker`

### 4) Frontend
1. `cd frontend`
2. `npm install`
3. `cp ../.env.example .env.local`
4. `npm run dev`

## API Contracts
- `GET /posts`
  - query params: `company`, `title`, `date_from`, `date_to`, `page`, `page_size`
- `POST /collector/run`
  - manual run trigger, writes a row in `runs`
- `GET /runs`
  - latest run history
- `GET /export.csv`
  - CSV export using same filters as `/posts`
- `PATCH /posts/{post_id}/status`
  - body: `{\"status\": \"no action|reached out|responded|chatted|referred\"}`

All routes above require a valid Clerk bearer token.

## Railway Deployment

### Backend API service
1. Create Railway service from repo root.
2. Set service root to `backend` or use `backend/railway.toml`.
3. Add env vars from `.env.example`.
4. Attach Railway Postgres and set `DATABASE_URL`.
5. Start command:
   - `sh -c 'alembic -c alembic.ini upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT'`

### Worker service
1. Create second Railway service from same repo.
2. Use `backend/railway.worker.toml` or set start command:
   - `sh -c 'alembic -c alembic.ini upgrade head && python -m app.worker'`
3. Set `SCHEDULER_INTERVAL_HOURS=6` (or 12).

### Alternative: Railway Cron
Run one-shot command on schedule:
- `python -m app.scheduler`

## Vercel Deployment
1. Import `frontend` as the project root.
2. Set env vars:
   - `NEXT_PUBLIC_API_BASE_URL` -> Railway backend URL
   - `NEXT_PUBLIC_APP_URL` -> Vercel app URL
   - `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`
   - `CLERK_SECRET_KEY`
3. Deploy.

## Smoke Test Checklist
1. Sign in succeeds and dashboard is protected.
2. `Run collector now` inserts a `runs` record.
3. `/posts` only contains results from last 7 days.
4. Re-running collector does not duplicate `post_url` rows.
5. CSV downloads with columns:
   - `post_url,title,company,query_used,first_seen,created_at`
6. Worker/cron creates periodic `runs` rows.
