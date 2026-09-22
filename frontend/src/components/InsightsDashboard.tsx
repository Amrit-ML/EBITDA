import { AlertTriangle, CheckCircle2, ChevronsRight, Upload, UserPlus } from 'lucide-react'
import type { InsightMetric } from '../api'
import { metricDifference, metricValue } from '../format'
import { cn } from '@/lib/utils'

type Status = 'better' | 'worse' | 'level' | 'missing'

const status = (m: InsightMetric): Status =>
  m.value === null ? 'missing' : m.favourable === null ? 'level' : m.favourable ? 'better' : 'worse'

// Bar fills sit on a light track, so light mode uses deeper tones than the
// brand green and amber to keep 3:1 against it; dark mode can use the brand.
const FILL: Record<Status, string> = {
  better: 'bg-[#1F9D55] dark:bg-primary-2',
  worse: 'bg-[#B7791F] dark:bg-accent-5',
  level: 'bg-n-4 dark:bg-n-4d',
  missing: 'bg-n-3 dark:bg-n-5',
}
const INK: Record<Status, string> = {
  better: 'text-[#1F9D55] dark:text-primary-2',
  worse: 'text-[#B7791F] dark:text-accent-5',
  level: 'text-n-4 dark:text-n-4d',
  missing: 'text-n-4 dark:text-n-4d',
}

// Past this multiple of the benchmark a bar stops growing and shows an
// off-scale marker, so the benchmark tick is never squeezed to the edge.
const SCALE_CAP = 2.5

// The two groups the eight ratios fall into. Order follows the reader's
// question: is overhead too heavy, then are people productive.
const GROUPS = [
  {
    title: 'Overhead',
    note: 'SG&A against revenue, gross profit, growth and people.',
    keys: [
      'sga_pct_revenue',
      'sga_pct_gross_profit',
      'sga_growth_vs_revenue_growth',
      'sga_per_employee',
      'sga_fte_pct',
    ],
  },
  {
    title: 'Productivity',
    note: 'What each employee generates.',
    keys: ['revenue_per_employee', 'gross_profit_per_employee', 'ebitda_per_employee'],
  },
]

/** A dollar figure at least twice its benchmark reads better as a multiple:
 *  "10.7×" rather than "+966.7%". */
function multipleOf(m: InsightMetric): number | null {
  if (m.difference_unit !== '%' || m.value === null || m.benchmark <= 0) return null
  const x = m.value / m.benchmark
  return x >= 2 ? x : null
}

/** The gap to the benchmark as a chip. Colour says good or bad; the icon and
 *  the spoken words say it too, so the verdict never rests on colour alone. */
export function Difference({ m }: { m: InsightMetric }) {
  if (m.difference === null) return <span className="text-n-4 dark:text-n-4d">—</span>
  const x = multipleOf(m)
  const text = x !== null ? `${x.toFixed(1)}×` : metricDifference(m.difference, m.difference_unit)
  const spoken = x !== null ? `, ${x.toFixed(1)} times the benchmark` : ''
  if (m.favourable === null) {
    return (
      <span className="whitespace-nowrap rounded-md bg-n-3 px-2 py-1 font-display text-xs font-semibold tabular-nums text-n-4 dark:bg-n-5 dark:text-n-4d">
        {text}
        <span className="sr-only">. Level with the benchmark.</span>
      </span>
    )
  }
  const good = m.favourable
  const Icon = good ? CheckCircle2 : AlertTriangle
  const verdict = good ? 'Better than the benchmark' : 'Worse than the benchmark'
  return (
    <span
      title={`${verdict}${spoken}`}
      className={cn(
        'inline-flex items-center gap-1 whitespace-nowrap rounded-md px-2 py-1 font-display text-xs font-semibold tabular-nums',
        good
          ? 'bg-primary-2/15 text-[#178A43] dark:text-primary-2'
          : 'bg-accent-5/15 text-[#8A5F00] dark:text-accent-5'
      )}
    >
      <Icon className="h-3.5 w-3.5" aria-hidden="true" />
      {text}
      <span className="sr-only">
        {spoken}. {verdict}.
      </span>
    </span>
  )
}

/** A bullet bar: the company's value as a fill, the benchmark as a tick.
 *  A scale that can go negative (a growth gap, or EBITDA for a loss-making
 *  company) runs either side of a zero line; otherwise it starts at zero. */
function Bullet({ m }: { m: InsightMetric }) {
  const v = m.value
  const b = m.benchmark
  const diverging = m.kind === 'pp' || (v ?? 0) < 0 || b < 0
  let lo: number
  let hi: number
  if (diverging) {
    const r = Math.max(Math.abs(v ?? 0), Math.abs(b), m.kind === 'pp' ? 2 : 1) * 1.3
    const capped = Math.abs(b) > 0 ? Math.min(r, Math.abs(b) * SCALE_CAP * 1.3) : r
    lo = -capped
    hi = capped
  } else {
    lo = 0
    const top = Math.max(v ?? 0, b) * 1.25 || 1
    hi = b > 0 ? Math.min(top, b * SCALE_CAP) : top
  }
  const clamp = (x: number) => Math.min(hi, Math.max(lo, x))
  const pos = (x: number) => ((clamp(x) - lo) / (hi - lo)) * 100
  const offScale = v !== null && (v > hi || v < lo)
  const zero = pos(0)
  const start = v === null ? zero : diverging ? Math.min(zero, pos(v)) : 0
  const width = v === null ? 0 : diverging ? Math.abs(pos(v) - zero) : pos(v)
  const label =
    v === null
      ? `Benchmark ${metricValue(m.kind, b)}; your figure is not available yet`
      : `Your company ${metricValue(m.kind, v)} against a benchmark of ${metricValue(m.kind, b)}${offScale ? ', beyond the end of the scale' : ''}`

  return (
    <div className="relative h-6" role="img" aria-label={label}>
      <div className="absolute inset-x-0 top-1/2 h-2.5 -translate-y-1/2 rounded-full bg-n-2 dark:bg-n-7" />
      {diverging && (
        <div
          className="absolute top-1/2 h-4 w-px -translate-y-1/2 bg-n-4/40"
          style={{ left: `${zero}%` }}
          aria-hidden="true"
        />
      )}
      {v !== null && width > 0 && (
        <div
          className={cn(
            'absolute top-1/2 h-2.5 -translate-y-1/2 animate-grow-x',
            // An off-scale end is squared off where the chevron takes over.
            offScale ? (v > 0 ? 'rounded-l-full' : 'rounded-r-full') : 'rounded-full',
            FILL[status(m)]
          )}
          style={{
            left: `${start}%`,
            width: `${width}%`,
            transformOrigin: diverging && v < 0 ? 'right' : 'left',
          }}
        />
      )}
      {offScale && (
        <ChevronsRight
          className={cn(
            'absolute top-1/2 h-4 w-4 -translate-y-1/2 rounded-full bg-n-1 dark:bg-n-6',
            v! > 0 ? '-right-2.5' : '-left-2.5 rotate-180',
            INK[status(m)]
          )}
          strokeWidth={3}
          aria-hidden="true"
        />
      )}
      <div
        className="absolute top-0 h-6 w-[3px] -translate-x-1/2 rounded-full bg-n-7 ring-2 ring-n-1 dark:bg-n-1 dark:ring-n-6"
        style={{ left: `${pos(b)}%` }}
        aria-hidden="true"
      />
    </div>
  )
}

export interface MetricActions {
  onAddHeadcount: (field: 'total-fte' | 'sga-fte') => void
  onUpload: () => void
}

function MissingValue({ m, actions }: { m: InsightMetric; actions: MetricActions }) {
  const button =
    'inline-flex items-center gap-2 rounded-lg bg-accent-2/10 px-3 py-2 font-display text-sm font-semibold text-accent-2 transition-colors hover:bg-accent-2/20'
  if (m.action === 'add_total_fte' || m.action === 'add_sga_fte') {
    return (
      <button
        type="button"
        onClick={() => actions.onAddHeadcount(m.action === 'add_sga_fte' ? 'sga-fte' : 'total-fte')}
        className={button}
      >
        <UserPlus className="h-4 w-4" aria-hidden="true" />
        {m.missing}
      </button>
    )
  }
  if (m.action === 'reupload') {
    return (
      <div className="space-y-2">
        <p className="text-sm leading-5 text-n-4 dark:text-n-4d">{m.missing}.</p>
        <button type="button" onClick={actions.onUpload} className={button}>
          <Upload className="h-4 w-4" aria-hidden="true" />
          Upload the P&amp;L again
        </button>
      </div>
    )
  }
  return <p className="text-sm leading-5 text-n-4 dark:text-n-4d">{m.missing}</p>
}

function MetricCard({ m, actions }: { m: InsightMetric; actions: MetricActions }) {
  return (
    <article className="flex flex-col rounded-2xl border border-n-3 bg-n-1 p-5 transition-shadow duration-300 hover:shadow-lift dark:border-n-5 dark:bg-n-6">
      <div className="flex items-start justify-between gap-3">
        <h4 className="font-display text-[0.9375rem] font-semibold leading-5">{m.label}</h4>
        {m.value !== null && <Difference m={m} />}
      </div>
      <p className="mt-1 font-display text-xs text-n-4 dark:text-n-4d">{m.formula}</p>

      <div className="mt-4 min-h-10">
        {m.value !== null ? (
          <p className="font-display text-[2rem] font-bold leading-none tracking-tight tabular-nums">
            {metricValue(m.kind, m.value)}
          </p>
        ) : (
          <MissingValue m={m} actions={actions} />
        )}
      </div>

      <div className="mt-auto pt-5">
        <Bullet m={m} />
        <p className="mt-2 flex items-center gap-1.5 whitespace-nowrap font-display text-xs text-n-4 dark:text-n-4d">
          <span className="h-3 w-[3px] rounded-full bg-n-7 dark:bg-n-1" aria-hidden="true" />
          Benchmark
          <span className="font-semibold tabular-nums text-n-7 dark:text-n-1">
            {metricValue(m.kind, m.benchmark)}
          </span>
        </p>
      </div>
    </article>
  )
}

/** How the eight ratios stand, as one proportioned bar with its counts. */
function Scoreline({ metrics }: { metrics: InsightMetric[] }) {
  const counts: Record<Status, number> = { better: 0, worse: 0, level: 0, missing: 0 }
  for (const m of metrics) counts[status(m)] += 1
  const measured = metrics.length - counts.missing
  // Better and worse always show, even at zero; the other two only when
  // they have something in them.
  const parts = (
    [
      { key: 'better', label: 'Better than benchmark' },
      { key: 'level', label: 'Level' },
      { key: 'worse', label: 'Worse than benchmark' },
      { key: 'missing', label: 'Not measured yet' },
    ] as { key: Status; label: string }[]
  ).filter((p) => p.key === 'better' || p.key === 'worse' || counts[p.key] > 0)

  return (
    <section
      aria-label="How the ratios compare"
      className="rounded-2xl border border-n-3 bg-n-1 p-5 dark:border-n-5 dark:bg-n-6"
    >
      <p className="font-display text-lg font-semibold tracking-tight">
        {measured === 0
          ? 'No ratios measured yet'
          : `${counts.better} of ${measured} measured ratio${measured === 1 ? '' : 's'} ${counts.better === 1 ? 'outperforms' : 'outperform'} the benchmark`}
      </p>
      <div className="mt-4 flex h-3 gap-0.5 overflow-hidden rounded-full" aria-hidden="true">
        {parts
          .filter((p) => counts[p.key] > 0)
          .map((p) => (
            <div
              key={p.key}
              className={cn('h-full origin-left animate-grow-x', FILL[p.key])}
              style={{ flexGrow: counts[p.key] }}
            />
          ))}
      </div>
      <ul className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5 font-display text-xs text-n-4 dark:text-n-4d">
        {parts.map((p) => (
          <li key={p.key} className="flex items-center gap-1.5">
            <span className={cn('h-2.5 w-2.5 rounded-sm', FILL[p.key])} aria-hidden="true" />
            {p.label}
            <span className="font-semibold tabular-nums text-n-7 dark:text-n-1">{counts[p.key]}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}

export function InsightsDashboard({
  metrics,
  ...actions
}: { metrics: InsightMetric[] } & MetricActions) {
  const byKey = new Map(metrics.map((m) => [m.key, m]))
  return (
    <div className="space-y-8">
      <Scoreline metrics={metrics} />
      {GROUPS.map((g) => {
        const items = g.keys.map((k) => byKey.get(k)).filter(Boolean) as InsightMetric[]
        if (!items.length) return null
        return (
          <section key={g.title} aria-labelledby={`group-${g.title}`}>
            <div className="mb-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <h3 id={`group-${g.title}`} className="font-display text-base font-semibold">
                {g.title}
              </h3>
              <p className="text-sm text-n-4 dark:text-n-4d">{g.note}</p>
            </div>
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {items.map((m) => (
                <MetricCard key={m.key} m={m} actions={actions} />
              ))}
            </div>
          </section>
        )
      })}
    </div>
  )
}
