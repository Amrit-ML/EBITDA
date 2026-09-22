import { ArrowRight, Check, FileText, Play, Upload } from 'lucide-react'
import type { CompanySummary } from '../types'
import { money } from '../format'
import { cn } from '@/lib/utils'

interface Props {
  pl: CompanySummary | null
  industryLabel: string
  docCount: number
  busy: boolean
  onUpload: () => void
  onDocs: () => void
  onStart: () => void
}

// Rises into place on arrival; items stagger by setting their own delay.
const enter = 'animate-in fade-in-0 slide-in-from-bottom-3 duration-500 ease-out fill-mode-both'

/** The empty conversation: the three things to do, in order. */
export function Welcome(p: Props) {
  const steps = [
    {
      key: 'upload',
      icon: Upload,
      tile: 'bg-accent-2/15 text-accent-2',
      title: p.pl ? 'P&L uploaded' : 'Upload your P&L',
      detail: p.pl
        ? `FY${p.pl.fiscal_year} · ${money(p.pl.revenue, 0)} revenue · select to replace`
        : 'CSV, Excel, PDF or PowerPoint',
      done: !!p.pl,
      disabled: p.busy,
      onClick: p.onUpload,
    },
    {
      key: 'docs',
      icon: FileText,
      tile: 'bg-accent-3/15 text-accent-3',
      title: 'Add company documents',
      detail: p.docCount
        ? `${p.docCount} added · the agent reads these before asking you`
        : 'Optional · org charts, contracts, leases',
      done: p.docCount > 0,
      disabled: !p.pl || p.busy,
      onClick: p.onDocs,
    },
    {
      key: 'start',
      icon: Play,
      tile: 'bg-primary-2/15 text-[#178A43] dark:text-primary-2',
      title: 'Start the diagnostic',
      detail: p.pl
        ? `Compared with ${p.industryLabel.toLowerCase()} companies`
        : 'Upload a P&L first',
      done: false,
      disabled: !p.pl || p.busy,
      onClick: p.onStart,
    },
  ]

  return (
    <div className="mx-auto max-w-[43.75rem] pt-6 lg:pt-12">
      <h1 className={cn(enter, 'text-balance text-center font-display text-[2rem] font-bold leading-tight tracking-[-0.03em] lg:text-[2.75rem]')}>
        Find the EBITDA you can capture
      </h1>
      <p
        className={cn(enter, 'mx-auto mt-3 max-w-[36rem] text-balance text-center text-lg leading-7 text-n-4 lg:text-xl lg:leading-8 dark:text-n-4d')}
        style={{ animationDelay: '80ms' }}
      >
        Compare your costs with US public companies, then work through each gap with the
        agent.
      </p>

      <ol className="mx-auto mt-10 max-w-[31rem] space-y-4 lg:mt-12">
        {steps.map((s, i) => (
          <li key={s.key} className={enter} style={{ animationDelay: `${180 + i * 80}ms` }}>
            <button
              type="button"
              onClick={s.onClick}
              disabled={s.disabled}
              className={cn(
                'group flex w-full items-center gap-4 rounded-xl border border-n-3 bg-n-1 p-3.5 pr-4 text-left transition-[box-shadow,border-color,background-color,opacity,transform] duration-200 sm:gap-5 sm:pr-6 dark:border-n-5 dark:bg-n-6',
                'enabled:hover:border-transparent enabled:hover:shadow-lift enabled:active:scale-[0.99] dark:enabled:hover:border-n-5 dark:enabled:hover:bg-n-7',
                'disabled:cursor-not-allowed disabled:opacity-50'
              )}
            >
              <span
                className={cn(
                  'flex h-12 w-12 shrink-0 items-center justify-center rounded-lg sm:h-[3.75rem] sm:w-[3.75rem]',
                  s.tile
                )}
              >
                <s.icon className="h-6 w-6" aria-hidden="true" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block font-display text-[1.0625rem] font-semibold">
                  {s.title}
                </span>
                <span className="mt-0.5 block text-sm leading-5 text-n-4 dark:text-n-4d">
                  {s.detail}
                </span>
              </span>
              {s.done ? (
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary-2 text-n-7 duration-300 animate-in fade-in-0 zoom-in-50">
                  <Check className="h-4 w-4" strokeWidth={3} aria-hidden="true" />
                  <span className="sr-only">Done</span>
                </span>
              ) : (
                <ArrowRight
                  className="h-6 w-6 shrink-0 text-n-4 transition-transform group-enabled:group-hover:translate-x-1 group-enabled:group-hover:text-n-7 dark:text-n-4d dark:group-enabled:group-hover:text-n-1"
                  aria-hidden="true"
                />
              )}
            </button>
          </li>
        ))}
      </ol>
    </div>
  )
}
