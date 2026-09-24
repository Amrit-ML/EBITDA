import { useEffect, useState } from 'react'
import { AlertTriangle, LayoutGrid, Loader2, Table2, Users } from 'lucide-react'
import { getInsights, saveHeadcount, type Insights } from '../api'
import { metricValue } from '../format'
import { cn } from '@/lib/utils'
import { ImprovementPlan, InsightsDashboard, Verdict } from './InsightsDashboard'

const count = (n: number) => n.toLocaleString(undefined, { maximumFractionDigits: 1 })

type Layout = 'dashboard' | 'table'

/** The last layout this browser chose; a convenience, so storage may fail. */
function savedLayout(): Layout {
  try {
    return localStorage.getItem('insights-layout') === 'table' ? 'table' : 'dashboard'
  } catch {
    return 'dashboard'
  }
}

function HeadcountForm({
  initial,
  saving,
  onSave,
  onCancel,
}: {
  initial: Insights['headcount']
  saving: boolean
  onSave: (total: number, sga: number | null) => void
  onCancel?: () => void
}) {
  const [total, setTotal] = useState(initial.total_fte ? String(initial.total_fte) : '')
  const [sga, setSga] = useState(initial.sga_fte != null ? String(initial.sga_fte) : '')
  const t = Number(total)
  const s = sga.trim() === '' ? null : Number(sga)
  const problem =
    !total || !(t > 0)
      ? 'Enter total employees'
      : s !== null && (!(s >= 0) || s > t)
        ? 'SG&A employees must be between 0 and the total'
        : null
  const input =
    'h-11 w-full rounded-xl border-2 border-n-3 bg-n-1 px-3 font-display text-base tabular-nums outline-none transition-colors focus:border-primary-1 dark:border-n-5 dark:bg-n-6'

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        if (!problem) onSave(t, s)
      }}
      className="mt-4 grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end"
    >
      <label className="block">
        <span className="mb-1.5 block font-display text-xs font-semibold text-n-4 dark:text-n-4d">
          Total employees (FTE)
        </span>
        <input
          id="total-fte"
          type="number"
          inputMode="decimal"
          min={1}
          step="any"
          value={total}
          onChange={(e) => setTotal(e.target.value)}
          placeholder="e.g. 1,200"
          className={input}
        />
      </label>
      <label className="block">
        <span className="mb-1.5 block font-display text-xs font-semibold text-n-4 dark:text-n-4d">
          SG&amp;A employees (FTE)
        </span>
        <input
          id="sga-fte"
          type="number"
          inputMode="decimal"
          min={0}
          step="any"
          value={sga}
          onChange={(e) => setSga(e.target.value)}
          placeholder="Optional"
          className={input}
        />
      </label>
      <div className="flex gap-2">
        {onCancel && (
          <button
            type="button"
            onClick={onCancel}
            className="h-11 rounded-xl border-2 border-n-3 px-4 font-display text-sm font-semibold transition-colors hover:border-n-4/40 dark:border-n-5"
          >
            Cancel
          </button>
        )}
        <button
          type="submit"
          disabled={!!problem || saving}
          title={problem ?? undefined}
          className="flex h-11 items-center gap-2 rounded-xl bg-primary-1 px-5 font-display text-sm font-semibold text-n-1 transition-colors hover:bg-primary-1/90 disabled:cursor-not-allowed disabled:bg-n-3 disabled:text-n-4 dark:disabled:bg-n-5 dark:disabled:text-n-4d"
        >
          {saving && <Loader2 className="h-4 w-4 motion-safe:animate-spin" aria-hidden="true" />}
          Save
        </button>
      </div>
    </form>
  )
}

export function InsightsView({
  companyId,
  industry,
  industryLabel,
  onUpload,
}: {
  companyId: string
  industry: string
  industryLabel: string
  /** Opens the P&L upload, for a ratio that needs the file read again. */
  onUpload: () => void
}) {
  const [data, setData] = useState<Insights | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [layout, setLayout] = useState<Layout>(savedLayout)

  function chooseLayout(l: Layout) {
    setLayout(l)
    try {
      localStorage.setItem('insights-layout', l)
    } catch {
      // Private windows can refuse storage; the choice still applies now.
    }
  }

  // A card's "Add employees" opens the headcount form at the right field.
  function requestHeadcount(field: 'total-fte' | 'sga-fte') {
    setEditing(true)
    setTimeout(() => {
      const el = document.getElementById(field)
      if (!el) return
      // Scroll the content pane only. scrollIntoView also scrolls the page
      // itself, which is overflow-hidden but still scrollable from script,
      // and that shifted the whole app frame up out of view.
      const pane = el.closest<HTMLElement>('[data-scroll-pane]')
      if (pane) {
        const offset = el.getBoundingClientRect().top - pane.getBoundingClientRect().top
        const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
        pane.scrollTo({
          top: pane.scrollTop + offset - pane.clientHeight / 3,
          behavior: reduce ? 'auto' : 'smooth',
        })
      }
      el.focus({ preventScroll: true })
    }, 0)
  }

  useEffect(() => {
    let live = true
    getInsights(companyId, industry)
      .then((d) => {
        if (!live) return
        setData(d)
        setError(null)
      })
      .catch((e: Error) => live && setError(e.message))
    return () => {
      live = false
    }
  }, [companyId, industry])

  async function save(total: number, sga: number | null) {
    setSaving(true)
    setError(null)
    try {
      setData(await saveHeadcount(companyId, industry, { total_fte: total, sga_fte: sga }))
      setEditing(false)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const head = data?.headcount
  const hasHeadcount = !!head?.total_fte

  // A sanity check on the one figure typed in by hand. Revenue per employee
  // far from any plausible level usually means a team's headcount was
  // entered, not the whole company's.
  const rpe = data?.metrics.find((m) => m.key === 'revenue_per_employee')
  const rpeRatio =
    rpe && rpe.value !== null && rpe.benchmark > 0 ? rpe.value / rpe.benchmark : null
  const headcountLooksWrong = rpeRatio !== null && (rpeRatio > 4 || rpeRatio < 0.25)

  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-display text-2xl font-bold tracking-tight">Overhead and productivity</h2>
          <p className="mt-1 text-base leading-6 text-n-4 dark:text-n-4d">
            Eight ratios from your P&amp;L, each compared with the {industryLabel.toLowerCase()} industry.
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <div
            role="radiogroup"
            aria-label="Layout"
            className="flex rounded-xl bg-n-2 p-1 dark:bg-n-7"
          >
            {(
              [
                { id: 'dashboard', label: 'Dashboard', icon: LayoutGrid },
                { id: 'table', label: 'Table', icon: Table2 },
              ] as const
            ).map((o) => (
              <button
                key={o.id}
                type="button"
                role="radio"
                aria-checked={layout === o.id}
                onClick={() => chooseLayout(o.id)}
                className={cn(
                  'flex h-8 items-center gap-1.5 rounded-lg px-3 font-display text-xs font-semibold transition-colors',
                  layout === o.id
                    ? 'bg-n-1 text-n-7 shadow-sm dark:bg-n-6 dark:text-n-1'
                    : 'text-n-4 hover:text-n-7 dark:text-n-4d dark:hover:text-n-1'
                )}
              >
                <o.icon className="h-3.5 w-3.5" aria-hidden="true" />
                {o.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {error && (
        <p
          role="alert"
          className="mt-4 rounded-xl bg-accent-1/10 px-4 py-3 text-sm leading-6 text-[#B23C08] dark:text-[#F08A5D]"
        >
          {error}
        </p>
      )}

      {!data && !error && (
        <div role="status" className="mt-10 flex items-center gap-3 text-n-4 dark:text-n-4d">
          <Loader2 className="h-5 w-5 motion-safe:animate-spin" aria-hidden="true" />
          Working out the ratios…
        </div>
      )}

      {data && (
        <>
          {/* Headcount: not on a P&L, so asked for once and kept with it. */}
          <section className="mt-6 rounded-xl bg-n-2 p-5 dark:bg-n-7" aria-labelledby="headcount-title">
            <div className="flex items-center gap-3">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-accent-2/15 text-accent-2">
                <Users className="h-5 w-5" aria-hidden="true" />
              </span>
              <div className="min-w-0 flex-1">
                <h3 id="headcount-title" className="font-display text-base font-semibold">
                  Headcount
                </h3>
                <p className="text-sm leading-5 text-n-4 dark:text-n-4d">
                  {hasHeadcount
                    ? `${count(head!.total_fte!)} employees${head!.sga_fte != null ? `, ${count(head!.sga_fte)} in SG&A` : ''}`
                    : 'A P&L has no headcount, so enter it once. Five of the eight ratios use it.'}
                </p>
              </div>
              {hasHeadcount && !editing && (
                <button
                  type="button"
                  onClick={() => setEditing(true)}
                  className="h-9 shrink-0 rounded-lg border-2 border-n-3 px-3.5 font-display text-sm font-semibold transition-colors hover:border-n-4/40 dark:border-n-5"
                >
                  Edit
                </button>
              )}
            </div>
            {hasHeadcount && !editing && headcountLooksWrong && (
              <p className="mt-4 flex gap-2 rounded-lg bg-accent-5/10 px-3 py-2.5 text-sm leading-5 text-[#8A5F00] dark:text-accent-5">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                <span>
                  At {count(head!.total_fte!)} employees, revenue per employee is{' '}
                  <span className="font-semibold">{metricValue('usd', rpe!.value!)}</span>,{' '}
                  {rpeRatio! > 1
                    ? `${rpeRatio!.toFixed(1)}× the benchmark`
                    : 'under a quarter of the benchmark'}
                  . Check this is the whole company's headcount, not one team's.
                </span>
              </p>
            )}
            {(!hasHeadcount || editing) && (
              <HeadcountForm
                initial={data.headcount}
                saving={saving}
                onSave={save}
                onCancel={hasHeadcount ? () => setEditing(false) : undefined}
              />
            )}
          </section>

          {layout === 'dashboard' ? (
            <div className="mt-6">
              <InsightsDashboard
                metrics={data.metrics}
                improvements={data.improvements}
                onAddHeadcount={requestHeadcount}
                onUpload={onUpload}
              />
            </div>
          ) : (
          <>
          <div className="mt-6">
            <ImprovementPlan items={data.improvements} />
          </div>
          <div className="scroll-quiet mt-6 overflow-x-auto rounded-xl border border-n-3 dark:border-n-5">
            <table className="w-full min-w-[34rem] font-display text-sm">
              <thead className="whitespace-nowrap bg-n-2 text-left text-xs text-n-4 dark:bg-n-7 dark:text-n-4d">
                <tr>
                  <th scope="col" className="px-4 py-3 font-semibold">Metric</th>
                  <th scope="col" className="px-4 py-3 text-right font-semibold">You</th>
                  <th scope="col" className="px-4 py-3 text-right font-semibold">Industry</th>
                  <th scope="col" className="px-4 py-3 font-semibold">Variance to industry</th>
                </tr>
              </thead>
              <tbody>
                {data.metrics.map((m) => (
                  <tr key={m.key} className="border-t border-n-3 align-middle dark:border-n-5">
                    <th scope="row" className="px-4 py-3 text-left font-semibold">
                      {m.label}
                    </th>
                    <td className="px-4 py-3 text-right font-semibold tabular-nums">
                      {m.value === null ? '—' : metricValue(m.kind, m.value)}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums text-n-4 dark:text-n-4d">
                      {metricValue(m.kind, m.benchmark)}
                      {m.benchmark_source === 'example' && (
                        <span className="block text-[0.6875rem]">example</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      {m.value === null ? (
                        <span className="text-xs text-n-4 dark:text-n-4d">{m.missing}</span>
                      ) : (
                        <Verdict m={m} className="whitespace-nowrap" />
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          </>
          )}

          <ul className="mt-4 space-y-1 text-xs leading-5 text-n-4 dark:text-n-4d">
            <li>
              Industry means US listed {industryLabel.toLowerCase()} companies. Green indicates a
              favourable variance to the industry, amber an unfavourable one. For cost
              ratios such as SG&amp;A a lower figure is favourable; for output per employee a higher
              figure is favourable.
            </li>
            <li>
              Percentages are compared in percentage points (pp). Dollar figures are compared in
              percent, because percentage points do not apply to dollars.
            </li>
            <li>
              {data.growth_basis
                ? `Growth is measured from ${data.growth_basis}, the periods in your P&L.`
                : 'Growth needs a P&L with two or more periods.'}
            </li>
            {data.benchmark_source_note && (
              <li>
                Industry figures for the SG&amp;A ratios: {data.benchmark_source_note}. These are
                industry totals, so large companies weigh more.
              </li>
            )}
            {data.benchmarks_are_placeholder && (
              <li>
                Industry figures marked example are placeholders: no public source reports
                growth or headcount for the industry yet.
              </li>
            )}
          </ul>
        </>
      )}
    </div>
  )
}
