import { ArrowDown, ArrowUp, Upload, UserPlus } from 'lucide-react'
import type { Improvement, InsightMetric } from '../api'
import { metricDifference, metricValue } from '../format'
import { cn } from '@/lib/utils'

type Status = 'better' | 'worse' | 'level' | 'missing'

const status = (m: InsightMetric): Status =>
  m.value === null ? 'missing' : m.favourable === null ? 'level' : m.favourable ? 'better' : 'worse'

// Bars run a light-to-deep gradient toward their value end. Light mode ends
// on deeper tones than the brand green and amber to keep 3:1 against the
// white card; dark mode can end on the brand colours.
const FILL: Record<Status, string> = {
  better: 'bg-gradient-to-r from-[#5CCF93] to-[#1F9D55] dark:from-primary-2/50 dark:to-primary-2',
  worse: 'bg-gradient-to-r from-[#E4BA6A] to-[#B7791F] dark:from-accent-5/50 dark:to-accent-5',
  level: 'bg-gradient-to-r from-n-4/50 to-n-4 dark:from-n-4d/50 dark:to-n-4d',
  missing: 'bg-n-3 dark:bg-n-5',
}

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

/** The variance to the industry in standard reporting terms:
 *  "Unfavourable · 12.1 pp above industry". The arrow gives the direction, the word and colour
 *  the verdict, so the verdict never rests on colour alone. */
export function Verdict({ m, className }: { m: InsightMetric; className?: string }) {
  if (m.difference === null) return null
  if (m.favourable === null) {
    return (
      <p className={cn('font-display text-sm font-semibold text-n-4 dark:text-n-4d', className)}>
        In line with industry
      </p>
    )
  }
  const x = multipleOf(m)
  // Unsigned: the words "above" and "below" carry the direction.
  const gap = metricDifference(Math.abs(m.difference), m.difference_unit).replace(/^\+/, '')
  const detail =
    x !== null ? `${x.toFixed(1)}× industry` : `${gap} ${m.difference > 0 ? 'above' : 'below'} industry`
  const good = m.favourable
  const Arrow = m.difference > 0 ? ArrowUp : ArrowDown
  return (
    <p className={cn('flex flex-wrap items-center gap-x-1.5 font-display text-sm text-n-4 dark:text-n-4d', className)}>
      <span
        className={cn(
          'font-semibold',
          good ? 'text-[#178A43] dark:text-primary-2' : 'text-[#8A5F00] dark:text-accent-5'
        )}
      >
        {good ? 'Favourable' : 'Unfavourable'}
      </span>
      <span className="inline-flex items-center gap-0.5 tabular-nums">
        · <Arrow className="h-3.5 w-3.5" aria-hidden="true" />
        {detail}
      </span>
    </p>
  )
}

interface BarRow {
  label: string
  value: number | null
  text: string
  fill: string
}

/** A two-bar comparison: each row a label, a bar from zero, and its value.
 *  Plain lengths against a shared scale, so "which is bigger" is read at a
 *  glance. If either value is negative (a loss, a shrinking line), zero moves
 *  to the middle and bars run left or right of it. */
function CompareBars({ rows, label }: { rows: BarRow[]; label: string }) {
  const nums = rows.map((r) => r.value).filter((v): v is number => v !== null)
  const max = Math.max(...nums.map(Math.abs), 0) || 1
  const diverging = nums.some((v) => v < 0)
  const zero = diverging ? 50 : 0
  const span = diverging ? 50 : 100
  return (
    <div role="img" aria-label={label} className="space-y-2">
      {rows.map((r) => {
        const w = r.value === null ? 0 : (Math.abs(r.value) / max) * span
        const left = r.value !== null && r.value < 0 ? zero - w : zero
        return (
          <div
            key={r.label}
            title={`${r.label}: ${r.text}`}
            className="grid grid-cols-[4.75rem_1fr_4rem] items-center gap-2 font-display text-xs"
          >
            <span className="truncate text-n-4 dark:text-n-4d">{r.label}</span>
            <div className="relative h-4">
              {diverging && (
                <div className="absolute inset-y-0 w-px bg-n-4/40" style={{ left: `${zero}%` }} />
              )}
              {w > 0 && (
                <div
                  className={cn('absolute inset-y-0 animate-grow-x rounded', r.fill)}
                  style={{
                    left: `${left}%`,
                    width: `${w}%`,
                    transformOrigin: r.value! < 0 ? 'right' : 'left',
                  }}
                />
              )}
            </div>
            <span className="text-right font-semibold tabular-nums text-n-7 dark:text-n-1">
              {r.text}
            </span>
          </div>
        )
      })}
    </div>
  )
}

const PEER_FILL = 'bg-gradient-to-r from-n-3 to-n-4/50 dark:from-n-5 dark:to-n-4d/60'

/** What each card charts. Most compare you with the industry; the growth card
 *  compares your two growth rates, which is what its 0.0 pp gap is made of. */
function chartRows(m: InsightMetric): BarRow[] {
  if (m.parts) {
    const pct = (v: number) => metricDifference(v * 100, '%')
    return [
      { label: 'SG&A', value: m.parts.sga_growth, text: pct(m.parts.sga_growth), fill: FILL[status(m)] },
      { label: 'Revenue', value: m.parts.revenue_growth, text: pct(m.parts.revenue_growth), fill: PEER_FILL },
    ]
  }
  return [
    {
      label: 'You',
      value: m.value,
      text: m.value === null ? '—' : metricValue(m.kind, m.value),
      fill: FILL[status(m)],
    },
    { label: 'Industry', value: m.benchmark, text: metricValue(m.kind, m.benchmark), fill: PEER_FILL },
  ]
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
    // Subgrid rows: a title that wraps to two lines pushes its whole row of
    // cards down together, so values and bars stay level across the row.
    <article className="row-span-3 grid grid-rows-subgrid gap-y-0 rounded-2xl border border-n-3 bg-gradient-to-b from-n-1 to-n-2/70 p-5 transition-shadow duration-300 hover:shadow-lift dark:border-n-5 dark:from-n-6 dark:to-n-7/60">
      <h4 className="font-display text-[0.9375rem] font-semibold leading-5">{m.label}</h4>

      <div className="mt-4 min-h-10">
        {m.value !== null ? (
          <>
            <p className="font-display text-[2rem] font-bold leading-none tracking-tight tabular-nums">
              {metricValue(m.kind, m.value)}
            </p>
            <Verdict m={m} className="mt-2" />
          </>
        ) : (
          <MissingValue m={m} actions={actions} />
        )}
      </div>

      <div className="self-end pt-5">
        <CompareBars
          rows={chartRows(m)}
          label={chartRows(m).map((r) => `${r.label} ${r.text}`).join(', ')}
        />
        <p className="mt-3 font-display text-[0.6875rem] text-n-4 dark:text-n-4d">
          {m.benchmark_source === 'damodaran'
            ? 'Industry figure: Damodaran, NYU Stern'
            : 'Industry figure: example, not real data yet'}
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
  // Favourable and unfavourable always show, even at zero; the other two only when
  // they have something in them.
  const parts = (
    [
      { key: 'better', label: 'Favourable' },
      { key: 'level', label: 'In line' },
      { key: 'worse', label: 'Unfavourable' },
      { key: 'missing', label: 'Not yet measured' },
    ] as { key: Status; label: string }[]
  ).filter((p) => p.key === 'better' || p.key === 'worse' || counts[p.key] > 0)

  return (
    <section
      aria-label="How the ratios compare"
      className="rounded-2xl border border-n-3 bg-gradient-to-br from-primary-1/[0.07] via-n-1 to-n-1 p-5 dark:border-n-5 dark:from-primary-1d/15 dark:via-n-6 dark:to-n-6"
    >
      <p className="font-display text-lg font-semibold tracking-tight">
        {measured === 0
          ? 'No ratios measured yet'
          : `${counts.better} of ${measured} ratio${measured === 1 ? '' : 's'} favourable to industry`}
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

/** The improvement agenda: each unfavourable ratio, largest gap first, with
 *  where to look, why it matters and a first step. No savings figures. */
export function ImprovementPlan({ items }: { items: Improvement[] }) {
  return (
    <section
      aria-labelledby="where-to-improve"
      className="rounded-2xl border border-n-3 bg-gradient-to-br from-accent-5/[0.08] via-n-1 to-n-1 p-5 dark:border-n-5 dark:from-accent-5/10 dark:via-n-6 dark:to-n-6"
    >
      <h3 id="where-to-improve" className="font-display text-lg font-semibold tracking-tight">
        Where to improve
      </h3>
      {items.length === 0 ? (
        <p className="mt-1 text-sm text-n-4 dark:text-n-4d">
          Every measured ratio is in line with or favourable to the industry.
        </p>
      ) : (
        <>
          <p className="mt-1 text-sm text-n-4 dark:text-n-4d">
            Unfavourable ratios, largest gap first, each with where to start.
          </p>
          <ol className="mt-4 divide-y divide-n-3 dark:divide-n-5">
            {items.map((i, n) => (
              <li key={i.key} className="flex gap-4 py-4 first:pt-0 last:pb-0">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-[#E4BA6A] to-[#B7791F] font-display text-sm font-bold text-white">
                  {n + 1}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 font-display">
                    <span className="text-[0.9375rem] font-semibold">{i.area}</span>
                    <span className="text-xs text-n-4 dark:text-n-4d">
                      {i.label} ·{' '}
                      {metricDifference(Math.abs(i.difference), i.difference_unit).replace(/^\+/, '')}{' '}
                      {i.difference > 0 ? 'above' : 'below'} industry
                    </span>
                  </p>
                  <p className="mt-1 text-sm leading-6 text-n-4 dark:text-n-4d">{i.why}</p>
                  <p className="mt-1 text-sm leading-6">
                    <span className="font-display font-semibold">First step: </span>
                    {i.first_step}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        </>
      )}
    </section>
  )
}

export function InsightsDashboard({
  metrics,
  improvements,
  ...actions
}: { metrics: InsightMetric[]; improvements: Improvement[] } & MetricActions) {
  const byKey = new Map(metrics.map((m) => [m.key, m]))
  return (
    <div className="space-y-8">
      <Scoreline metrics={metrics} />
      <ImprovementPlan items={improvements} />
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
            <div className="grid gap-x-4 gap-y-4 sm:grid-cols-2 xl:grid-cols-3">
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
