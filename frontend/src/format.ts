import type { DriverResult } from './types'

export function money(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—'
  const sign = v < 0 ? '−' : ''
  const a = Math.abs(v)
  if (a >= 1e9) return `${sign}$${(a / 1e9).toFixed(2)}B`
  if (a >= 1e6) return `${sign}$${(a / 1e6).toFixed(digits)}M`
  if (a >= 1e3) return `${sign}$${(a / 1e3).toFixed(0)}K`
  return `${sign}$${a.toFixed(0)}`
}

/** "$6.5–11.7M" when both ends share a unit, else "$950K–$1.2M". */
export function moneyRange(lo: number, hi: number): string {
  if (lo >= 1e6 && hi >= 1e6 && hi < 1e9) {
    return `$${(lo / 1e6).toFixed(1)}–${(hi / 1e6).toFixed(1)}M`
  }
  return `${money(lo)}–${money(hi)}`
}

export function pct(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—'
  return `${(v * 100).toFixed(digits)}%`
}

export function ordinal(n: number): string {
  const r = Math.round(n)
  const t = r % 100
  if (t >= 11 && t <= 13) return `${r}th`
  return `${r}${['th', 'st', 'nd', 'rd'][r % 10] ?? 'th'}`
}

export const ROLE_LABEL: Record<string, string> = {
  lever: 'EBITDA lever',
  lever_overlap: 'EBITDA lever · may overlap G&A',
  rollup: 'Context · contains G&A',
  cash: 'Cash lever · not EBITDA',
  growth: 'Growth · protected',
  outcome: 'Outcome',
}

/** Each peer set lists exactly the widenings it applied, in any order. */
export function relaxations(keys: string[]): string {
  return keys.map(relaxation).join(' + ')
}

export function relaxation(key: string): string {
  const map: Record<string, string> = {
    pooled_all_years: 'all years pooled',
    adjacent_revenue_bands: 'neighbouring size bands',
    broadened_to_biotech_and_pharma: 'biotech and pharma combined',
  }
  return map[key] ?? key.replace(/_/g, ' ')
}

// Fact keys come from the model or the demo data as snake_case; without this
// the crib sheet reads "Ga headcount" and "Erp instances" in front of a client.
const ACRONYMS: Record<string, string> = {
  ga: 'G&A', hr: 'HR', it: 'IT', erp: 'ERP', hq: 'HQ', hqs: 'HQs',
  saas: 'SaaS', rnd: 'R&D', capex: 'CAPEX', sga: 'SG&A', fte: 'FTE',
  ftes: 'FTEs', ceo: 'CEO', cfo: 'CFO', pe: 'PE', kpi: 'KPI',
}

export function factLabel(key: string): string {
  const words = key.split(/[_\s]+/).filter(Boolean)
    .map((w) => ACRONYMS[w.toLowerCase()] ?? w.toLowerCase())
  if (!words.length) return key
  const first = words[0]
  words[0] = ACRONYMS[first.toLowerCase()] ? first : first.charAt(0).toUpperCase() + first.slice(1)
  return words.join(' ')
}

/**
 * Position on a shared "right is worse" axis, 0-100.
 *
 * For a cost, a high percentile means costlier than peers. For EBITDA margin a
 * high percentile is good, so it is mirrored. One axis direction for every row
 * means the reader never has to re-learn which way is bad.
 */
export function worsePosition(d: DriverResult): number | null {
  if (d.percentile === undefined) return null
  return d.lower_is_better ? d.percentile : 100 - d.percentile
}

export type Standing = 'worst' | 'above' | 'better'

// Within 5 points of the median is "at median": flagging CAPEX at the 52nd
// percentile as worse than peers is noise dressed as a finding.
export function standing(position: number): Standing {
  if (position >= 75) return 'worst'
  if (position > 55) return 'above'
  return 'better'
}

export const STANDING_TEXT: Record<Standing, string> = {
  worst: 'worst quartile',
  above: 'worse than median',
  better: 'at or better than median',
}

/** "<10M" → "Under $10M", "250M-1B" → "$250M–1B", ">5B" → "Over $5B". */
export function bandLabel(band: string | null | undefined): string {
  if (!band) return 'All sizes'
  if (band.startsWith('<')) return `Under $${band.slice(1)}`
  if (band.startsWith('>')) return `Over $${band.slice(1)}`
  return `$${band.replace('-', '–')}`
}

/** A sample's short name, from its tagline: "Vertical SaaS · $180M". */
export function sampleLabel(tagline: string, revenue: number | null): string {
  return `${tagline.split(',')[0]} · ${money(revenue, 0)}`
}

/** "Q1 2025" → "Q1 '25", "FY2025" → "FY25"; anything else unchanged. */
export function shortPeriod(p: string) {
  return p
    .replace(/\bFY\s?(\d{2})(\d{2})\b/i, 'FY$2')
    .replace(/\b(Q[1-4]|[A-Z][a-z]{2})\s+(\d{2})(\d{2})\b/, "$1 '$3")
}

/** An Insights ratio as shown: a share as "34.0%", a growth gap as
 *  "+1.5 pp", a dollar figure as "$400K". */
export function metricValue(kind: 'pct' | 'pp' | 'usd', v: number): string {
  if (kind === 'usd') return money(v, 1)
  if (kind === 'pp') return metricDifference(v, 'pp')
  return `${(v * 100).toFixed(1)}%`
}

/** The gap to a benchmark: "+2.0 pp" for shares, "−27.3%" for dollars. */
export function metricDifference(d: number, unit: 'pp' | '%'): string {
  const shown = Math.abs(d).toFixed(1)
  // No sign on a gap that rounds away: "0.0 pp", never "−0.0 pp".
  const sign = Number(shown) === 0 ? '' : d > 0 ? '+' : '−'
  return `${sign}${shown}${unit === 'pp' ? ' pp' : '%'}`
}
