# One Logikality — Functional Requirements by Phase

Functional-requirements breakdown derived from analysis of the `one-logikality-demo` reference implementation, grouped into logical delivery phases (foundational → advanced). Each phase is independently shippable and builds on prior phases.

> **Note:** File paths below refer to the demo reference codebase (`../one-logikality-demo`) and are included as structural pointers for the production build in this `One_Logikality` project.

> **Multi-tenancy is foundational, not an add-on.** Every tenant-scoped table carries `org_id`; Postgres RLS keyed on `org_id` is enforced from day one (see [TechStack.md §4](./TechStack.md)). The three-persona permission model (platform admin / customer admin / customer user) applies to every UI surface and every API endpoint.

---

## Phase 0 — Dev Environment & Scaffolding

**Goal:** Stand up the local stack described in [TechStack.md](./TechStack.md) so Phase 1 has somewhere to land. The repo is currently docs-only; nothing else can start until this is done.

| # | Requirement | Reference |
|---|-------------|-----------|
| 0.1 | `docker-compose.yml` with `db` (Postgres `5437`), `temporal-db`, `temporal` (`7234`), `temporal-ui` (`8086`) — port offsets chosen to coexist with Title Intelligence Hub | [TechStack.md §11](./TechStack.md) |
| 0.2 | `.env.example` committed with all variables from [TechStack.md §14](./TechStack.md); `.env` gitignored | — |
| 0.3 | FastAPI skeleton on port `8001` with `/health`; Alembic initialized; SQLAlchemy 2.0 async + asyncpg wired | [TechStack.md §3–4](./TechStack.md) |
| 0.4 | Next.js 16 / React 19 scaffold on port `9999`; `lib/brand.ts` exporting the Logikality palette (teal `#01BAED` primary, purple `#BD33A4` accent, orange `#FCAE1E` emphasis, charcoal `#1A1A2E`, dark gray `#53585F`) + Proxima Nova typography per `CLAUDE.md`; approved logo assets copied into `frontend/public/` | `CLAUDE.md` (Brand and styling), `docs/Logikality_Brand_Guidelines.pdf` |
| 0.5 | `./start-dev.sh` orchestrating docker compose + `alembic upgrade head` + seed + uvicorn + Temporal worker + `next dev` | [TechStack.md §13](./TechStack.md) |
| 0.6 | Lint/format/hooks: Ruff (backend), ESLint + Next.js lint (frontend), `lefthook`, `gitleaks` pre-commit, `commitlint` | [TechStack.md §10](./TechStack.md) |
| 0.7 | Driver abstractions: `StorageAdapter`, `QueueAdapter`, `LLMAdapter` with env-switched implementations (no `NODE_ENV` branching in business code) | [TechStack.md §15](./TechStack.md) |

**Exit criteria:** `./start-dev.sh` brings the stack up; UI renders a blank page with the correct Logikality logo and the teal-primary palette; `/health` returns 200; Temporal UI reachable at `http://localhost:8086`.

---

## Phase 1 — Platform Foundation & Multi-Tenant Setup

**Goal:** Establish the platform-admin portal and multi-tenant account model.
**User stories:** [UserStories.md § Phase 1](./UserStories.md#phase-1--platform-foundation--multi-tenant-setup)

| # | Requirement | Reference Location |
|---|-------------|--------------------|
| 1.1 | Dual-portal login selector (Customer vs Platform Admin) | `app/page.tsx` |
| 1.2 | Platform-admin authentication (`admin@logikality.com`) | `app/platform-admin/login/page.tsx` |
| 1.3 | Customer-org login with org-scoped credentials | `app/customer/login/page.tsx` |
| 1.4 | Three-tier role model: `platform-admin` / `customer-admin` / `customer-user` | `stores/demo-store.tsx` |
| 1.5 | Platform admin — list customer accounts + KPIs (orgs, users, subscriptions) | `app/platform-admin/accounts/page.tsx` |
| 1.6 | Platform admin — create new customer account (org name, type, primary admin) | `app/platform-admin/accounts/new/page.tsx` |
| 1.7 | Platform admin — edit account, reset admin password, delete account | `app/platform-admin/accounts/[id]/page.tsx` |
| 1.8 | Platform admin — change own password | `app/platform-admin/profile/page.tsx` |
| 1.9 | Role-aware sidebars (customer vs platform-admin navigation) | `components/shared/sidebar.tsx`, `platform-admin-sidebar.tsx` |

---

## Phase 2 — Customer Org Administration

**Goal:** Let customer admins manage their team, app access, and credentials.
**User stories:** [UserStories.md § Phase 2](./UserStories.md#phase-2--customer-org-administration)

| # | Requirement | Reference Location |
|---|-------------|--------------------|
| 2.1 | Customer admin — change password (with current-password verification) | `app/customer/admin/profile/page.tsx` |
| 2.2 | Invite team members by email + name + role (Admin/Member) | `app/customer/admin/users/page.tsx` |
| 2.3 | Auto-generate temp password + copy-to-clipboard distribution | `app/customer/admin/users/page.tsx` |
| 2.4 | Remove team members (primary admin protected) | `app/customer/admin/users/page.tsx` |
| 2.5 | Two-tier app model — **subscribed** (platform-admin controlled) vs **enabled** (customer-admin controlled) | `stores/demo-store.tsx` |
| 2.6 | Customer admin — enable/disable subscribed apps; ECV always required | `app/customer/admin/apps/page.tsx` |

---

## Phase 3 — Document Ingestion & ECV Core

**Goal:** Upload packets and run the foundational ECV (Extraction, Classification & Validation) app.
**User stories:** [UserStories.md § Phase 3](./UserStories.md#phase-3--document-ingestion--ecv-core)

| # | Requirement | Reference Location |
|---|-------------|--------------------|
| 3.1 | Drag-drop + file picker for PDF/PNG/JPEG packet upload | `app/customer/upload/page.tsx` |
| 3.2 | Loan-program selector at upload (Conventional/VA/FHA/USDA/Jumbo) | `app/customer/upload/page.tsx` |
| 3.3 | Program-specific rule preview on upload (DTI limit, chain depth, framework) | `app/customer/upload/page.tsx` |
| 3.4 | Multi-stage pipeline animation: OCR → Classify → Validate → Analyze | `components/shared/pipeline-progress.tsx` |
| 3.5 | ECV overall weighted score + 90% auto-approve threshold | `app/customer/ecv/page.tsx` |
| 3.6 | 13 validation sections × 60+ line-item checks with confidence % | `lib/demo-data.ts` (`ECV_SECTIONS`, `ECV_LINE_ITEMS`) |
| 3.7 | Severity classification: CRITICAL (<50%) / REVIEW (50–85%) / PASS (≥85%) | `app/customer/ecv/page.tsx` |
| 3.8 | ECV Documents tab — inventory of ~25 MISMO 3.6 doc classes with found/missing + page quality flags | `app/customer/ecv/page.tsx` |
| 3.9 | ECV Section Scores tab — expandable sections with per-check drill-down | `app/customer/ecv/page.tsx` |
| 3.10 | ECV Items-to-Review tab — unified sub-85% list with severity filter | `app/customer/ecv/page.tsx` |
| 3.11 | Loan-program confirmation (Option B: declared + confirmed) — three states: **Confirmed** / **Conflict** (suggests alternative) / **Inconclusive** | `lib/demo-data.ts` (`CONFIRMATION_ANALYSIS`) |
| 3.12 | Packet-level program override dialog with reason | `components/shared/override-dialog.tsx` |
| 3.13 | Sticky action bar: Approve / Reject / Export PDF / Send to manual review | `app/customer/ecv/page.tsx` |

---

## Phase 4 — Rule & Configuration System

**Goal:** Three-level rule layering: industry defaults → org overrides → packet overrides.
**User stories:** [UserStories.md § Phase 4](./UserStories.md#phase-4--rule--configuration-system)

| # | Requirement | Reference Location |
|---|-------------|--------------------|
| 4.1 | Industry-default rule library per program | `lib/demo-data.ts` (`LOAN_PROGRAMS`, `MICRO_APP_RULES`) |
| 4.2 | Org-level rule overrides per program/app (customer admin) | `app/customer/admin/configuration/page.tsx` |
| 4.3 | Packet-level rule overrides with reason + actor + timestamp | `stores/demo-store.tsx` (`packetRuleOverrides`) |
| 4.4 | Effective-rule resolver layering all three levels | `lib/effective-rules.ts` |
| 4.5 | `ConfigApplied` badge on every app showing which rules were used | `components/shared/config-applied.tsx` |
| 4.6 | Rule editor dialog (number, select, toggle field types) | `components/shared/edit-rules-dialog.tsx` |
| 4.7 | Draft/save pattern with unsaved-changes warning + reset-to-defaults | `app/customer/admin/configuration/page.tsx` |

---

## Phase 5 — App Gating & Cross-App Dependencies

**Goal:** Prevent downstream apps from running without required documents; link findings across apps.
**User stories:** [UserStories.md § Phase 5](./UserStories.md#phase-5--app-gating--cross-app-dependencies)

| # | Requirement | Reference Location |
|---|-------------|--------------------|
| 5.1 | Required-docs mapping per micro-app | `lib/demo-data.ts` (`APP_REQUIRED_DOCS`) |
| 5.2 | Blocked-app dialog when required docs missing + "Proceed Anyway" option | `components/shared/blocked-app-dialog.tsx` |
| 5.3 | Sidebar "BLOCKS [App]" indicators on missing docs | `app/customer/ecv/page.tsx` |
| 5.4 | Cross-app reference links keyed by **MISMO 3.6 field IDs** (not free-text) between related findings | `components/shared/cross-app-ref.tsx` |

---

## Phase 6 — Downstream Micro-Apps

**Goal:** Specialized analysis apps that consume ECV output.
**User stories:** [UserStories.md § Phase 6](./UserStories.md#phase-6--downstream-micro-apps)

| # | Requirement | Reference Location |
|---|-------------|--------------------|
| 6.1 | **Title Search & Abstraction** — chain-of-title, 7 risk flags, property summary | `app/customer/apps/title-search/page.tsx` |
| 6.2 | **Title Examination** — ALTA Schedule B/C analysis, standard + specific exceptions, requirements, warnings, **curative workflow** | `app/customer/apps/title-exam/page.tsx`, `title-results/page.tsx` |
| 6.3 | **Compliance** — TRID / TILA / RESPA / ECOA / state-specific / HMDA checks + fee-tolerance table | `app/customer/apps/compliance/page.tsx` |
| 6.4 | **Income Calculation** — base/overtime/bonus/rental sources, trend analysis, DTI rollup | `app/customer/apps/income-calc/page.tsx` |
| 6.5 | Risk summary cards (critical/high/medium/low counts) on each app | `components/shared/risk-summary-cards.tsx` |
| 6.6 | Tab-based navigation pattern across all apps (Overview / Details / Results / Export) | Multiple |

---

## Phase 7 — AI Transparency & MISMO Integration

**Goal:** Surface AI reasoning and structured-data extractions alongside findings.
**User stories:** [UserStories.md § Phase 7](./UserStories.md#phase-7--ai-transparency--mismo-integration)

| # | Requirement | Reference Location |
|---|-------------|--------------------|
| 7.1 | `AiNote` callout explaining guideline reference / reasoning per finding | `components/shared/ai-note.tsx` |
| 7.2 | `AiRecommendation` badge: Approve / Reject / Escalate with confidence | `components/shared/ai-recommendation.tsx` |
| 7.3 | MISMO **3.6** field-level extraction panel (entity → MISMO path → value + confidence) | `components/shared/mismo-panel.tsx` |
| 7.4 | Evidence panel showing source-document snippets with page references | `components/shared/evidence-panel.tsx` |
| 7.5 | Review dialog aggregating AI note + MISMO + evidence per flag | `components/shared/review-dialog.tsx` |

---

## Phase 8 — Export & Reporting

**Goal:** Produce downstream artifacts for downstream systems and manual review.
**User stories:** [UserStories.md § Phase 8](./UserStories.md#phase-8--export--reporting)

| # | Requirement | Reference Location |
|---|-------------|--------------------|
| 8.1 | Export PDF report per app | Header buttons on each app page |
| 8.2 | Export **MISMO 3.6 XML** per app | Header buttons on each app page |
| 8.3 | Send-to-manual-review pathway from ECV | `app/customer/ecv/page.tsx` |

---

## Recommended Implementation Order

Phase numbers above are a **requirements grouping**, not the build order. The sequence below rearranges a few phases to avoid known rework traps — specifically, building the rule resolver before ECV consumes it, building AI transparency primitives alongside ECV (not after), and locking MISMO-keyed cross-app references before any Phase 6 app is written.

### Step 0 — Dev environment & scaffolding
Deliver **Phase 0** end-to-end. Blocking for everything else.

### Step 1 — Auth + multi-tenant spine
From **Phase 1**: data model (`orgs`, `users`, `role` enum, `org_id` on all tenant-scoped tables), **Postgres RLS keyed on `org_id` from day one**, JWT login, seed script (platform admin + "Acme Mortgage Holdings" + primary customer-admin), dual-portal login selector + both login pages (US-1.1 – 1.3), role-aware sidebar shell (US-1.9).
- **Why first:** every later screen is role-scoped. Retrofitting RLS is painful.
- **Exit:** all three roles log in, land in the right portal, see only their sidebar.

### Step 2 — Finish Phase 1, then Phase 2
Platform-admin CRUD (US-1.5 – 1.8). Subscriptions-vs-enablement data model (US-2.5) — stand this up now because Phase 3 and Phase 5 both extend it. Customer-admin surfaces (US-2.1 – 2.6).
- **Exit:** platform admin can spin up a customer; customer admin can invite users and toggle subscribed apps; ECV is locked on.

### Step 3 — Rule system primitives *(pulls Phase 4 ahead of Phase 3)*
Deliver **Phase 4** now, before ECV.
- **Why ahead of Phase 3:** ECV is the first rule consumer. Building ECV first guarantees hardcoded rule values and a later rewrite.
- Scope: industry defaults (US-4.1), `getEffectiveRules` resolver with unit tests (US-4.4), rule editor dialog + `ConfigApplied` badge (US-4.5 – 4.6), org-level configuration page with draft/save + reset (US-4.2, 4.7), packet-override schema and APIs (US-4.3) — the packet-override UI lands with ECV in Step 4.

### Step 4 — Phase 3 ECV core *(with Phase 7 primitives alongside)*
Biggest slice. Build in this internal order:
1. Upload page: drag-drop, program selector, rule preview (US-3.1 – 3.3).
2. Storage adapter + packet persistence.
3. Temporal worker + ECV workflow skeleton (OCR → Classify → Extract → Validate → Analyze); start with deterministic stubs, then wire LiteLLM; SSE for progress (US-3.4).
4. **Pull Phase 7 primitives forward here, not after:** `AiNote`, `AiRecommendation`, `MismoPanel`, `EvidencePanel`, `ReviewDialog` (US-7.1 – 7.5). Every finding the pipeline emits must carry `(document_id, page, MISMO_3.6_path, text_snippet)` from the first run — retrofitting evidence means re-persisting every finding.
5. ECV dashboard: overall score + 90% threshold, Documents / Section Scores / Items-to-Review tabs, severity classification, sticky action bar (US-3.5 – 3.10, 3.13).
6. Loan-program confirmation states + packet override dialog (US-3.11 – 3.12), wiring into Step 3's packet-override plumbing.
- **Exit:** user uploads a packet, watches the pipeline, sees findings with AI note/MISMO/evidence, and `ConfigApplied` shows rule sources.

### Step 5 — Phase 5 gating
Required-docs mapping (US-5.1), sidebar BLOCKS indicators and blocked-app dialog (US-5.2 – 5.3), **cross-app references stored as MISMO 3.6 field ID pairs** (US-5.4).
- **Why before any Phase 6 app:** locking MISMO-keyed refs now prevents every micro-app from shipping free-text refs and needing rework.

### Step 6 — First downstream app: Compliance
Deliver **US-6.3** as a vertical slice. Extract the reusable pieces as you go: risk summary cards (US-6.5), consistent tab shell (US-6.6), `ConfigApplied` on the app header.
- **Why Compliance first** (not Title Search): no curative state machine, so the reusable app shell is validated end-to-end faster.

### Step 7 — Remaining micro-apps (easiest → hardest)
1. **Income Calculation** (US-6.4) — shares structure with Compliance; layer in Vertex Document AI for W-2 / 1040 / paystub / URLA / CD per [TechStack.md §8](./TechStack.md).
2. **Title Search & Abstraction** (US-6.1) — introduces chain-of-title UI.
3. **Title Examination** (US-6.2) — last, because of the curative workflow (state machine, assignees, cleared/not-cleared).

### Step 8 — Phase 8 exports + polish
PDF report with brand-compliant cover / header / footer (US-8.1), MISMO 3.6 XML export (US-8.2), send-to-manual-review (US-8.3). Harden Playwright coverage across the critical paths.

### Deviations from a strict phase-number order
| Deviation | Reason |
|-----------|--------|
| Phase 4 before Phase 3 | Rule resolver must exist before ECV consumes it, or ECV hardcodes rules and gets rewritten. |
| Phase 7 primitives built alongside Phase 3, not after | Findings must carry `(document_id, page, MISMO path, snippet)` from the first pipeline run. |
| US-5.4 (MISMO-keyed cross-app refs) before any Phase 6 app | Prevents every micro-app shipping free-text refs and needing rework. |
| Compliance first among Phase 6 apps (not Title Search) | No state machine — faster validation of the reusable app shell. |

---

## Tech Stack

See [TechStack.md](./TechStack.md) for the local-development stack. Production/staging AWS stack is TBD. AI model strategy (Gemini 2.5 Flash for classification, Gemini 2.5 Pro for extraction, Claude Sonnet 4 for validation & reasoning) is defined in `CLAUDE.md`.

## Scope Note: Production vs. Demo

The paths in the tables above reference the demo prototype (`../one-logikality-demo`) for structural orientation only. Per `CLAUDE.md`, several demo patterns are explicitly **not** production targets:

- Hardcoded credentials, the single seeded "Acme Mortgage Holdings" org, and the sidebar "Enter admin mode" toggle exist for demo velocity — production uses real auth + RBAC.
- `demo-store.tsx` React Context is demo-only; production needs real persistence.
- Every loan-outcome decision must pass through a **human-in-the-loop gate** in production.
