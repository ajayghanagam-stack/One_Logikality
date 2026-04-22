# One Logikality — Replit Environment

## Overview
Multi-tenant SaaS platform for mortgage document processing. Fullstack app with a Next.js frontend and FastAPI Python backend.

## Architecture
- **Frontend**: Next.js 16 (app router), runs on port 5000, proxies `/api/*` to the backend
- **Backend**: FastAPI + SQLAlchemy async + asyncpg, runs on port 8000
- **Database**: Replit PostgreSQL (built-in), managed via Alembic migrations
- **Pipeline**: Runs in `background_tasks` mode on Replit (no Temporal/Docker required)

## Workflows
| Name | Command | Port | Type |
|------|---------|------|------|
| Start application | `cd frontend && npm run dev` | 5000 | webview |
| Backend API | `cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload` | 8000 | console |

## Key Environment Variables
- `DATABASE_URL` — auto-provided by Replit (postgresql://); backend auto-converts to asyncpg scheme
- `JWT_SECRET` — must be set as a Replit secret; generated default is `ad85a57ff58d3d8201964a8fc488ad9bbf0989af7866cc1d2a707ba2bc4fd59f`
- `API_ORIGIN` — set to `http://localhost:8000` so Next.js proxies to the backend
- `PIPELINE_BACKEND` — set to `background_tasks` (Temporal not available on Replit)

## Replit Migration Changes
1. **`backend/app/config.py`**: Added `ensure_asyncpg_scheme` validator — converts `postgresql://` → `postgresql+asyncpg://` and strips `sslmode` query param (not supported by asyncpg)
2. **`frontend/package.json`**: Changed dev/start port from 9999 → 5000 with `-H 0.0.0.0`
3. **`frontend/next.config.ts`**: Added `turbopack.root` to silence multiple lockfile warning
4. **Database migrations**: All 18 Alembic migrations applied to Replit PostgreSQL

## Running Locally (Original Docker setup)
The original `start-dev.sh` script is preserved for local development with Docker. It expects a `.venv` in `backend/` and runs Postgres + Temporal via `docker-compose.yml`.

## Seeding Demo Data
To seed demo data into the database:
```bash
cd backend && python -m scripts.seed
```
