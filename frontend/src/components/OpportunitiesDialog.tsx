import { useState } from 'react'
import { Check, Copy } from 'lucide-react'
import type { CompanySummary, Finding } from '../types'
import { money } from '../format'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { cn } from '@/lib/utils'

// One marker colour per cost line, kept wherever that line appears.
const DRIVER_COLOR: Record<string, string> = {
  ga_pct: 'bg-accent-3',
  sales_marketing_pct: 'bg-accent-2',
  advertising_pct: 'bg-accent-1',
  facilities_pct: 'bg-accent-5',
  capex_pct: 'bg-accent-4',
}

/** Where the cost stands today, in words: "Spends more than 8 in 10 similar
 *  companies". The percentile is the share of peers that spend less. */
function rank(f: Finding): string | null {
  const p = f.percentile_now
  if (p === undefined) return null
  if (p < 50) return 'Below the typical similar company'
  return `Spends more than ${Math.min(9, Math.round(p / 10))} in 10 similar companies`
}

function flags(f: Finding): string[] {
  return [
    f.ebitda_role === 'cash' && 'Cash, not EBITDA',
    f.ebitda_role === 'growth' && 'Growth spend',
    f.unsupported && 'Not yet confirmed',
  ].filter(Boolean) as string[]
}

/** Plain text of what was found, for pasting into a memo or an email. */
function summaryText(findings: Finding[], pl: CompanySummary | null, industryLabel: string) {
  const lines: string[] = []
  if (pl) {
    lines.push(
      `EBITDA diagnostic: FY${pl.fiscal_year} P&L, ${money(pl.revenue, 0)} revenue, compared with ${industryLabel.toLowerCase()} companies`,
      ''
    )
  }
  lines.push(`Opportunities found: ${findings.length}`)
  findings.forEach((f, i) => {
    const where = [f.label, rank(f)?.toLowerCase()].filter(Boolean).join('; ')
    lines.push('', `${i + 1}. ${f.lever} (${where})`)
    if (f.rationale) lines.push(`   Why: ${f.rationale}`)
    if (f.first_step) lines.push(`   First step: ${f.first_step}`)
  })
  return lines.join('\n')
}

function OpportunityItem({ f }: { f: Finding }) {
  const r = rank(f)
  return (
    <li className="rounded-xl border border-n-3 p-4 duration-300 animate-in fade-in-0 slide-in-from-bottom-1 dark:border-n-5">
      <div className="flex gap-3">
        <span
          className={cn('mt-1.5 h-3.5 w-3.5 shrink-0 rounded', DRIVER_COLOR[f.driver] ?? 'bg-n-4')}
          aria-hidden="true"
        />
        <div className="min-w-0 flex-1">
          <p className="font-display text-base font-semibold leading-6 first-letter:uppercase">
            {f.lever}
          </p>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5 font-display text-xs">
            <span className="font-medium text-n-4 dark:text-n-4d">{f.label}</span>
            {r && (
              <span className="rounded bg-n-2 px-1.5 py-0.5 font-semibold text-n-7 dark:bg-n-7 dark:text-n-1">
                {r}
              </span>
            )}
            {flags(f).map((x) => (
              <span
                key={x}
                className="rounded bg-accent-5/15 px-1.5 py-0.5 font-semibold text-[#8A5F00] dark:text-accent-5"
              >
                {x}
              </span>
            ))}
          </div>
          {f.rationale && (
            <p className="mt-3 text-sm leading-6">
              <span className="font-display font-semibold">Why: </span>
              {f.rationale}
            </p>
          )}
          {f.first_step && (
            <p className="mt-1 text-sm leading-6">
              <span className="font-display font-semibold">First step: </span>
              {f.first_step}
            </p>
          )}
        </div>
      </div>
    </li>
  )
}

export function OpportunitiesDialog({
  open,
  onOpenChange,
  findings,
  pl,
  industryLabel,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  findings: Finding[]
  pl: CompanySummary | null
  industryLabel: string
}) {
  const [copied, setCopied] = useState(false)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-[40rem]">
        <DialogTitle>Opportunities</DialogTitle>
        <DialogDescription>
          What the diagnostic has found so far: where a cost is out of line with{' '}
          {industryLabel.toLowerCase()} companies, why, and where to start.
        </DialogDescription>

        {findings.length === 0 ? (
          <p className="mt-6 rounded-xl bg-n-2 px-4 py-3 text-sm leading-6 text-n-4 dark:bg-n-7 dark:text-n-4d">
            None yet. Each one appears here as soon as the agent has confirmed it with you.
          </p>
        ) : (
          <>
            <ol className="scroll-quiet -mx-1 mt-6 max-h-[55vh] space-y-3 overflow-y-auto px-1">
              {findings.map((f) => (
                <OpportunityItem key={f.id} f={f} />
              ))}
            </ol>
            <div className="mt-6 flex justify-end">
              <button
                type="button"
                onClick={() => {
                  navigator.clipboard?.writeText(summaryText(findings, pl, industryLabel)).then(
                    () => {
                      setCopied(true)
                      setTimeout(() => setCopied(false), 1500)
                    },
                    () => {}
                  )
                }}
                className="flex h-10 items-center gap-2 rounded-xl border-2 border-n-3 px-3.5 font-display text-sm font-semibold transition hover:border-n-4/40 active:scale-[0.97] dark:border-n-5 dark:hover:border-n-4"
                title="Copy the opportunities as text for a memo or email"
              >
                {copied ? (
                  <Check
                    className="h-4 w-4 text-[#178A43] duration-200 animate-in zoom-in-50 dark:text-primary-2"
                    strokeWidth={2.5}
                    aria-hidden="true"
                  />
                ) : (
                  <Copy className="h-4 w-4" aria-hidden="true" />
                )}
                {copied ? 'Copied' : 'Copy summary'}
              </button>
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}
