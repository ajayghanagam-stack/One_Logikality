/**
 * Rule catalog — industry-standard defaults per loan program plus the
 * per-micro-app editable-rule schemas.
 *
 * Ported from the demo reference (`one-logikality-demo/lib/demo-data.ts`)
 * AND kept in lockstep with `backend/app/rules/catalog.py`. The backend
 * exposes an identical structure at `GET /api/customer-admin/config/catalog`
 * for scripts/tools that need to read the catalog server-side; the UI
 * uses this static copy to keep the rule editor zero-round-trip.
 *
 * Keys are camelCase end-to-end (not Python snake_case) so values
 * round-trip unchanged across the wire.
 */

export type RuleValue = string | number | boolean;

export type LoanProgramRules = {
  id: string;
  label: string;
  description: string;
  confidenceThreshold: number;
  chainDepth: number;
  judgmentScope: "state" | "both";
  regulatoryFramework: string;
  disclosureSet: string;
  guidelines: string;
  dtiLimit: number;
  trendingMethod: "averaged" | "declining";
  residualIncome: boolean;
};

export type EditableRuleSchema = {
  key: string;
  label: string;
  type: "number" | "select" | "toggle";
  unit?: string;
  min?: number;
  max?: number;
  options?: { value: string; label: string }[];
  helpText?: string;
};

export const LOAN_PROGRAMS: Record<string, LoanProgramRules> = {
  conventional: {
    id: "conventional",
    label: "Conventional Conforming",
    description: "Fannie Mae / Freddie Mac conforming loans within loan limits",
    confidenceThreshold: 85,
    chainDepth: 30,
    judgmentScope: "both",
    regulatoryFramework: "CFPB 2026",
    disclosureSet: "TRID + Federal + State",
    guidelines: "Fannie Mae Selling Guide",
    dtiLimit: 45,
    trendingMethod: "averaged",
    residualIncome: false,
  },
  jumbo: {
    id: "jumbo",
    label: "Jumbo / Non-Conforming",
    description:
      "Loan amounts above conforming limits, typically portfolio or private investor",
    confidenceThreshold: 95,
    chainDepth: 40,
    judgmentScope: "both",
    regulatoryFramework: "CFPB 2026 + Investor overlays",
    disclosureSet: "TRID + Federal + State + Portfolio",
    guidelines: "Investor-specific (varies)",
    dtiLimit: 43,
    trendingMethod: "averaged",
    residualIncome: false,
  },
  fha: {
    id: "fha",
    label: "FHA",
    description: "Federal Housing Administration insured loans",
    confidenceThreshold: 80,
    chainDepth: 30,
    judgmentScope: "both",
    regulatoryFramework: "CFPB 2026 + HUD",
    disclosureSet: "TRID + Federal + State + FHA specific",
    guidelines: "HUD Handbook 4000.1",
    dtiLimit: 50,
    trendingMethod: "averaged",
    residualIncome: false,
  },
  va: {
    id: "va",
    label: "VA",
    description: "Veterans Affairs guaranteed loans",
    confidenceThreshold: 82,
    chainDepth: 30,
    judgmentScope: "both",
    regulatoryFramework: "CFPB 2026 + VA",
    disclosureSet: "TRID + Federal + State + VA specific",
    guidelines: "VA Lenders Handbook 26-7",
    dtiLimit: 41,
    trendingMethod: "averaged",
    residualIncome: true,
  },
  usda: {
    id: "usda",
    label: "USDA Rural Development",
    description: "USDA Single Family Housing Guaranteed Loan Program",
    confidenceThreshold: 82,
    chainDepth: 30,
    judgmentScope: "both",
    regulatoryFramework: "CFPB 2026 + USDA",
    disclosureSet: "TRID + Federal + State + USDA specific",
    guidelines: "USDA HB-1-3555",
    dtiLimit: 41,
    trendingMethod: "averaged",
    residualIncome: false,
  },
  nonqm: {
    id: "nonqm",
    label: "Non-QM / Alternative Doc",
    description:
      "Bank statement, DSCR, asset depletion, and other non-QM programs",
    confidenceThreshold: 95,
    chainDepth: 40,
    judgmentScope: "both",
    regulatoryFramework: "CFPB 2026 + Investor overlays",
    disclosureSet: "TRID + Federal + State + Non-QM specific",
    guidelines: "Investor-specific (Bank statement, DSCR, Asset depletion)",
    dtiLimit: 50,
    trendingMethod: "averaged",
    residualIncome: false,
  },
};

export const LOAN_PROGRAM_IDS = Object.keys(LOAN_PROGRAMS);

// Display metadata for the micro-apps that carry editable rules.
// Kept separate from `lib/apps.ts::MICRO_APPS` because the Configuration
// page wants slightly different icons (tone is "adjust rules", not
// "enable the whole app").
export const RULE_APP_LABELS: Record<string, string> = {
  compliance: "Compliance",
  "income-calc": "Income Calculation",
  "title-search": "Title Search & Abstraction",
  "title-exam": "Title Examination",
};

export const RULE_APP_ICONS: Record<string, string> = {
  compliance: "🛡️",
  "income-calc": "💵",
  "title-search": "🔎",
  "title-exam": "📋",
};

export const MICRO_APP_RULES: Record<string, EditableRuleSchema[]> = {
  compliance: [
    {
      key: "regulatoryFramework",
      label: "Regulatory framework",
      type: "select",
      options: [
        { value: "CFPB 2026", label: "CFPB 2026" },
        { value: "CFPB 2026 + HUD", label: "CFPB 2026 + HUD" },
        { value: "CFPB 2026 + VA", label: "CFPB 2026 + VA" },
        { value: "CFPB 2026 + USDA", label: "CFPB 2026 + USDA" },
        {
          value: "CFPB 2026 + Investor overlays",
          label: "CFPB 2026 + Investor overlays",
        },
      ],
      helpText:
        "Base regulatory framework applied to disclosure timing, fee tolerances, and truth-in-lending checks.",
    },
    {
      key: "disclosureSet",
      label: "Disclosure set",
      type: "select",
      options: [
        { value: "TRID + Federal + State", label: "TRID + Federal + State" },
        {
          value: "TRID + Federal + State + FHA specific",
          label: "TRID + Federal + State + FHA specific",
        },
        {
          value: "TRID + Federal + State + VA specific",
          label: "TRID + Federal + State + VA specific",
        },
        {
          value: "TRID + Federal + State + USDA specific",
          label: "TRID + Federal + State + USDA specific",
        },
        {
          value: "TRID + Federal + State + Portfolio",
          label: "TRID + Federal + State + Portfolio",
        },
        {
          value: "TRID + Federal + State + Non-QM specific",
          label: "TRID + Federal + State + Non-QM specific",
        },
      ],
      helpText:
        "Which disclosure requirements to verify. Program-specific disclosures (e.g., FHA Amendatory Clause) are added based on program type.",
    },
  ],
  "income-calc": [
    {
      key: "dtiLimit",
      label: "DTI limit",
      type: "number",
      unit: "%",
      min: 30,
      max: 60,
      helpText:
        "Maximum debt-to-income ratio for qualification. May be loosened for strong compensating factors (reserves, LTV, credit score).",
    },
    {
      key: "guidelines",
      label: "Underwriting guidelines",
      type: "select",
      options: [
        { value: "Fannie Mae Selling Guide", label: "Fannie Mae Selling Guide" },
        {
          value: "Freddie Mac Single-Family Seller/Servicer Guide",
          label: "Freddie Mac Seller/Servicer Guide",
        },
        { value: "HUD Handbook 4000.1", label: "HUD Handbook 4000.1 (FHA)" },
        { value: "VA Lenders Handbook 26-7", label: "VA Lenders Handbook 26-7" },
        { value: "USDA HB-1-3555", label: "USDA HB-1-3555" },
        {
          value: "Investor-specific (varies)",
          label: "Investor-specific (varies)",
        },
      ],
      helpText:
        "Which underwriting guideline authority is used for income calculation rules.",
    },
    {
      key: "trendingMethod",
      label: "Income trending method",
      type: "select",
      options: [
        { value: "averaged", label: "Averaged (2-year average)" },
        {
          value: "declining",
          label: "Declining (conservative — use lowest year)",
        },
      ],
      helpText:
        "Averaged is standard; Declining uses the lowest annual amount from the 2-year history (conservative).",
    },
    {
      key: "residualIncome",
      label: "Residual income required",
      type: "toggle",
      helpText:
        "Required for VA loans. Calculates net income after all obligations against VA regional tables.",
    },
  ],
  "title-search": [
    {
      key: "chainDepth",
      label: "Chain-of-title depth",
      type: "number",
      unit: "years",
      min: 20,
      max: 60,
      helpText:
        "How many years back to trace chain of title. 30 years is standard; jumbo/non-QM typically 40.",
    },
    {
      key: "judgmentScope",
      label: "Judgment search scope",
      type: "select",
      options: [
        { value: "state", label: "State courts only" },
        { value: "both", label: "State + Federal (PACER)" },
      ],
      helpText: "Which court systems to search for judgments and liens.",
    },
  ],
  "title-exam": [
    {
      key: "exceptionClassification",
      label: "Exception classification standard",
      type: "select",
      options: [
        { value: "ALTA", label: "ALTA standard" },
        { value: "State-specific", label: "State-specific overlay" },
      ],
      helpText:
        "Which ALTA standards apply. Some states (CA, NY, TX) have specific overlays.",
    },
    {
      key: "vestingSensitivity",
      label: "Vesting mismatch sensitivity",
      type: "select",
      options: [
        { value: "Strict", label: "Strict (flag any mismatch)" },
        { value: "Moderate", label: "Moderate (flag material mismatches)" },
        { value: "Lenient", label: "Lenient (only flag substantive defects)" },
      ],
      helpText:
        "How aggressively to flag name/identity variances between documents.",
    },
  ],
};

export const RULE_APP_IDS = Object.keys(MICRO_APP_RULES);

// `{ programId: { ruleKey: value } }` — the shape of the wire response
// from GET /api/customer-admin/config and the shape the resolver's
// `orgOverrides` argument expects.
export type OrgConfigOverrides = Record<string, Record<string, RuleValue>>;
