/**
 * Micro-app catalog — display metadata shared across the platform-admin
 * portal (account creation, subscription management) and customer-portal
 * screens in later phases.
 *
 * `id` values are kept in lockstep with backend/app/models.py::APP_IDS and
 * the CHECK constraint in migration 0003_app_subscriptions. The backend
 * validates against its own list, so adding a new app means changes in
 * three places: this file, the backend constant, and a new migration.
 *
 * Emojis-as-icons are intentional in this prototype tier — see CLAUDE.md
 * Brand and styling section. Replace with SVG icons before production.
 */

export type MicroApp = {
  id: string;
  name: string;
  desc: string;
  icon: string;
  /** ECV is foundational — the backend auto-subscribes every org to it
   *  regardless of what the UI sends, so the checkbox/button is disabled
   *  and carries a "Required" badge. */
  required: boolean;
};

export const MICRO_APPS: readonly MicroApp[] = [
  {
    id: "ecv",
    name: "ECV Engine",
    desc: "Extraction, Classification & Validation — the foundational AI engine",
    icon: "🔍",
    required: true,
  },
  {
    id: "title-search",
    name: "Title Search & Abstraction",
    desc: "AI-powered chain-of-title analysis",
    icon: "📋",
    required: false,
  },
  {
    id: "title-exam",
    name: "Title Examination",
    desc: "Expert-level title defect detection",
    icon: "🔎",
    required: false,
  },
  {
    id: "compliance",
    name: "Compliance",
    desc: "TRID, RESPA, ECOA — automated regulatory compliance",
    icon: "⚖",
    required: false,
  },
  {
    id: "income-calc",
    name: "Income Calculation",
    desc: "W-2, 1040, paystub income qualification",
    icon: "💰",
    required: false,
  },
] as const;

/**
 * Default subscribed apps by organization type. Mirrors the demo's
 * ORG_TYPE_APP_DEFAULTS — the lender gets the full stack, servicers
 * focus on compliance, title agencies on title work, BPOs start bare.
 * Keys are the human-readable type labels (the same strings the
 * backend validates against).
 */
export const ORG_TYPE_APP_DEFAULTS: Record<string, readonly string[]> = {
  "Mortgage Lender": ["ecv", "title-search", "title-exam", "compliance", "income-calc"],
  "Loan Servicer": ["ecv", "compliance"],
  "Title Agency": ["ecv", "title-search", "title-exam"],
  "Mortgage BPO": ["ecv"],
};
