import type { EbitdaHistory, TrendAnalysis } from '../api'
import { money, shortPeriod } from '../format'
import { cn } from '@/lib/utils'
import { TrendChart } from './TrendChart'

const label = 'font-display text-sm font-semibold text-n-4 dark:text-n-4d'

function StatusPill({ pct }: { pct: number | null }) {
  if (pct === null) return null
  const ahead = pct >= 5
  const behind = pct <= -5
  return (
    <span
      className={cn(
        'shrink-0 rounded-md px-2 py-0.5 font-display text-xs font-semibold tabular-nums',
        ahead && 'bg-primary-2/15 text-[#178A43] dark:text-primary-2',
        behind && 'bg-accent-5/15 text-[#8A5F00] dark:text-accent-5',
        !ahead && !behind && 'bg-n-3 text-n-4 dark:bg-n-5 dark:text-n-4d'
      )}
    >
      {pct >= 0 ? '+' : '−'}
      {Math.abs(pct).toFixed(0)}% vs usual
    </span>
  )
}

function Trend({ t }: { t: TrendAnalysis }) {
  const quarterly = t.periods.every((p) => /\bQ[1-4]\b/i.test(p))
  const unit = quarterly ? 'quarter' : 'period'
  const prior = t.periods.length - 1
  return (
    <section
      aria-labelledby="trend-title"
      className="rounded-xl border border-n-3 p-5 duration-500 animate-in fade-in-0 dark:border-n-5"
    >
      <div className="flex items-center justify-between gap-3">
        <h3 id="trend-title" className={label}>
          EBITDA by {unit}
        </h3>
        <StatusPill pct={t.variance_pct} />
      </div>

      {/* Chart and table side by side where there is room for both. */}
      <div className="mt-4 grid gap-6 md:grid-cols-[minmax(0,3fr)_minmax(0,2fr)] md:items-start">
        <div>
          <TrendChart data={t} />

          {/* Markers sit in a box one line tall, so they stay beside the
              first line when the text wraps. */}
          <div className="mt-3 space-y-1.5 font-display text-xs leading-4 text-n-4 dark:text-n-4d">
            <p className="flex items-start gap-2">
              <span className="flex h-4 w-2.5 shrink-0 items-center" aria-hidden="true">
                <span className="h-2.5 w-2.5 rounded-sm bg-primary-1 dark:bg-primary-1d" />
              </span>
              <span>
                <span className="font-semibold text-n-7 dark:text-n-1">{t.current_period}</span>,
                the latest {unit}
              </span>
            </p>
            <p className="flex items-start gap-2">
              <svg width="10" height="16" className="shrink-0" aria-hidden="true">
                <line
                  x1="0" x2="10" y1="8" y2="8" strokeDasharray="3 2" strokeWidth="1.5"
                  className="stroke-n-7 dark:stroke-n-1"
                />
              </svg>
              <span>
                Usual level{' '}
                <span className="font-semibold tabular-nums text-n-7 dark:text-n-1">
                  {money(t.historical_average)}
                </span>
                {prior > 0 &&
                  `, the average of the ${prior} ${unit}${prior === 1 ? '' : 's'} before`}
              </span>
            </p>
          </div>
        </div>

        <table className="w-full font-display text-sm tabular-nums">
          <thead>
            <tr className="text-xs text-n-4 dark:text-n-4d">
              <th scope="col" className="pb-2 text-left font-medium capitalize">
                {unit}
              </th>
              <th scope="col" className="pb-2 text-right font-medium">EBITDA</th>
              <th scope="col" className="pb-2 text-right font-medium">vs usual</th>
            </tr>
          </thead>
          <tbody>
            {t.ebitda.map((v, i) => {
              const d = v - t.historical_average
              const current = i === t.ebitda.length - 1
              return (
                <tr
                  key={t.periods[i]}
                  className={cn('border-t border-n-3 dark:border-n-5', current && 'font-semibold')}
                >
                  <td className="py-2 text-left">{shortPeriod(t.periods[i])}</td>
                  <td className="py-2 text-right">{money(v)}</td>
                  <td className={cn('py-2 text-right', !current && 'text-n-4 dark:text-n-4d')}>
                    {/* Within half a percent reads as level, not "+$0". */}
                    {Math.abs(d) < Math.abs(t.historical_average) * 0.005
                      ? 'at usual'
                      : `${d >= 0 ? '+' : '−'}${money(Math.abs(d))}`}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <p className="mt-4 text-sm leading-6 text-n-4 dark:text-n-4d">{t.commentary}</p>
    </section>
  )
}

/** EBITDA over time, from the P&L itself: the periods in the current file,
 *  and, once there are more, the history across every upload. */
export function TrendSection({
  trend,
  history,
}: {
  trend: TrendAnalysis | null
  history: EbitdaHistory | null
}) {
  // The accumulated history only adds something once it reaches beyond the
  // periods already charted from the current file.
  const showHistory =
    !!history &&
    history.historical_average !== null &&
    history.count > (trend?.periods.length ?? 0)
  if (!trend && !showHistory) return null

  return (
    <div className="space-y-4">
      <div>
        <h2 className="font-display text-2xl font-bold tracking-tight">EBITDA trend</h2>
        <p className="mt-1 text-base leading-6 text-n-4 dark:text-n-4d">
          From your own P&amp;L, so no benchmark is involved.
        </p>
      </div>
      {trend && <Trend t={trend} />}
      {showHistory && (
        <section className="rounded-xl border border-n-3 p-4 duration-500 animate-in fade-in-0 dark:border-n-5">
          <div className="flex items-center justify-between gap-3">
            <h3 className={label}>Across all your uploads</h3>
            <StatusPill pct={history!.variance_pct} />
          </div>
          <p className="mt-2 text-sm leading-6">{history!.message}</p>
        </section>
      )}
    </div>
  )
}
