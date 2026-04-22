# One_Logikality

A multi-tenant B2B SaaS platform for AI-powered mortgage document processing. Customers are mortgage lenders, loan servicers, title agencies, and mortgage BPOs.

## The core product idea

One_Logikality is organized around a **foundational layer** and **downstream micro-apps**.

The foundational layer is **ECV** (Extraction, Classification & Validation). It ingests 2,000-page mortgage packets and produces a normalized MISMO 3.6 data layer with page-level evidence citations. Everything else depends on ECV output.

The downstream micro-apps consume ECV data:
- **Title Search & Abstraction** — chain of title, lien search
- **Title Examination** — ALTA Schedule B/C analysis, curative workflow
- **Compliance** — TRID, TILA, RESPA, state-specific disclosure verification
- **Income Calculation** — DTI, income trending, residual income (VA)

Customers subscribe to micro-apps à la carte. ECV is included with every account.

**Per-packet scope.** When a user uploads a packet, they pick which of their enabled apps that specific packet should be scored against — e.g. a title-only packet won't drag down its ECV score with missing-income findings. ECV itself is always in scope; other apps are opt-in per upload. See the "Packet scope" section below for how scoring uses this.

## Multi-tenant admin model

Three distinct personas, three distinct permission scopes:

1. **Platform admin** (Logikality staff) — creates customer organizations, enables/disables subscribed micro-apps for a customer, resets customer admin passwords. Hardcoded credentials in the demo.

2. **Customer admin** (designated admin at the customer org) — invites users to their org, enables/disables subscribed micro-apps for their users, configures organization-level rule set overrides, changes their own password.

3. **Customer user** (invited by customer admin) — uses the micro-apps but cannot change organization configuration or user management.

This model mirrors Title Intelligence Hub (Anthropic's other product). When building new admin-related features, maintain clean role separation — never let customer users see configuration surfaces.

## Three-tier rule configuration

Rule values layer in order of priority:

1. **Industry defaults** — hard-coded in `LOAN_PROGRAMS` (DTI limits per program, chain depth, regulatory framework, etc.). These reflect GSE/HUD/VA/USDA/ALTA standards. Never treat these as customer-editable.

2. **Organization-level overrides** — set by customer admin on the Configuration page. Apply to every packet the org processes. Stored per-program.

3. **Packet-level overrides** — set by underwriter/examiner/compliance officer when processing a specific loan. Apply to one packet only. Stored per-micro-app per-rule.

Helper: `getEffectiveRules(microAppId, programId, packetOverrides, orgOverrides)` computes the layered final value. Use it everywhere rule values are consumed.

## Packet scope

A packet carries a `scoped_app_ids` array (ECV always locked in). Every ECV validation check carries an `app_ids` tuple — there is no "applies to everyone" bucket. `"ecv"` is itself a member of `_ALL_APPS` in `backend/app/pipeline/validate.py`, so foundational extraction-quality checks (doc completeness, page legibility, cross-doc reconciliation) are tagged with `_ALL_APPS` and therefore always in scope. Specialized checks are tagged with just the downstream apps they feed — e.g. DTI belongs to `("income-calc",)`, lien checks to `("title-search", "title-exam")`. A check is in scope for a packet iff its `app_ids` intersects the packet's `scoped_app_ids`; since `"ecv"` is always in `scoped_app_ids`, any check tagged with `_ALL_APPS` (or containing `"ecv"`) is always in scope.

At dashboard render time:
- Per-section score recomputes from **in-scope** items only
- Overall weighted score ignores out-of-scope sections
- Severity counts (critical / review / pass) only count in-scope items
- Out-of-scope checks still render in the Section Scores / Items-to-Review tabs, but muted with an "Out of scope" badge so the audit trail stays complete

The Coverage card on the dashboard summarizes pass / review / critical per in-scope app. The content-hash dedupe key also includes scope — same bytes uploaded twice with different scope selections are treated as different packets.

## Loan program handling (Option B — declared + confirmed)

**Not auto-detection.** The customer declares the loan program at upload time via a dropdown. ECV then analyzes documents and produces one of three confirmation states:

- **Confirmed** — documents agree with declaration
- **Conflict** — documents suggest a different program (e.g., no FHA case number when FHA was declared)
- **Inconclusive** — insufficient evidence

The declared program drives rule set selection end-to-end. Overrides work at both program level (swap entire rule set) and rule level (edit individual rules).

## MISMO 3.6 as the data spine

Every extracted field is tagged with its MISMO 3.6 path. Every validation finding cites specific MISMO fields. Cross-app references (title exam citing extraction from URLA) use MISMO field IDs, not free-text. Export is MISMO XML.

This is a central platform differentiator. Don't introduce proprietary field naming where MISMO equivalents exist.

## AI model strategy

Use the right model for the right job:

- **Classification** — Gemini 2.5 Flash (high volume, simple decisions, 25 doc classes) via Vertex AI
- **Extraction** — Gemini 2.5 Pro (nuanced, schema-driven, MISMO 3.6 field extraction) via Vertex AI
- **Validation & reasoning** — Claude Sonnet 4 (judgment fields, causality, reconciliation) via Anthropic API

All model keys are cloud-side secrets. Never expose them to the browser. Adapters live in `backend/app/adapters/llm_vertex.py` and `backend/app/adapters/llm_anthropic.py` — every LLM call in the pipeline routes through these.

## How the pipeline runs

Upload handler persists the packet synchronously, then schedules `run_ecv_stub(packet_id)` as a FastAPI `BackgroundTask`. The stub orchestrates six stages (`ingest → classify → extract → validate → score → route`) and stamps `current_stage` on the packet row after each, so the frontend's pipeline animation can poll and sync.

The three LLM stages are the real work:

1. **Classify** (`pipeline/classify.py`) — splits the PDF into 50-page batches, asks Gemini Flash to label each page with a MISMO 3.6 document class, then groups consecutive same-class pages into `EcvDocument` rows. Batches fan out under a 5-wide semaphore.

2. **Extract** (`pipeline/extract.py`) — for every classified document, asks Gemini Pro to emit MISMO 3.6 `(mismo_path, value, confidence, page, snippet)` tuples. Persisted as `EcvExtraction` rows. Per-doc calls fan out under a 5-wide semaphore — this is the biggest wall-clock cost and the biggest parallelism win.

3. **Validate** (`pipeline/validate.py`) — for each of 13 industry-standard ECV sections, asks Claude Sonnet to grade that section's 3–5 line-item checks against the extraction bundle. Writes `EcvSection` + `EcvLineItem`. Section calls fan out under a 4-wide semaphore; row-building stays sequential to preserve the post-flush section_id binding.

Failures inside each fan-out coroutine degrade to empty / zero-confidence rather than killing the batch — one bad doc or section doesn't sink the packet.

The BackgroundTask / stub layer is a bridge to the Temporal workflow landing later (`pipeline/worker.py` is scaffolded). When the workflow replaces it, the per-stage implementations stay as-is; only orchestration moves.

## Architecture philosophy (read this before adding new features)

Deterministic pipelines form the backbone. Agent-shaped components are called at specific points for work that genuinely requires iteration — title exception resolution, income reconciliation across conflicting sources, curative workflow planning, conversational Q&A on a packet.

**Don't default to agents for everything.** Rule application, classification, MISMO export, and workflow orchestration should be code. Agents are components invoked by the pipeline, not the pipeline itself.

Every decision that changes a loan outcome goes through a human-in-the-loop gate.

**Concurrency, not agents, is the default for scale.** LLM calls within a stage (classify batches, extract docs, validate sections) run concurrently via `asyncio.gather` with per-stage semaphores. Each coroutine is independent; session handling stays simple because each stage closes its DB session before the gather and opens a fresh one for the single bulk insert after.

## Current state (what's shipped)

One source of truth for "is this done?" — match against [`docs/Plan.md`](./docs/Plan.md) for phase-level detail.

**Shipped:**
- Phase 0–2: dev stack, multi-tenant schema with Postgres RLS on `org_id`, platform-admin CRUD, customer-admin users + apps + password surfaces
- Phase 3: upload → real ECV pipeline (Vertex Flash classify / Pro extract / Claude Sonnet validate) → dashboard with 13 sections, severity classification, loan-program confirmation (Confirmed / Conflict / Inconclusive), packet-level program override
- Phase 4: three-tier rule layering with `getEffectiveRules` resolver, `ConfigApplied` badges, org-config draft/save/reset
- Phase 5: app gating, BLOCKS indicators, MISMO-keyed cross-app references
- Phase 6: Compliance, Income Calculation, Title Search, Title Examination micro-apps (all four)
- Phase 7: AI transparency + MISMO extraction — **colocated in each app page** rather than shared components (see "Things to know" below)
- Phase 8: PDF + MISMO 3.6 XML exports per app, send-to-manual-review
- Beyond the original plan: packet-scope (`scoped_app_ids`), content-hash file dedupe, pipeline LLM-call parallelization

**Not yet shipped:**
- Temporal workflow replacing the BackgroundTask stub (worker is scaffolded, task queue `ecv` stub)
- Real auth/RBAC — the current demo uses hardcoded seed credentials
- Production persistence (replacing the frontend `demo-store` Context where it still lingers)
- Vertex Document AI for image-only PDFs — current classify/extract uses pypdf text

### Things to know that aren't obvious from the code

- **Phase 7 primitives are inlined, not shared.** `AiNote`, `AiRecommendation`, `MismoPanel`, `EvidencePanel`, `ReviewDialog` were planned as `components/shared/*`, but landed as per-page inline functions inside each micro-app (`frontend/app/[orgSlug]/apps/*/page.tsx`). Treat them as per-app variants for now. If you find yourself copying the third variant, that's your cue to extract.
- **The `ecv_stub.py` "stub" calls real LLMs.** "Stub" refers to the orchestration, not the AI. Tests monkeypatch the top-level pipeline entrypoints to keep runs hermetic.
- **Content-hash dedupe includes scope.** The same bytes uploaded twice with different `scoped_app_ids` are different packets by design.

## Brand and styling

**Authoritative brand source:** [`docs/Logikality_Brand_Guidelines.pdf`](./docs/Logikality_Brand_Guidelines.pdf) is the single source of truth for all Logikality logos, wordmarks, brand colors, typography, and usage rules. Consult it before introducing any brand-adjacent asset or color.

Working summary (must stay in sync with the PDF — if there is a conflict, the PDF wins):

**Primary palette**
- Teal `#01BAED` — primary brand color, CTAs
- Purple `#BD33A4` — accents, highlights
- Orange / Gold `#FCAE1E` — emphasis, alerts

**Secondary palette**
- Charcoal `#1A1A2E` — backgrounds, text
- Dark Gray `#53585F` — body text
- White `#FFFFFF` — backgrounds, contrast

**Typography**
- Primary typeface: **Proxima Nova** (Extrabold = headlines, Bold = subheadings, Regular = body)
- Fallback stack: Arial, Helvetica, sans-serif

**Voice**
- Decisive / Intelligent / Authentic / Direct. Tagline: "Transformation first, AI second — We deliver decisions, not documents."

**Logo usage**
- **Never recreate or approximate the Logikality logo.** Always use the approved logo files per `docs/Logikality_Brand_Guidelines.pdf`, copied into `frontend/public/` (e.g. `logikality_with_tagline.png`, `Logo_withTagline.svg`, `Logo_rev_no-tagline.svg`). Do not redraw, re-trace, or inline the logo as SVG.
- Two approved variants: **Primary** (reverse / no-tagline, for dark backgrounds) and **Secondary** (with tagline, for light backgrounds).
- Clear space: equal to the `o` in "logikality". Minimum width: 100px. Do not stretch, distort, or alter logo colors.

**Visual parity with Title Intelligence Hub** (the other Logikality product line). Same palette, same typography, same card styling, same form conventions. Platform admin and customer admin chrome should look visually consistent within the product.

## Build conventions

- **Next.js** App Router (currently v16 / React 19 in the prototype)
- **No CSS files** — inline styles via React style props, using brand tokens from `lib/brand.ts`
- **State** — the prototype uses a React Context `demo-store`; production will need real persistence. Don't over-invest in the current demo-store pattern
- **Files over folders** for small features — don't create deep nesting for single-page sections
- **Icons** are inline SVG, not an icon library, for crisp rendering at any scale

## Development

Full local stack (Postgres :5437, Temporal :7234 + UI :8086, FastAPI :8001, Temporal worker, Next.js :9999):

```bash
./start-dev.sh                     # full bring-up; Ctrl+C tears everything down
```

One-time setup:

```bash
cp .env.example .env
cd backend && python3.12 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && cd ..
cd frontend && npm install && cd ..
npm install                        # repo-root tooling: lefthook + commitlint
brew install gitleaks              # macOS; `scoop install gitleaks` on Windows
```

Backend (`cd backend`, venv active):

```bash
.venv/bin/uvicorn app.main:app --reload --port 8001
.venv/bin/alembic upgrade head
.venv/bin/alembic revision --autogenerate -m "<message>"
.venv/bin/pytest                               # all tests
.venv/bin/pytest tests/test_health.py::test_x  # single test
.venv/bin/ruff check . && .venv/bin/ruff format .
```

Frontend (`cd frontend`):

```bash
npm run dev          # next dev -p 9999
npm run build
npm run lint         # eslint .
npm run test         # vitest run
npm run test:watch
```

Git hooks run automatically via lefthook (installed by the root `npm install`): gitleaks + ruff + eslint on staged files pre-commit, commitlint on the message. Use Conventional Commits (`feat(...)`, `fix(...)`, `chore(...)`, etc.).

## Code map

Where the moving parts live. See [docs/TechStack.md](./docs/TechStack.md) for why.

**Backend**
- `backend/app/main.py` — FastAPI entry, `/health`, router wiring
- `backend/app/config.py` — settings from `.env` (pydantic-settings)
- `backend/app/models.py` — SQLAlchemy 2.0 ORM; `org_id` on every tenant-scoped table for RLS
- `backend/app/deps.py` — DI factories for the LLM / storage / queue adapters + auth
- `backend/app/security.py` — password hashing + JWT session helpers
- `backend/app/adapters/{storage,queue,llm}.py` — **driver abstractions**; every env-switched integration (local FS vs S3, Temporal vs background tasks, LLM providers) must go through these. Never branch on env vars directly in business code (see TechStack §15)
- `backend/app/adapters/llm_vertex.py` — Gemini Flash + Pro via Vertex AI
- `backend/app/adapters/llm_anthropic.py` — Claude Sonnet via Anthropic API
- `backend/app/pipeline/classify.py` — Gemini Flash page classifier → `EcvDocument` rows (concurrent batches)
- `backend/app/pipeline/extract.py` — Gemini Pro MISMO field extractor → `EcvExtraction` rows (concurrent per-doc)
- `backend/app/pipeline/validate.py` — Claude Sonnet 13-section validator → `EcvSection` + `EcvLineItem` (concurrent per-section)
- `backend/app/pipeline/ecv_stub.py` — BackgroundTask orchestrator stitching classify / extract / validate + canned micro-app seed data. Temporal replacement lands later
- `backend/app/pipeline/{compliance,income,title_exam,title_search}_data.py` — canned seed rows for the Phase 6 micro-apps until their own pipelines land
- `backend/app/pipeline/worker.py` — Temporal worker process; task queue = `ecv` today, more per micro-app later (see TechStack §5)
- `backend/app/routers/{auth,customer_admin,logikality,packets,compliance,income,title_search,title_exam,debug}.py` — FastAPI routers grouped by feature surface (platform admin lives in `logikality.py`)
- `backend/app/exports.py` — PDF + MISMO 3.6 XML renderers per app
- `backend/alembic/versions/` — schema migrations; run on every bring-up. Notables: `0016` MISMO extractions, `0017` content-hash dedupe, `0018` packet-scoped app IDs
- `backend/tests/` — pytest + pytest-asyncio; `asyncio_mode = "auto"` in `pyproject.toml`. `test_validate.py::test_validate_runs_sections_concurrently` is the perf regression guard for pipeline parallelism

**Frontend**
- `frontend/app/page.tsx` — dual-portal login selector (Customer vs Platform Admin)
- `frontend/app/logikality/` — platform-admin chrome (accounts CRUD, password reset)
- `frontend/app/[orgSlug]/` — customer portal under a tenant slug
  - `page.tsx` — org home
  - `upload/page.tsx` — drag-drop upload + program selector + scope picker
  - `ecv/page.tsx` — dashboard: KPIs, Coverage card, Documents / Sections / Items-to-Review tabs
  - `admin/` — customer-admin surfaces (users, apps, configuration, profile)
  - `apps/{compliance,income-calc,title-search,title-exam}/page.tsx` — the four Phase 6 dashboards
- `frontend/components/sidebar.tsx` — role-aware navigation; Phase 7 AI-transparency primitives are currently inlined into each app page, not shared here
- `frontend/lib/brand.ts` — Logikality palette + typography tokens; **the only source of brand values** for inline styles
- `frontend/public/` — approved Logikality logo files (PDF-sourced — never recreate as SVG)

**Root**
- `docker-compose.yml` — `db` (Postgres :5437), `temporal-db`, `temporal` (:7234), `temporal-ui` (:8086); ports offset from Title Intelligence Hub so both repos can run side by side
- `start-dev.sh` — one-command bring-up (docker + alembic + seed + uvicorn + worker + Next.js)
- `docs/Plan.md` — phase-by-phase requirements and recommended implementation order
- `docs/TechStack.md` — why each piece of the stack was chosen

## Scope distinction: demo vs production

The current repo is a **prototype for stakeholder demos**. Several patterns exist only for demo purposes:

- Hardcoded credentials (`admin@logikality.com`/`admin123`, customer login)
- Single seeded customer ("Acme Mortgage Holdings")
- "Enter admin mode" toggle in sidebar (production will use real RBAC)
- `demo-store.tsx` React Context for all state (production needs real persistence)
- No actual authentication/authorization enforcement

When building production features, don't cargo-cult these demo shortcuts. They exist for demo velocity, not as architectural targets.

## Things to avoid

- Don't recreate the Logikality logo as SVG or inline drawing
- Don't put loan-program-specific rule values under customer configuration (they're industry standards)
- Don't blur the three admin personas — each has distinct permission scope
- Don't introduce proprietary field names where MISMO equivalents exist
- Don't default to "make it an agent" when deterministic code would be faster, cheaper, and more auditable
- Don't use emoji in production UI copy (acceptable as icons in prototypes only)
- Don't add decorative form fields without a clear purpose — every field should earn its place

## What success looks like

Every packet processed produces a defensible decision trail: classified documents, extracted MISMO fields, validation findings with page-level citations, applied rule set (with every override justified), and a final micro-app output that cites its sources. A compliance auditor or regulator asking "why did this loan get approved?" should always have a traceable answer.

@docs/Plan.md
