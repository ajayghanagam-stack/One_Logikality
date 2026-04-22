# One Logikality — Happy Path Test Scenarios

Happy-path test cases derived from [Plan.md](./Plan.md) and [UserStories.md](./UserStories.md). Each scenario describes the optimistic path where inputs are valid, permissions are correct, and the system behaves as designed. Error paths and negative cases are out of scope for this document.

Scenario format:
- **ID** — stable identifier (`TS-<phase>.<story>.<n>`)
- **Given / When / Then** — preconditions, action, observable outcome
- **Data** — seed data or fixture references where relevant

---

## Phase 0 — Dev Environment & Scaffolding

### TS-0.1.1 — Full local stack bring-up
- **Given** a fresh checkout with `.env` copied from `.env.example`, Docker Desktop running, and `./start-dev.sh` invoked
- **When** the script finishes bring-up
- **Then** Postgres is listening on `5437`, Temporal on `7234`, Temporal UI on `8086`, FastAPI on `8001`, the Temporal worker is registered on the `ecv` task queue, and Next.js is serving on `9999`

### TS-0.1.2 — Backend health endpoint
- **Given** the stack is up
- **When** `GET http://localhost:8001/health` is called
- **Then** the response is `200 OK` with a JSON body indicating service status

### TS-0.1.3 — Frontend renders with brand palette
- **Given** the stack is up
- **When** `http://localhost:9999` is loaded in a browser
- **Then** the page renders the approved Logikality logo from `/public/`, teal `#01BAED` appears as the primary accent, and Proxima Nova (with declared fallback) is the active font family

### TS-0.1.4 — Alembic head matches models
- **Given** the backend virtualenv is active
- **When** `alembic upgrade head` is run against a fresh database
- **Then** the migration completes without error and `alembic current` reports the latest revision as `(head)`

---

## Phase 1 — Platform Foundation & Multi-Tenant Setup

### TS-1.1.1 — Dual-portal landing page
- **Given** the visitor has no session
- **When** the root URL is opened
- **Then** two labeled entry points render — "Customer" and "Platform Admin" — each linking to `/customer/login` and `/platform-admin/login` respectively

### TS-1.2.1 — Platform admin successful sign-in
- **Given** seeded credentials `admin@logikality.com` / `admin123`
- **When** the platform-admin login form is submitted
- **Then** a session tagged `platform-admin` is issued and the browser is routed to the accounts list

### TS-1.3.1 — Customer admin successful sign-in
- **Given** the seeded "Acme Mortgage Holdings" org with its primary customer-admin user
- **When** the customer login form is submitted with that user's email + password
- **Then** a session tagged `customer-admin` is issued and the browser lands on the org's home

### TS-1.3.2 — Customer user successful sign-in
- **Given** an invited customer-user belonging to Acme Mortgage Holdings
- **When** the customer login form is submitted
- **Then** the session is tagged `customer-user` and the home page renders with only enabled apps visible

### TS-1.4.1 — Role drives route access
- **Given** three parallel sessions — platform-admin, customer-admin, customer-user
- **When** each navigates to their permitted routes
- **Then** menus, sidebars, and API responses reflect only that role's capabilities; higher-privilege URLs are not surfaced to lower-privilege sessions

### TS-1.5.1 — Accounts list renders KPIs
- **Given** a signed-in platform admin and ≥1 seeded org
- **When** `/platform-admin/accounts` is opened
- **Then** KPI cards show total orgs, active users, and active subscriptions, and each account row displays org name, type, admin email, subscribed apps, user count, and created date

### TS-1.6.1 — Create a new customer account
- **Given** the new-account form open for a platform admin
- **When** valid org name, type, admin name, admin email, admin password, and a subset of app subscriptions are submitted
- **Then** a new account is persisted with `ECV` forced on, the admin user is created, and the account appears on the accounts list

### TS-1.7.1 — Edit subscriptions on an existing account
- **Given** an existing account detail page
- **When** a subscription toggle is flipped and Save is clicked
- **Then** the change persists in `app_subscriptions` and is reflected on the accounts list on refresh

### TS-1.7.2 — Reset customer admin password
- **Given** an existing account detail page
- **When** Reset Password is clicked and confirmed
- **Then** a new temporary password is generated, displayed for copy, and the user's stored credential hash is updated

### TS-1.8.1 — Platform admin changes own password
- **Given** a signed-in platform admin on the profile page
- **When** the current password is entered along with a new password and matching confirmation
- **Then** the change is saved, success feedback renders, and the new credential is valid on the next sign-in

### TS-1.9.1 — Role-aware sidebar rendering
- **Given** a signed-in user of any role
- **When** any authenticated page renders
- **Then** the sidebar chrome, items, and Logikality logo asset match that role's expected layout and use only approved logo assets from `/public/`

---

## Phase 2 — Customer Org Administration

### TS-2.1.1 — Customer admin changes own password
- **Given** a signed-in customer admin on the profile page
- **When** current + new (≥6 chars) + matching confirmation are submitted
- **Then** the password is updated and the new value is valid on next sign-in

### TS-2.2.1 — Invite a team member
- **Given** the invite form on the customer admin's users page
- **When** name, email, and role (Admin or Member) are submitted
- **Then** a new user row appears in the org's users list with the chosen role

### TS-2.3.1 — Temp password generated and copyable
- **Given** an invite has just been completed
- **When** the temp password badge is rendered and the copy icon is clicked
- **Then** the clipboard contains the temp password and a copy-confirmation indicator renders

### TS-2.4.1 — Remove a non-primary team member
- **Given** a non-primary member listed on the users page
- **When** Remove is clicked and confirmed
- **Then** the user is deleted from the org's users list and cannot sign in

### TS-2.5.1 — Subscribed vs unsubscribed partitioning
- **Given** the customer admin's app-access page with a mix of subscribed and unsubscribed apps
- **When** the page renders
- **Then** subscribed apps appear in a Subscribed section with enable/disable toggles, and unsubscribed apps appear in a non-enableable Unsubscribed section

### TS-2.6.1 — Enable a subscribed app
- **Given** a subscribed app currently disabled for the org
- **When** the customer admin toggles it on and the change is saved
- **Then** the app appears in every org user's sidebar on next load

### TS-2.6.2 — ECV toggle locked on
- **Given** the customer admin's app-access page
- **When** ECV's row is inspected
- **Then** the toggle is on and disabled, labeled as required

---

## Phase 3 — Document Ingestion & ECV Core

### TS-3.1.1 — Drag-drop a PDF packet
- **Given** the upload page
- **When** a valid PDF is dropped into the dropzone
- **Then** the file is listed with name, size, and a delete control

### TS-3.1.2 — File-picker PDF upload
- **Given** the upload page
- **When** a valid PDF is selected via the file picker
- **Then** the file is listed identically to the drag-drop case

### TS-3.2.1 — Select a loan program
- **Given** the upload page with at least one file queued
- **When** the program selector is opened and "Conventional" is chosen
- **Then** the selection is captured and the Analyze button becomes enabled

### TS-3.3.1 — Rule preview for selected program
- **Given** a program has been selected on the upload page
- **When** the rule preview renders
- **Then** DTI limit, chain depth, regulatory framework, and a guidelines summary are visible for that program

### TS-3.4.1 — Pipeline animation progresses through stages
- **Given** a packet has been submitted for analysis
- **When** the pipeline view renders
- **Then** stages `Upload → OCR → Classify → Validate → Analyze → Complete` tick through via SSE updates, and completion routes the user to the ECV dashboard

### TS-3.5.1 — ECV score ≥ 90% enables Approve
- **Given** a packet whose pipeline produced an overall score of 92%
- **When** the ECV dashboard renders
- **Then** Approve is enabled on the sticky action bar and no manual-review banner is shown

### TS-3.6.1 — Section expands into line-item checks
- **Given** the ECV Section Scores tab
- **When** a section row is expanded
- **Then** its line items render with description, result, and confidence %

### TS-3.7.1 — Severity classification at boundaries
- **Given** line items with confidences 42, 70, and 92
- **When** the Items-to-Review tab renders
- **Then** the 42 item is CRITICAL, the 70 item is REVIEW, and the 92 item is PASS

### TS-3.8.1 — Documents tab inventory
- **Given** a packet that produced document-class findings
- **When** the Documents tab renders
- **Then** the inventory groups documents by category, tagging each with MISMO 3.6 class, status, confidence, and page numbers; pages with blank/low-res/rotated flags display those flags

### TS-3.9.1 — Section Scores weighted bars
- **Given** the ECV Section Scores tab
- **When** it renders for a scored packet
- **Then** all 13 sections display weighted scores with proportional bars

### TS-3.10.1 — Filter Items to Review by severity
- **Given** the Items-to-Review tab with a mix of Critical and Review items
- **When** the Critical filter chip is clicked
- **Then** only items with confidence < 50% remain, sorted by confidence ascending

### TS-3.11.1 — Program confirmation = Confirmed
- **Given** a packet where documents fully support the declared program
- **When** ECV completes
- **Then** the program pill reads "Confirmed" and downstream rules resolve against the declared program

### TS-3.12.1 — Packet-level program override with reason
- **Given** the ECV dashboard with the program pill visible
- **When** Change program is clicked, a new program is selected, a reason is entered, and Save is clicked
- **Then** the override is persisted with actor + timestamp, the override marker renders, and downstream rules recalculate for the new program

### TS-3.13.1 — Sticky action bar remains pinned
- **Given** a long ECV dashboard page
- **When** the user scrolls to the bottom
- **Then** the Approve / Reject / Export PDF / Send to manual review bar remains fixed to the viewport

---

## Phase 4 — Rule & Configuration System

### TS-4.1.1 — Industry default applied when no overrides
- **Given** a packet whose program has no org or packet overrides
- **When** `getEffectiveRules` resolves values for its micro-app
- **Then** every rule resolves to the industry default and carries no override flag

### TS-4.2.1 — Org-level override persists and applies
- **Given** the customer admin's configuration page for a program/app pair
- **When** a rule is edited, Save is clicked, and the save completes
- **Then** subsequent packets for that program resolve the new org-level value

### TS-4.3.1 — Packet-level override captured with audit fields
- **Given** a reviewer on the ECV or micro-app page
- **When** a rule is edited at the packet level with a reason
- **Then** the override stores reason + actor + timestamp, visible on the rule detail view

### TS-4.4.1 — Resolver precedence packet > org > default
- **Given** all three levels populated with distinct values for the same rule
- **When** the resolver runs
- **Then** it returns the packet value and flags the override level as "packet"

### TS-4.5.1 — ConfigApplied badge lists sources
- **Given** a micro-app page loaded for a packet with a mix of default, org, and packet-level rules
- **When** the header renders
- **Then** the ConfigApplied badge enumerates the key rules with source labels (default / org / packet)

### TS-4.6.1 — Rule editor renders the correct input type
- **Given** rules of types number, select, and toggle
- **When** the editor opens for each
- **Then** a numeric input, a dropdown, and a switch render respectively, and each validates on Save

### TS-4.7.1 — Reset to defaults clears org overrides
- **Given** the configuration page with unsaved edits and existing saved overrides
- **When** Reset to defaults is clicked and confirmed
- **Then** all overrides for the selected program clear back to industry defaults

---

## Phase 5 — App Gating & Cross-App Dependencies

### TS-5.1.1 — App unblocked when required docs present
- **Given** an app's required-docs mapping fully satisfied by the packet inventory
- **When** ECV resolves gating
- **Then** the app is marked unblocked and is clickable from the launcher

### TS-5.2.1 — Proceed Anyway on a blocked app
- **Given** a blocked app with one missing required doc
- **When** the launcher tile is clicked, the blocked-app dialog appears, and Proceed Anyway is confirmed
- **Then** the app loads with a partial-data-mode banner

### TS-5.3.1 — Sidebar BLOCKS indicator renders
- **Given** a missing doc that blocks the Income Calculation app
- **When** the ECV Documents sidebar renders
- **Then** a "BLOCKS Income Calculation" indicator is attached to that doc row

### TS-5.4.1 — Cross-app reference stored and navigable by MISMO ID
- **Given** a Compliance finding that references an Income Calculation field
- **When** the reference is persisted and later rendered
- **Then** it is stored as a MISMO 3.6 field ID pair and the UI link navigates to the related finding in the target app

---

## Phase 6 — Downstream Micro-Apps

### TS-6.1.1 — Title Search Overview renders
- **Given** a packet with Title Search enabled and required docs present
- **When** the Title Search app opens
- **Then** the Overview tab shows property summary, risk KPI cards, and a chain-of-title timeline

### TS-6.2.1 — Title Examination curative workflow updates state
- **Given** a Title Examination results view with an open requirement
- **When** a curative step, assignee, and Cleared status are recorded
- **Then** the requirement reflects the new state and its audit trail shows the actor + timestamp

### TS-6.3.1 — Compliance check verdicts render
- **Given** a packet whose pipeline produced compliance findings
- **When** the Compliance Overview tab renders
- **Then** each check shows Pass / Fail / Warn / N/A with a reason

### TS-6.3.2 — Fee tolerance table compares LE vs CD
- **Given** the Compliance Tolerances tab for the same packet
- **When** it renders
- **Then** LE vs CD fees are bucketed into 0% / 10% / Unlimited with dollar and percent deltas

### TS-6.4.1 — Income sources and DTI render
- **Given** a packet with income findings for Base / Overtime / Bonus / Rental
- **When** the Income Calculation app renders its Income Sources and DTI tabs
- **Then** each source shows monthly + annual amounts, documentation, and trend, and the DTI tab shows total income, total debt, DTI ratio, and guideline status

### TS-6.5.1 — Risk summary cards
- **Given** any downstream app page
- **When** it renders
- **Then** four cards show counts for Critical / High / Medium / Low severity

### TS-6.6.1 — Consistent tab layout across apps
- **Given** the user navigates across Title Search, Title Exam, Compliance, and Income Calculation
- **When** each app loads
- **Then** the tab order (Overview / Details / Results / Export) is identical in position and labeling

---

## Phase 7 — AI Transparency & MISMO Integration

### TS-7.1.1 — AiNote explains a finding
- **Given** a finding produced by the pipeline
- **When** the finding is opened
- **Then** an `AiNote` callout renders with reasoning and a guideline citation

### TS-7.2.1 — AiRecommendation badge renders
- **Given** a finding produced by the pipeline
- **When** the finding is opened
- **Then** an `AiRecommendation` badge shows one of Approve / Reject / Escalate with a confidence %

### TS-7.3.1 — MISMO panel enumerates extractions
- **Given** a finding whose extractions reference MISMO 3.6 paths
- **When** the MISMO panel is opened
- **Then** each row shows entity → MISMO 3.6 path → value with per-field confidence

### TS-7.4.1 — Evidence panel shows page refs
- **Given** a finding with source-document evidence
- **When** the evidence panel is opened
- **Then** snippets render with document name and page number

### TS-7.5.1 — Review dialog aggregates all four views
- **Given** any flag/check on any app
- **When** the review dialog is opened
- **Then** AiNote, AiRecommendation, MISMO panel, and evidence panel are all present in one dialog

---

## Phase 8 — Export & Reporting

### TS-8.1.1 — Export PDF from a micro-app
- **Given** any micro-app page loaded for a scored packet
- **When** Export PDF is clicked
- **Then** a PDF downloads containing the current view's key sections with brand-compliant cover, header/footer, and logo placement

### TS-8.2.1 — Export MISMO 3.6 XML
- **Given** any micro-app page loaded for a scored packet
- **When** Export MISMO XML is clicked
- **Then** a MISMO 3.6-conformant XML file downloads and validates against the MISMO 3.6 schema

### TS-8.3.1 — Send to manual review from ECV
- **Given** the ECV dashboard action bar
- **When** Send to manual review is clicked and confirmed
- **Then** the packet is flagged for manual review and routed to the manual-review queue

---

## Cross-Cutting — Brand & Visual Compliance

### TS-X.1.1 — Brand tokens drive component color
- **Given** any UI surface introduced or modified
- **When** its rendered styles are inspected
- **Then** color values resolve through `lib/brand.ts` tokens — no raw hex literals scattered through components

### TS-X.2.1 — Logo renders from approved asset only
- **Given** any surface that displays the Logikality mark
- **When** the DOM is inspected
- **Then** the mark is sourced from an approved file in `/public/` (e.g. `logikality_with_tagline.png`, `Logo_withTagline.svg`, `Logo_rev_no-tagline.svg`) — never an inline drawing or re-traced SVG

---

## Coverage Matrix

| Phase | User Stories | Happy-Path Scenarios |
|-------|--------------|----------------------|
| 0     | Scaffolding  | TS-0.1.1 – TS-0.1.4  |
| 1     | US-1.1 – US-1.9 | TS-1.1.1 – TS-1.9.1 |
| 2     | US-2.1 – US-2.6 | TS-2.1.1 – TS-2.6.2 |
| 3     | US-3.1 – US-3.13 | TS-3.1.1 – TS-3.13.1 |
| 4     | US-4.1 – US-4.7 | TS-4.1.1 – TS-4.7.1 |
| 5     | US-5.1 – US-5.4 | TS-5.1.1 – TS-5.4.1 |
| 6     | US-6.1 – US-6.6 | TS-6.1.1 – TS-6.6.1 |
| 7     | US-7.1 – US-7.5 | TS-7.1.1 – TS-7.5.1 |
| 8     | US-8.1 – US-8.3 | TS-8.1.1 – TS-8.3.1 |
| X     | US-X.1 – US-X.2 | TS-X.1.1 – TS-X.2.1 |
