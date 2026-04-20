# One Logikality — Tech Stack (Local Dev)

Local-development stack for One Logikality. Aligned with Title Intelligence Hub (TI Hub) so engineers move between projects without re-learning tooling, with a small number of deliberate upgrades called out at the end.

Staging/production AWS stack is TBD and will be documented separately.

---

## 1. Team platforms

One Logikality supports a **mixed Mac + Windows** team. The contract between the code and the container runtime is the **`docker` CLI + `docker-compose.yml`** — not any specific GUI. Every platform below produces identical command-line behavior.

| Platform | Container runtime | Why |
|---|---|---|
| **macOS (Apple Silicon)** | **OrbStack** | Native arm64, 2–5× faster bind-mount I/O, ~400 MB RAM vs Docker Desktop's 2–4 GB, free for personal use, same `docker` CLI |
| **Windows 10/11** | **Docker Desktop** (preferred) or **Rancher Desktop** (license-free alternative) | Docker Desktop has deep WSL2/Hyper-V integration on Windows and is strongest on this platform. Rancher Desktop (free OSS from SUSE) is a drop-in alternative if the Docker Desktop commercial license is an issue for your org |

**Docker Desktop license watch-out:** Docker Desktop requires a paid subscription for companies with **>250 employees OR >$10M USD annual revenue**. If either threshold applies, Windows users should standardize on **Rancher Desktop** instead. OrbStack has its own commercial tier ($8/user/month).

**Non-goals:** No Replit support, no cloud-dev containers, no Nix. Mac or Windows laptops only.

---

## 2. Language runtimes

| Layer | Choice | Notes |
|---|---|---|
| Python (backend + pipeline workers) | **Python 3.12** | Matches TI Hub. Install via `pyenv` (Mac) or `pyenv-win` / official installer (Windows) |
| Node.js (frontend) | **Node 20 LTS** | Required by Next.js 16 / React 19. Install via `nvm` (Mac) or `nvm-windows` / `fnm` (Windows) |
| Node package manager | **npm** | Matches TI Hub's convention; avoids a second lockfile format for engineers switching projects |
| TypeScript | **5.x** | Matches the existing demo |

---

## 3. Application framework

Aligned with TI Hub's split-service topology: a Python backend handles data, auth, and pipeline orchestration; a Next.js frontend owns the UI.

| Concern | Choice | Notes |
|---|---|---|
| Backend framework | **FastAPI 0.115+** | Same as TI Hub |
| ASGI server | **uvicorn 0.34+** with `--reload` locally | Same as TI Hub |
| Frontend framework | **Next.js 16** (App Router, Turbopack) | **Kept at 16** (the demo is already here — downgrading to TI Hub's 14 would be churn) |
| Frontend UI | **React 19**, inline styles from `lib/brand.ts`, inline SVG icons | Per `CLAUDE.md` conventions |
| Frontend state (demo only) | React Context in `stores/demo-store.tsx` | Production persistence is TBD and is not the demo-store |

---

## 4. Data layer

| Concern | Choice | Notes |
|---|---|---|
| Database | **PostgreSQL 16-alpine** in Docker | Same image as TI Hub |
| Async driver | **asyncpg** | Matches TI Hub |
| ORM | **SQLAlchemy 2.0 async** | Matches TI Hub; not Drizzle |
| Migrations | **Alembic 1.14+**, `alembic upgrade head` on backend startup | Matches TI Hub |
| Row-level security | Postgres RLS keyed on `org_id`, enforced from day one | Defense-in-depth for multi-tenant |
| Seed data | Python script mirroring `lib/demo-data.ts` so the frontend works without a real backend |

---

## 5. Pipeline orchestration

| Concern | Choice | Notes |
|---|---|---|
| Orchestrator | **Temporal 1.7+** via `temporalio/auto-setup` container | Same as TI Hub. Chosen over BullMQ/Celery because our ECV pipeline (OCR → Classify → Extract → Validate → Analyze) has the exact shape Temporal was built for: long durations, retries, compensations, observability |
| Task queues | `ecv`, `title-search`, `title-exam`, `compliance`, `income-calc` | One queue per micro-app, same pattern as TI Hub's `title-intelligence` / `title-search` |
| Temporal UI | `temporalio/ui` container | Local workflow debugging |
| UI ↔ backend eventing | **Server-Sent Events** from FastAPI | One-way streaming; no WebSocket infra |

No Redis, no BullMQ, no Celery.

---

## 6. Auth (local dev)

| Concern | Choice | Notes |
|---|---|---|
| Scheme | **Homegrown JWT** (HS256), 24h TTL, `Authorization: Bearer <token>` | Matches TI Hub. Adopting Clerk/Auth0 is a later decision — don't fork auth between the two products until there is a concrete reason |
| Password hashing | `argon2-cffi` | Only if/when One Logikality stops using TI Hub's pattern of JWT-issuing login endpoint |
| Secret loading | `JWT_SECRET` from `.env` | Dev default is insecure and labeled as such |

Production auth (Clerk/Auth0/Cognito) is an explicit future decision.

---

## 7. Object storage (local)

| Concern | Choice | Notes |
|---|---|---|
| Default driver | **Local filesystem** at `./storage` | Matches TI Hub. Simpler than MinIO; one fewer container |
| Switch to S3/MinIO | `STORAGE_PROVIDER=s3` env flag + `S3_ENDPOINT`, `S3_BUCKET`, keys | Matches TI Hub |
| Max upload | 100 MB per file | Matches TI Hub |

---

## 8. AI / ML providers

Aligned with `CLAUDE.md`: **Gemini 2.5 Flash** for classification, **Gemini 2.5 Pro** for extraction, **Claude Sonnet 4** for validation & reasoning.

| Concern | Choice | Notes |
|---|---|---|
| Provider abstraction | **LiteLLM 1.0+** | Matches TI Hub. Lets us swap providers via config for the eval harness and handle fallbacks cleanly |
| Direct SDKs (where needed) | `anthropic>=0.20`, `google-generativeai>=0.5`, `google-genai>=1.0` (Vertex) | Matches TI Hub |
| Default PDF extraction | **Native PDF → Gemini** (TI Hub pattern) | Simpler pipeline, already production-proven at TI Hub |
| Selective extraction upgrade | **Vertex AI Document AI Lending processors** for W-2, 1040, paystub, URLA/1003, Closing Disclosure | Document AI's specialized processors beat general LLMs on standardized mortgage forms. Add selectively, not wholesale |
| Legacy Claude mode | JPEG render at 100 DPI, 8 images/batch | Matches TI Hub |
| Keys | `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_REGION` in `.env` | Server-side only; never exposed to the browser |

### Model-selection guardrails

- Lock all model calls to strict JSON schemas (Claude tool-use; Gemini `response_schema` + `response_mime_type: application/json`). No free-form parsing.
- Every finding carries `(document_id, page, MISMO_3.6_path, text_snippet)` evidence. Enforced at schema validation.
- Build an eval harness (see §10) before committing to a provider split.

---

## 9. Testing

| Layer | Choice | Notes |
|---|---|---|
| Backend unit / integration | **pytest 9 + pytest-asyncio** | Matches TI Hub |
| Backend test markers | `benchmark`, `benchmark_live`, `llm_eval` | Adopted directly from TI Hub |
| Frontend E2E | **Playwright 1.58+** | Matches TI Hub |
| Frontend unit | **Vitest** | **Upgrade over TI Hub** (TI Hub has no FE unit tests); fast on Apple Silicon |

---

## 10. Tooling & code quality

| Concern | Choice | Notes |
|---|---|---|
| FE linting | **ESLint 8**, Next.js lint | Matches TI Hub |
| BE linting/formatting | **Ruff** (lint + format) | **Upgrade over TI Hub** — TI Hub has no committed Python linter; Ruff costs nothing to adopt and should eventually propagate back to TI Hub |
| Pydantic | **v2** | Matches TI Hub |
| Git hooks | `lefthook` | Fast on Apple Silicon |
| Secret scanning | `gitleaks` pre-commit | Catches leaked keys locally |
| Commit convention | Conventional Commits + `commitlint` | — |

---

## 11. Local services (`docker-compose.yml`)

All ports chosen to **avoid collisions with TI Hub** so a developer can run both projects simultaneously on one laptop.

| Service | Image | Host port | Purpose |
|---|---|---|---|
| `db` | `postgres:16-alpine` | **5437** | Application DB (TI Hub uses 5436) |
| `temporal-db` | `postgres:16-alpine` | internal only | Temporal state |
| `temporal` | `temporalio/auto-setup:latest` | **7234** | Temporal server (TI Hub uses 7233) |
| `temporal-ui` | `temporalio/ui:latest` | **8086** | Temporal UI (TI Hub uses 8085) |

**Not included** (deliberately): Redis, MinIO, MailHog. Add only when there is a concrete need.

---

## 12. Native processes (started by `./start-dev.sh`)

| Process | Host port | Notes |
|---|---|---|
| **uvicorn** (FastAPI backend) | **8001** | TI Hub uses 8000 |
| **Temporal worker** | — | Separate Python process, no listener |
| **Next.js dev** (`npx next dev`) | **9999** | Keeps the One Logikality demo port to avoid developer muscle-memory confusion |

---

## 13. Bring-up (one command per platform)

Prereqs:

- **macOS:** OrbStack installed (`brew install --cask orbstack`), Python 3.12 via `pyenv`, Node 20 via `nvm`.
- **Windows:** Docker Desktop (or Rancher Desktop) running, Python 3.12, Node 20 via `nvm-windows`, and either Git Bash or WSL2 for running `./start-dev.sh`.

```bash
# First time, on either platform
git clone <repo> && cd One_Logikality
cp .env.example .env                   # fill in AI provider keys + JWT_SECRET
./start-dev.sh
```

Every subsequent day:

```bash
./start-dev.sh
```

`start-dev.sh` (modeled on TI Hub's) performs:

1. Kill stale uvicorn / Temporal worker / next dev processes.
2. `docker compose up -d db temporal-db temporal temporal-ui`.
3. `alembic upgrade head` + `python scripts/seed.py`.
4. Start `uvicorn app.main:app --reload --port 8001` in the background.
5. Start the Temporal worker (`python -m app.pipeline.worker`) in the background.
6. Start `npx next dev -p 9999` in the background.
7. Print URLs: UI → `http://localhost:9999`, API → `http://localhost:8001/docs`, Temporal UI → `http://localhost:8086`.

**Windows note:** If Git Bash misbehaves on the script's process management, use WSL2 Ubuntu as the shell. Docker Desktop / Rancher Desktop bridges WSL2 cleanly.

---

## 14. Environment variables

Keep the same variable names as TI Hub so engineers don't context-switch. `.env.example` is committed; `.env` is gitignored.

| Variable | Example | Notes |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5437/one_logikality` | Local Postgres |
| `TEMPORAL_ADDRESS` | `localhost:7234` | Local Temporal |
| `JWT_SECRET` | (random string) | Insecure dev default is flagged in code |
| `JWT_EXPIRATION_MINUTES` | `1440` | 24h, matches TI Hub |
| `ANTHROPIC_API_KEY` | `sk-ant-...` | Server-side only |
| `GOOGLE_API_KEY` | `AIza...` | If not using Vertex |
| `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_REGION` | — | For Vertex AI + Document AI |
| `STORAGE_PROVIDER` | `local` \| `s3` | Matches TI Hub |
| `STORAGE_PATH` | `./storage` | Local filesystem default |
| `PIPELINE_BACKEND` | `temporal` \| `background_tasks` | `temporal` locally; `background_tasks` only as a degraded fallback |
| `AI_PROVIDER` | `claude` \| `gemini` \| `hybrid` | Matches TI Hub |

---

## 15. Portability guardrails (dev → AWS)

Every local choice has its production counterpart. The port to AWS is mostly config, not code.

| Local | AWS equivalent |
|---|---|
| Postgres in Docker | RDS Postgres 16 |
| Temporal in Docker | Temporal Cloud (managed) or self-hosted on ECS |
| Local filesystem storage | S3, selected via `STORAGE_PROVIDER=s3` |
| Homegrown JWT | Same JWT, plus Secrets Manager for `JWT_SECRET`; Cognito/Clerk/Auth0 is a later decision |
| `.env` file | Parameter Store / Secrets Manager injected at runtime |

Code-level guardrails:

- **No Mac-only native deps.** Everything arm64-container compatible so the same images run on Graviton.
- **Driver pattern.** `StorageAdapter`, `QueueAdapter`, `LLMAdapter` interfaces with env-switched implementations — never branch on `NODE_ENV` in business code.
- **Same migration tool, same schema.** `alembic` runs locally and against RDS unchanged.

---

## 16. Deliberate deviations from TI Hub

Short list, each justified. Everything else matches TI Hub.

| # | Deviation | Reason |
|---|---|---|
| 1 | **Next.js 16** (TI Hub is on 14) | The One Logikality demo is already on 16; downgrading would be churn with zero upside |
| 2 | **Per-platform container runtime** (OrbStack on Mac / Docker Desktop or Rancher Desktop on Windows) | Mac users get real perf/RAM wins from OrbStack; the `docker` CLI contract is identical across all three, so scripts and compose files are portable |
| 3 | **Ruff added to backend** | TI Hub has no Python linter committed; adding Ruff costs nothing and should eventually back-port to TI Hub |
| 4 | **Vitest added to frontend** | TI Hub has no FE unit tests; fills a real gap |
| 5 | **Port offsets** (5437 / 7234 / 8001 / 8086 / 9999) | Lets engineers run TI Hub and One Logikality on the same laptop without collisions |
| 6 | **Selective Vertex AI Document AI** for a handful of standardized mortgage forms | TI Hub's native-PDF-to-Gemini pattern is the default here too, but Document AI's Lending processors beat LLMs on W-2/1040/paystub/URLA/CD accuracy — worth layering in for ECV and Income Calc |

No deviations on: Python version, FastAPI, SQLAlchemy async + asyncpg, Alembic, Temporal, homegrown JWT, local filesystem storage, LiteLLM, pytest + pytest-asyncio, ESLint, npm, Playwright, Pydantic v2, `.env` convention, env variable names.

---

## 17. Non-goals for local dev

Called out so they don't drift in:

- No Redis (Temporal replaces BullMQ; no cache need yet)
- No MinIO (filesystem is enough)
- No MailHog (no outbound email in dev yet)
- No Kubernetes (docker-compose is fine for single-machine dev)
- No Clerk/Auth0 (homegrown JWT matches TI Hub; revisit later)
- No Drizzle / Prisma (SQLAlchemy is the ORM for both products)
- No Nix / Replit (Mac + Windows only)

