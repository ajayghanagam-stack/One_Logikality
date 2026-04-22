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
To seed users/orgs into the database (does NOT seed micro-app data):
```bash
cd backend && python -m scripts.seed
```

## AI Pipeline Architecture
All micro-app findings are now derived in real-time from the actual uploaded documents — **no canned/demo data**.

### ECV Pipeline Stages
| Stage | Module | What it does |
|-------|--------|-------------|
| classify | `pipeline/classify.py` | Gemini 2.5 Flash classifies every page → `ecv_documents` |
| extract | `pipeline/extract.py` | Gemini 2.5 Pro extracts MISMO 3.6 fields → `ecv_extractions` |
| validate | `pipeline/validate.py` | Claude Sonnet grades 58 ECV checks → `ecv_sections`/`ecv_line_items` |
| score | `pipeline/title_exam_pipeline.py` etc. | Claude derives micro-app findings from document text |

### Micro-app Derivation Pipelines (NEW)
Each pipeline reads the full document text (up to 8000 chars/page via `page_utils.py`) and asks Claude Sonnet to generate structured findings:

- **`title_exam_pipeline.py`** — reads TITLE_COMMITMENT → Schedule B exceptions, Schedule C requirements, warnings, checklist
- **`income_pipeline.py`** — reads W2/PAYSTUB/TAX_RETURN → income sources, DTI obligations, findings
- **`compliance_pipeline.py`** — reads LOAN_ESTIMATE/CLOSING_DISCLOSURE → TRID/RESPA compliance checks
- **`title_search_pipeline.py`** — reads TITLE_COMMITMENT/WARRANTY_DEED/DEED_OF_TRUST → flags, property summary

All pipelines are idempotent and failure-tolerant. Empty document text → empty tables → empty state UI (no errors).

### Re-deriving Findings
To re-derive AI findings for all completed packets (e.g. after clearing data):
```bash
cd backend && python -m scripts.rederive
```
