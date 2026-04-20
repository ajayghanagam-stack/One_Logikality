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

- **Classification** — Gemini 2.5 Flash (high volume, simple decisions, 25 doc classes)
- **Extraction** — Gemini 2.5 Pro (nuanced, schema-driven, MISMO field extraction)
- **Validation & reasoning** — Claude Sonnet 4 (judgment fields, causality, reconciliation)

All model keys are cloud-side secrets. Never expose them to the browser.

## Architecture philosophy (read this before adding new features)

Deterministic pipelines form the backbone. Agent-shaped components are called at specific points for work that genuinely requires iteration — title exception resolution, income reconciliation across conflicting sources, curative workflow planning, conversational Q&A on a packet.

**Don't default to agents for everything.** Rule application, classification, MISMO export, and workflow orchestration should be code. Agents are components invoked by the pipeline, not the pipeline itself.

Every decision that changes a loan outcome goes through a human-in-the-loop gate.

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

- `backend/app/main.py` — FastAPI entry, `/health`, router wiring
- `backend/app/config.py` — settings from `.env` (pydantic-settings)
- `backend/app/adapters/{storage,queue,llm}.py` — **driver abstractions**; every env-switched integration (local FS vs S3, Temporal vs background tasks, LiteLLM providers) must go through these. Never branch on env vars directly in business code (see TechStack §15)
- `backend/app/pipeline/worker.py` — Temporal worker process; task queue = `ecv` today, more per micro-app later (see TechStack §5)
- `backend/alembic/` — schema migrations; run on every bring-up
- `backend/tests/` — pytest + pytest-asyncio; `asyncio_mode = "auto"` in `pyproject.toml`
- `frontend/app/` — Next.js App Router pages
- `frontend/lib/brand.ts` — Logikality palette + typography tokens; **the only source of brand values** for inline styles
- `frontend/public/` — approved Logikality logo files (PDF-sourced — never recreate as SVG)
- `docker-compose.yml` — `db`, `temporal-db`, `temporal`, `temporal-ui`; ports offset from Title Intelligence Hub so both repos can run side by side

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
