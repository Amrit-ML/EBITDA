// Mirrors the backend response shapes (core/benchmarks.py, agent.py, main.py).

export type EbitdaRole =
  | 'lever'
  | 'lever_overlap'
  | 'rollup'
  | 'cash'
  | 'growth'
  | 'outcome'

export type Confidence = 'high' | 'medium' | 'low' | 'insufficient'

export interface CompanySummary {
  id: string
  name: string
  tagline: string
  industry: string
  industry_label: string
  fiscal_year: number
  synthetic: boolean
  uploaded: boolean
  revenue: number | null
}

export interface Industry {
  id: string
  label: string
  description: string
  filers: number
}

/** One driver's spread across an industry, before any P&L is uploaded. */
export interface ProfileDriver {
  driver: string
  label: string
  ebitda_role: EbitdaRole
  lower_is_better: boolean
  description: string
  n: number
  peer_companies: number
  relaxations: string[]
  industry_level: string
  available: boolean
  confidence: Confidence
  reason?: string
  p10?: number
  p25?: number
  median?: number
  p75?: number
  p90?: number
}

export interface IndustryProfile {
  id: string
  label: string
  description: string
  min_revenue: number
  band: string | null
  fiscal_year: number
  years: number[]
  filers: number
  company_years: number
  median_revenue: number | null
  bands: { band: string; filers: number }[]
  drivers: ProfileDriver[]
}

export interface DriverResult {
  driver: string
  label: string
  ebitda_role: EbitdaRole
  lower_is_better: boolean
  company_value: number | null
  company_dollars: number | null
  n: number
  peer_companies: number
  relaxations: string[]
  industry_level: string
  available: boolean
  confidence: Confidence
  reason?: string
  p25?: number
  median?: number
  p75?: number
  percentile?: number
  gap_to_median_usd?: number
  gap_to_top_quartile_usd?: number
}

export interface Comparison {
  company: {
    revenue: number
    revenue_band: string | null
    industry: string
    industry_label: string
    fiscal_year: number
    peer_years: number[]
    ebitda: number | null
    ebitda_margin: number | null
  }
  drivers: DriverResult[]
  totals: {
    nature: string
    ebitda_gap_low_usd: number
    ebitda_gap_high_usd: number
    low_basis: string
    high_basis: string
    cash_opportunity_usd: number
    margin_gap_low_pts: number | null
    margin_gap_high_pts: number | null
    excluded: Record<string, string[]>
  }
}

/** An opportunity the diagnostic recorded: the action, why, and where to
 *  start. No saving is estimated. (Sessions saved before that change also
 *  carry savings fields, which nothing reads.) */
export interface Finding {
  id: string
  driver: string
  label: string
  ebitda_role: EbitdaRole
  lever: string
  rationale: string
  first_step?: string
  based_on: string[]
  /** Where the cost ranks against peers today: the share that spend less. */
  percentile_now?: number
  unsupported?: boolean
}

export interface FindingsTotals {
  count: number
}

export interface TraceStep {
  step: string
  model: string
  duration_s: number
  cost_usd: number
}

export interface AgentTurn {
  session_id: string
  message: string
  stage: string
  facts: Record<string, unknown>
  findings: Finding[]
  findings_totals: FindingsTotals
  guard: { unverified_figures: string[]; checked: boolean }
  trace: TraceStep[]
  turn_cost_usd: number
  comparison?: Comparison
}

export interface Briefing {
  id: string
  name: string
  hidden_facts: Record<string, string | number>
  planted: Record<string, string>
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  guard?: AgentTurn['guard']
  trace?: TraceStep[]
  cost?: number
  /** When the message was added, for the time shown under it. */
  at?: number
}

export interface UploadPeriod {
  key: string
  label: string
  year: number | null
}

export interface UploadPreview {
  upload_id: string
  filename: string
  /** Worksheet/page/slide read, and every section found (empty for CSV). */
  sheet: string | null
  sheets: string[]
  /** Where the table came from: a plain file, a workbook, a PDF or a deck. */
  source_kind: 'file' | 'workbook' | 'pdf' | 'deck'
  /** Shown for pdf/deck: the column layout was inferred, not read from cells. */
  extraction_note: string | null
  orientation: 'rows' | 'columns'
  labels: string[]
  periods: UploadPeriod[]
  default_period: string | null
  // 'ai' = the fixed synonym list found nothing, so one model call named the
  // label; every other confidence level is a same-process pattern match.
  suggested_mapping: Record<string, { label: string; confidence: 'exact' | 'partial' | 'ai' }>
  /** Fields the AI mapper (not the synonym list) named. */
  ai_mapped: string[]
  detected_units: 'thousands' | 'millions' | null
  fields: { key: string; label: string; required: boolean }[]
  preview: { columns: string[]; rows: unknown[][] }
  warning: string | null
}

export type Units = 'dollars' | 'thousands' | 'millions'
