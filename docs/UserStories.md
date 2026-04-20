# One Logikality — User Stories & Acceptance Criteria

User stories and acceptance criteria for each phase defined in [Plan.md](./Plan.md). Stories follow the format **As a [role], I want [capability], so that [benefit]**. Acceptance criteria use Given/When/Then.

---

## Cross-Cutting — Brand & Visual Compliance

These stories apply to **every** UI surface in the product and layer on top of the phase-specific stories below.

### US-X.1 — Brand compliance on all UI surfaces
**As the** product owner, **I want** every screen, export, and email to comply with Logikality's brand guidelines, **so that** customer-facing output is consistent and on-brand.
- **Given** any new or modified UI component, **when** it introduces color, typography, or logo usage, **then** it MUST match the values documented in [`docs/Logikality_Brand_Guidelines.pdf`](./Logikality_Brand_Guidelines.pdf) (and, where summarized in `CLAUDE.md`, those values; the PDF wins on conflict).
- **Given** any PR, **when** brand-adjacent changes are reviewed, **then** deviations from the guidelines are flagged as blockers, not style nits.
- **Given** brand tokens are defined, **when** components render color/styling, **then** they consume `lib/brand.ts` tokens — no raw hex literals scattered through components.

### US-X.2 — Approved logo usage only
**As the** product owner, **I want** the Logikality logo to only ever render from approved asset files, **so that** the mark is never degraded, re-traced, or approximated.
- **Given** any screen displays the logo, **when** it renders, **then** it uses an approved raster/SVG file from `/public/` (e.g. `logikality_with_tagline.png`) — not an inline SVG drawing, not a re-traced path, not a CSS/text recreation.
- **Given** a logo is placed, **when** the final render is compared against `docs/Logikality_Brand_Guidelines.pdf`, **then** clear-space, minimum-size, background-contrast, and permitted variant rules are all satisfied.
- **Given** a co-branded surface (e.g. product x Title Intelligence Hub parity), **when** it renders, **then** it uses only the variants the guidelines explicitly permit.

---

## Phase 1 — Platform Foundation & Multi-Tenant Setup

### US-1.1 — Dual-portal login selector
**As a** visitor to the platform, **I want** to choose between Customer and Platform Admin sign-in, **so that** I land in the right portal.
- **Given** I open the root URL, **when** the page loads, **then** I see two clearly labeled entry points (Customer / Platform Admin).
- **Given** I click Customer, **when** the click is registered, **then** I am routed to `/customer/login`.
- **Given** I click Platform Admin, **when** the click is registered, **then** I am routed to `/platform-admin/login`.
- **Given** the page renders, **when** the Logikality mark is displayed, **then** it uses an approved asset from `/public/` and conforms to [`docs/Logikality_Brand_Guidelines.pdf`](./Logikality_Brand_Guidelines.pdf) (clear-space, minimum size, permitted variant). See cross-cutting US-X.1 / US-X.2.

### US-1.2 — Platform-admin authentication
**As a** Logikality staff member, **I want** to sign in with my staff credentials, **so that** I can manage customer accounts.
- **Given** valid credentials, **when** I submit the form, **then** my session is tagged `platform-admin` and I land on the accounts list.
- **Given** invalid credentials, **when** I submit, **then** I see an inline error and remain on the login page.
- **Given** the login screen renders, **when** the Logikality mark and chrome are displayed, **then** both conform to [`docs/Logikality_Brand_Guidelines.pdf`](./Logikality_Brand_Guidelines.pdf) — approved logo asset only, teal `#01BAED` primary palette with orange `#FCAE1E` for emphasis/alerts, Proxima Nova typography. See US-X.1 / US-X.2.

### US-1.3 — Customer-org login
**As a** customer-org user, **I want** to sign in with my org-scoped email + password, **so that** I only see my org's data.
- **Given** valid org credentials, **when** I submit, **then** my session is tagged with the correct role (`customer-admin` or `customer-user`) and I land on my org's home.
- **Given** invalid credentials, **when** I submit, **then** I see an inline error.
- **Given** the login screen renders, **when** the Logikality mark and chrome are displayed, **then** both conform to [`docs/Logikality_Brand_Guidelines.pdf`](./Logikality_Brand_Guidelines.pdf) — approved logo asset only, teal `#01BAED` primary palette, Proxima Nova typography, consistent with the platform-admin login (no visual divergence between portals). See US-X.1 / US-X.2.

### US-1.4 — Three-tier role model
**As a** product owner, **I want** distinct roles (`platform-admin`, `customer-admin`, `customer-user`), **so that** access is scoped correctly.
- **Given** a signed-in user, **when** they navigate, **then** menus, sidebars, and routes reflect only their role's capabilities.
- **Given** a user of lower privilege, **when** they attempt a higher-privilege action, **then** it is not surfaced or is blocked.

### US-1.5 — Platform admin account list + KPIs
**As a** platform admin, **I want** to see all customer accounts with summary KPIs, **so that** I can monitor platform usage at a glance.
- **Given** I open the accounts page, **when** it loads, **then** I see total orgs, active users, and active subscriptions as KPI cards.
- **Given** the accounts table renders, **when** I scan it, **then** each row shows org name, type, admin email, subscribed apps, user count, and created date.

### US-1.6 — Create new customer account
**As a** platform admin, **I want** to create a customer account, **so that** I can onboard new orgs.
- **Given** the new-account form, **when** I submit org name, type, admin name, admin email, admin password, and selected app subscriptions, **then** a new account is created and appears in the accounts list.
- **Given** ECV is in the subscription list, **when** I submit, **then** ECV is forced on regardless of my selection.
- **Given** a missing required field, **when** I submit, **then** the form shows validation errors and no account is created.

### US-1.7 — Edit / reset / delete account
**As a** platform admin, **I want** to edit subscriptions, reset admin password, and delete an account, **so that** I can maintain customers over their lifecycle.
- **Given** an account detail page, **when** I toggle a subscription and save, **then** the change persists and is reflected in the account list.
- **Given** I click Reset Password, **when** I confirm, **then** a new temporary password is generated and displayed for distribution.
- **Given** I click Delete, **when** I confirm, **then** the account is removed from the list.

### US-1.8 — Platform admin profile / password change
**As a** platform admin, **I want** to change my own password, **so that** I can maintain my credentials.
- **Given** I enter my current password and a new password matching confirmation, **when** I submit, **then** the change is saved and I see success feedback.
- **Given** the current password is wrong, **when** I submit, **then** the form errors and nothing is saved.

### US-1.9 — Role-aware sidebars
**As a** signed-in user, **I want** my sidebar to only show what I can access, **so that** the UI is not cluttered with unavailable items.
- **Given** a `platform-admin` session, **when** any page renders, **then** the platform-admin sidebar is shown.
- **Given** a customer session, **when** any page renders, **then** the customer sidebar is shown with only enabled + unblocked apps.
- **Given** either sidebar renders, **when** the Logikality mark is displayed in the sidebar header, **then** it uses an approved asset from `/public/`, honors minimum-size + clear-space rules from [`docs/Logikality_Brand_Guidelines.pdf`](./Logikality_Brand_Guidelines.pdf), and is visually identical across customer and platform-admin sidebars. See US-X.1 / US-X.2.

---

## Phase 2 — Customer Org Administration

### US-2.1 — Customer admin password change
**As a** customer admin, **I want** to change my password with current-password verification, **so that** my account stays secure.
- **Given** I enter current + new + confirmation, **when** I submit and they all validate, **then** the password is updated.
- **Given** the new password is shorter than 6 chars or does not match confirmation, **when** I submit, **then** the form errors and nothing saves.

### US-2.2 — Invite team members
**As a** customer admin, **I want** to invite team members by email, name, and role, **so that** my team can access the platform.
- **Given** the invite form, **when** I submit name + email + role, **then** a new user is added to the org users list.
- **Given** a duplicate email in the org, **when** I submit, **then** the form errors and no user is added.

### US-2.3 — Temp password generation + copy
**As a** customer admin, **I want** a temporary password generated and copyable, **so that** I can share it with the invited user.
- **Given** I complete an invite, **when** the user is created, **then** a temp password is displayed.
- **Given** the temp password is displayed, **when** I click the copy icon, **then** it is copied to my clipboard and I see copy confirmation.

### US-2.4 — Remove team members (primary protected)
**As a** customer admin, **I want** to remove team members (except the primary admin), **so that** I can offboard users.
- **Given** a non-primary member, **when** I click remove and confirm, **then** they are removed from the list.
- **Given** the primary admin row, **when** I look for the remove control, **then** it is not present / is disabled.

### US-2.5 — Two-tier app model (subscribed vs enabled)
**As a** product owner, **I want** platform admins to control subscriptions and customer admins to control enablement, **so that** commercial and operational controls stay separate.
- **Given** an app is not subscribed, **when** a customer admin views the app-access page, **then** it appears in a non-enableable "Unsubscribed" section.
- **Given** an app is subscribed, **when** the customer admin views, **then** it appears in the Subscribed section with an enable/disable toggle.

### US-2.6 — Enable/disable subscribed apps
**As a** customer admin, **I want** to enable or disable subscribed apps for my org, **so that** only the relevant apps appear for my team.
- **Given** I toggle an app off, **when** any org user next loads, **then** that app is absent from their sidebar.
- **Given** the ECV app, **when** I view the page, **then** its toggle is locked on and labeled required.

---

## Phase 3 — Document Ingestion & ECV Core

### US-3.1 — Upload packet (drag-drop + picker)
**As a** customer user, **I want** to upload a packet via drag-drop or a file picker, **so that** I can start ECV analysis.
- **Given** the upload page, **when** I drop or select PDF/PNG/JPEG files, **then** they are listed with name, size, and a delete action.
- **Given** an unsupported file type, **when** I attempt to add it, **then** it is rejected with a clear message.

### US-3.2 — Select loan program at upload
**As a** customer user, **I want** to pick a loan program before analysis, **so that** the correct rules apply.
- **Given** the upload page, **when** I open the program selector, **then** I see Conventional, VA, FHA, USDA, Jumbo.
- **Given** no program is selected, **when** I click Analyze, **then** the action is blocked with a prompt to select.

### US-3.3 — Program-specific rule preview
**As a** customer user, **I want** to see key rules for the selected program before analyzing, **so that** I understand the constraints.
- **Given** I select a program, **when** the selection is applied, **then** I see DTI limit, chain depth, regulatory framework, and guidelines summary.

### US-3.4 — Pipeline animation
**As a** customer user, **I want** to see analysis progress through discrete stages, **so that** I have confidence the system is working.
- **Given** I click Analyze, **when** processing starts, **then** the pipeline shows stages Upload → OCR → Classify → Validate → Analyze → Complete.
- **Given** processing completes, **when** the final stage finishes, **then** I am routed to the ECV dashboard.

### US-3.5 — ECV overall score + auto-approve threshold
**As a** reviewer, **I want** a weighted overall ECV score with a 90% auto-approve threshold, **so that** I know when manual review is required.
- **Given** the ECV page renders, **when** the score is ≥ 90%, **then** the Approve action is enabled.
- **Given** the score is < 90%, **when** the page renders, **then** a "Manual review required" banner shows and Approve is disabled.

### US-3.6 — 13 sections × line-item checks with confidence
**As a** reviewer, **I want** each validation section to expand into line-item checks with confidence %, **so that** I can drill into results.
- **Given** a section row, **when** I expand it, **then** its line items appear with description, result, and confidence %.

### US-3.7 — Severity classification
**As a** reviewer, **I want** each check tagged as CRITICAL / REVIEW / PASS based on confidence, **so that** I can triage quickly.
- **Given** confidence < 50%, **then** the item is CRITICAL.
- **Given** confidence 50–85%, **then** the item is REVIEW.
- **Given** confidence ≥ 85%, **then** the item is PASS.

### US-3.8 — Documents tab (inventory + quality flags)
**As a** reviewer, **I want** a document inventory with found/missing status and page-quality flags across the ~25 MISMO 3.6 doc classes, **so that** I can see packet completeness.
- **Given** the Documents tab, **when** it renders, **then** docs are grouped by category with MISMO 3.6 class, status, confidence, and page numbers.
- **Given** a page has quality issues (blank, low-res, rotated), **when** the tab renders, **then** those flags are surfaced on the doc.

### US-3.9 — Section Scores tab
**As a** reviewer, **I want** a section-scores view with drill-down, **so that** I can compare section performance.
- **Given** the Section Scores tab, **when** it renders, **then** all 13 sections show weighted score + bar.
- **Given** I click a section, **when** it expands, **then** its line items are listed.

### US-3.10 — Items to Review tab
**As a** reviewer, **I want** a unified list of sub-85% items with severity filter, **so that** I can focus on the weakest checks.
- **Given** the tab renders, **when** I apply the Critical filter, **then** only items < 50% confidence are shown.
- **Given** the tab renders, **when** I apply the Review filter, **then** only items 50–85% confidence are shown.
- **Given** the list renders, **when** I scan it, **then** items are sorted by confidence ascending.

### US-3.11 — Loan-program confirmation (Option B: declared + confirmed)
**As a** reviewer, **I want** ECV to confirm my declared program against evidence, **so that** I catch mismatches early.
- **Given** documents support the declared program, **when** ECV computes, **then** the status pill reads **Confirmed**.
- **Given** documents suggest a different program, **when** ECV computes, **then** the pill reads **Conflict** and a suggested alternative is shown.
- **Given** evidence is insufficient, **when** ECV computes, **then** the pill reads **Inconclusive**.
- **Given** any state, **when** downstream rule resolution runs, **then** the declared program drives the rule set end-to-end (not auto-detection).

### US-3.12 — Packet-level program override with reason
**As a** reviewer, **I want** to change the declared program with a reason captured, **so that** decisions are auditable.
- **Given** I click Change program, **when** the override dialog opens, **then** I must enter a reason and select a new program.
- **Given** I confirm the override, **when** it saves, **then** downstream rules recalculate and an override marker shows in the UI.

### US-3.13 — Sticky action bar
**As a** reviewer, **I want** Approve / Reject / Export PDF / Send-to-manual-review actions pinned at the bottom, **so that** I can act from anywhere on the page.
- **Given** the ECV page, **when** I scroll, **then** the action bar remains visible.
- **Given** the score < 90%, **when** the bar renders, **then** Approve is disabled with a tooltip explaining why.

---

## Phase 4 — Rule & Configuration System

### US-4.1 — Industry-default rules per program
**As a** product owner, **I want** an immutable library of industry-default rules per program, **so that** overrides are always measured against a known baseline.
- **Given** any rule resolution, **when** no overrides exist, **then** the industry default value is applied.

### US-4.2 — Org-level rule overrides
**As a** customer admin, **I want** to override rules per program and per app for my org, **so that** my team works with our policies.
- **Given** the configuration page, **when** I select a program and an app, **then** I see the editable rules for that combination.
- **Given** I edit and save, **when** the save completes, **then** future packets for that program use the new values.

### US-4.3 — Packet-level overrides with audit fields
**As a** reviewer, **I want** to override a rule on a specific packet with a reason, **so that** exceptions are tracked.
- **Given** I open a rule editor on a packet, **when** I change a value, **then** I must provide a reason.
- **Given** an override is saved, **when** I view it, **then** the reason, actor, and timestamp are visible.

### US-4.4 — Effective-rule resolver (three-level)
**As a** developer, **I want** a resolver that layers industry default → org override → packet override, **so that** apps get one effective ruleset.
- **Given** overrides exist at each level, **when** the resolver runs, **then** packet > org > default precedence is applied.
- **Given** a rule has no overrides, **when** the resolver runs, **then** the industry default is returned with no override flag.

### US-4.5 — ConfigApplied badge
**As a** reviewer, **I want** each app to show which rules were applied and from which level, **so that** results are transparent.
- **Given** an app page loads, **when** I view the header area, **then** a ConfigApplied badge lists the key rules and their source (default/org/packet).

### US-4.6 — Rule editor dialog (number/select/toggle)
**As a** customer admin or reviewer, **I want** a single editor that supports number, select, and toggle rule fields, **so that** editing is consistent.
- **Given** a rule of any supported type, **when** I open the editor, **then** the correct input is rendered and validates on save.

### US-4.7 — Draft/save with reset to defaults
**As a** customer admin, **I want** a draft/save pattern with unsaved-changes warning and reset-to-defaults, **so that** I can experiment safely.
- **Given** I change a value, **when** I attempt to leave without saving, **then** I see an unsaved-changes warning.
- **Given** I click Reset to defaults, **when** I confirm, **then** all overrides for the selected program clear back to industry defaults.

---

## Phase 5 — App Gating & Cross-App Dependencies

### US-5.1 — Required-docs mapping per app
**As a** product owner, **I want** each micro-app to declare its required MISMO doc types, **so that** gating is deterministic.
- **Given** an app's required-docs list, **when** ECV resolves the packet, **then** the app's blocked/unblocked status is computed from inventory.

### US-5.2 — Blocked-app dialog with Proceed Anyway
**As a** reviewer, **I want** a clear blocking dialog when required docs are missing, with the option to proceed anyway, **so that** I can make an informed choice.
- **Given** an app is blocked, **when** I click it, **then** a dialog lists missing documents and shows Cancel / Proceed Anyway.
- **Given** I click Proceed Anyway, **when** the app loads, **then** a banner indicates partial-data mode.

### US-5.3 — Sidebar BLOCKS indicators
**As a** reviewer, **I want** ECV to show which apps are blocked by missing docs, **so that** I can prioritize collecting them.
- **Given** a missing doc blocks an app, **when** the ECV sidebar renders, **then** a "BLOCKS [App]" indicator appears on that doc.

### US-5.4 — Cross-app reference links (MISMO-keyed)
**As a** reviewer, **I want** findings to link to related findings in other apps by MISMO 3.6 field ID, **so that** cross-references are machine-readable and auditable (not free-text).
- **Given** a finding references another app's data, **when** it is persisted, **then** the reference is stored as a MISMO 3.6 field ID pair.
- **Given** a finding has cross-app references, **when** I view it, **then** I see links that navigate to the related finding in the target app.

---

## Phase 6 — Downstream Micro-Apps

### US-6.1 — Title Search & Abstraction
**As a** title reviewer, **I want** a chain-of-title view with risk flags and a property summary, **so that** I can assess title health.
- **Given** the app loads, **when** the Overview tab renders, **then** I see property summary, risk KPI cards, and a chain-of-title timeline.
- **Given** a flag, **when** I open it, **then** I see severity, description, page ref, AI note, recommendation, MISMO fields, and evidence.

### US-6.2 — Title Examination (ALTA B/C + curative workflow)
**As a** title examiner, **I want** ALTA Schedule B/C analysis with exceptions, requirements, warnings, and a curative workflow, **so that** I can clear defects and produce an examination report.
- **Given** the results view, **when** it renders, **then** ALTA Schedule B/C sections, standard + specific exceptions, requirements, and warnings are all visible.
- **Given** an open exception or requirement, **when** I enter the curative workflow, **then** I can record curative steps, assignees, and cleared/not-cleared status against that item.

### US-6.3 — Compliance
**As a** compliance reviewer, **I want** TRID / TILA / RESPA / ECOA / state-specific / HMDA checks plus a fee-tolerance table, **so that** I can verify regulatory compliance.
- **Given** the Overview tab, **when** it renders, **then** each check shows Pass / Fail / Warn / N/A with a reason.
- **Given** the Tolerances tab, **when** it renders, **then** LE vs CD fees are compared against 0% / 10% / Unlimited buckets with dollar and percent deltas.

### US-6.4 — Income Calculation
**As an** underwriter, **I want** base/overtime/bonus/rental income with trends and a DTI rollup, **so that** I can qualify the borrower.
- **Given** the Income Sources tab, **when** it renders, **then** each source shows monthly + annual amounts, documentation, and trend.
- **Given** the DTI tab, **when** it renders, **then** total income, total debt, DTI ratio, and guideline status are shown.

### US-6.5 — Risk summary cards
**As a** reviewer, **I want** per-app risk KPI cards (critical/high/medium/low), **so that** I can triage severity at a glance.
- **Given** any micro-app page, **when** it renders, **then** four cards show counts for each severity tier.

### US-6.6 — Consistent tab navigation
**As a** user, **I want** consistent tab patterns across apps (Overview / Details / Results / Export), **so that** the apps feel unified.
- **Given** any downstream app, **when** it loads, **then** a predictable tab layout is used.

---

## Phase 7 — AI Transparency & MISMO Integration

### US-7.1 — AI note callout
**As a** reviewer, **I want** each finding to include an AI note explaining the guideline reference and reasoning, **so that** I can trust the result.
- **Given** a finding, **when** I open it, **then** an `AiNote` box explains the reasoning with guideline citation.

### US-7.2 — AI recommendation badge
**As a** reviewer, **I want** each finding to carry an Approve/Reject/Escalate badge with confidence, **so that** I know the AI's position.
- **Given** a finding, **when** it renders, **then** an `AiRecommendation` badge shows one of Approve / Reject / Escalate with a confidence %.

### US-7.3 — MISMO 3.6 field extraction panel
**As a** data consumer, **I want** MISMO 3.6 entities and field paths with confidence, **so that** downstream systems can consume structured data.
- **Given** a finding, **when** I open the MISMO panel, **then** I see entity → MISMO 3.6 path → value rows with per-field confidence.

### US-7.4 — Evidence panel with page refs
**As a** reviewer, **I want** evidence snippets from source docs with page numbers, **so that** I can verify AI claims against the source.
- **Given** a finding, **when** I open the evidence panel, **then** snippets render with document name and page number.

### US-7.5 — Review dialog aggregation
**As a** reviewer, **I want** a single review dialog that combines AI note, recommendation, MISMO, and evidence, **so that** I can decide without context switching.
- **Given** I click a flag/check, **when** the dialog opens, **then** all four views are present.

---

## Phase 8 — Export & Reporting

### US-8.1 — Export PDF report
**As a** reviewer, **I want** to export a per-app PDF report, **so that** I can share it outside the platform.
- **Given** any app page, **when** I click Export PDF, **then** a PDF is produced containing the current view's key sections.
- **Given** the PDF is generated, **when** it renders the cover, header/footer, and any logo placement, **then** it conforms to [`docs/Logikality_Brand_Guidelines.pdf`](./Logikality_Brand_Guidelines.pdf) — approved logo asset, teal-primary palette, Proxima Nova typography. See US-X.1 / US-X.2.

### US-8.2 — Export MISMO 3.6 XML
**As a** data consumer, **I want** to export a per-app MISMO 3.6 XML, **so that** downstream systems can ingest the results.
- **Given** any app page, **when** I click Export MISMO XML, **then** a MISMO 3.6-conformant XML file is produced.

### US-8.3 — Send to manual review
**As a** reviewer, **I want** to send a packet to manual review from ECV, **so that** human reviewers can take over.
- **Given** the ECV action bar, **when** I click Send to manual review, **then** the packet is flagged and routed accordingly.
