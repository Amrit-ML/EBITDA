import { useState } from 'react'
import {
  ChevronDown,
  FileSpreadsheet,
  FileText,
  Gauge,
  MessagesSquare,
  Moon,
  Sun,
  Trash2,
  X,
} from 'lucide-react'
import type { SessionSummary } from '../api'
import type { CompanySummary, Industry } from '../types'
import { money } from '../format'
import type { Theme } from '@/lib/theme'
import { cn } from '@/lib/utils'
import { Wordmark } from './Logo'

// Each industry keeps one marker colour wherever it appears.
const INDUSTRY_COLOR: Record<string, string> = {
  biotech: 'bg-accent-2',
  pharma: 'bg-accent-3',
}
const INDUSTRY_SHORT: Record<string, string> = { biotech: 'Biotech', pharma: 'Pharma' }

/** The two pages the sidebar switches between. */
export type View = 'diagnostic' | 'insights'

interface Props {
  industries: Industry[]
  industryId: string
  onIndustry: (id: string) => void
  pl: CompanySummary | null
  docCount: number
  busy: boolean
  onUpload: () => void
  onDocs: () => void
  theme: Theme
  onTheme: (t: Theme) => void
  sessions: SessionSummary[]
  activeSessionId: string | null
  onOpenSession: (id: string) => void
  onDeleteSession: (id: string) => void
  view: View
  onView: (v: View) => void
  /** Present when the sidebar is shown as a drawer on a small screen. */
  onClose?: () => void
}

/** "12:05 pm" today, "Yesterday", "Sep 18" this year, else "Sep 18, 2025". */
function when(seconds: number) {
  const d = new Date(seconds * 1000)
  const now = new Date()
  const day = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime()
  const days = Math.round((day(now) - day(d)) / 86_400_000)
  if (days === 0) return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
  if (days === 1) return 'Yesterday'
  return d.toLocaleDateString([], {
    month: 'short',
    day: 'numeric',
    ...(d.getFullYear() !== now.getFullYear() && { year: 'numeric' }),
  })
}

function HistoryItem({
  s,
  active,
  busy,
  onOpen,
  onDelete,
}: {
  s: SessionSummary
  active: boolean
  busy: boolean
  onOpen: () => void
  onDelete: () => void
}) {
  // Deleting takes two clicks: the first arms it, the second confirms.
  const [armed, setArmed] = useState(false)
  // Kept short enough to fit beside the time: the year moves to the second
  // line, where it had been pushing the revenue out of view.
  const title = [INDUSTRY_SHORT[s.industry] ?? s.industry, s.revenue && money(s.revenue, 0)]
    .filter(Boolean)
    .join(' · ')
  const progress =
    s.findings_count > 0
      ? `${s.findings_count} ${s.findings_count === 1 ? 'opportunity' : 'opportunities'}`
      : `${s.message_count} message${s.message_count === 1 ? '' : 's'}`

  return (
    <li className="group relative" onMouseLeave={() => setArmed(false)}>
      <button
        type="button"
        onClick={onOpen}
        disabled={busy}
        aria-current={active ? 'true' : undefined}
        title={s.preview}
        className={cn(
          'flex w-full flex-col gap-0.5 rounded-lg px-4 py-2.5 text-left transition-colors disabled:cursor-not-allowed',
          active ? 'bg-n-6 shadow-pill' : 'hover:bg-n-6/60'
        )}
      >
        <span className="flex w-full items-center gap-2.5">
          <span
            className={cn('h-2.5 w-2.5 shrink-0 rounded-sm', INDUSTRY_COLOR[s.industry] ?? 'bg-n-4')}
            aria-hidden="true"
          />
          <span
            className={cn(
              'min-w-0 flex-1 truncate font-display text-sm font-semibold',
              active ? 'text-n-1' : 'text-n-3/90'
            )}
          >
            {title}
          </span>
          <span className="shrink-0 font-display text-xs tabular-nums text-n-4d">
            {when(s.updated_at)}
          </span>
        </span>
        <span className="truncate pl-5 font-display text-xs text-n-4d">
          {s.fiscal_year ? `FY${s.fiscal_year} · ` : ''}
          <span className={cn(s.findings_count > 0 && 'font-semibold text-primary-2')}>
            {progress}
          </span>
        </span>
      </button>
      <button
        type="button"
        onClick={() => (armed ? onDelete() : setArmed(true))}
        onBlur={() => setArmed(false)}
        disabled={busy}
        className={cn(
          'absolute right-2 top-1/2 flex h-8 -translate-y-1/2 items-center justify-center rounded-md font-display text-xs font-semibold transition-opacity focus:opacity-100 group-hover:opacity-100 disabled:hidden',
          armed
            ? 'bg-accent-1 px-2.5 text-n-1 opacity-100'
            : 'w-8 bg-n-6 text-n-4d opacity-0 hover:text-n-1'
        )}
        aria-label={armed ? 'Confirm delete' : `Delete ${title}`}
      >
        {armed ? 'Delete' : <Trash2 className="h-4 w-4" aria-hidden="true" />}
      </button>
    </li>
  )
}

export function Sidebar(p: Props) {
  const [industriesOpen, setIndustriesOpen] = useState(true)
  const [historyOpen, setHistoryOpen] = useState(true)

  return (
    <nav
      aria-label="Main"
      className="scroll-quiet flex h-full w-full flex-col overflow-y-auto bg-n-7 px-4 pb-4 pt-6"
    >
      <div className="flex items-center justify-between pl-3 pr-1">
        <Wordmark />
        {p.onClose && (
          <button
            type="button"
            onClick={p.onClose}
            className="flex h-10 w-10 items-center justify-center rounded-full text-n-4d hover:text-n-1"
            aria-label="Close menu"
          >
            <X className="h-5 w-5" />
          </button>
        )}
      </div>

      <div className="mt-10 space-y-1">
        {(
          [
            { id: 'diagnostic', label: 'Diagnostic', icon: MessagesSquare, tint: 'text-primary-1d', needsPl: false },
            { id: 'insights', label: 'Insights', icon: Gauge, tint: 'text-primary-2', needsPl: true },
          ] as const
        ).map((item) => {
          const active = p.view === item.id
          const blocked = item.needsPl && !p.pl
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => p.onView(item.id)}
              disabled={blocked}
              aria-current={active ? 'page' : undefined}
              title={blocked ? 'Upload a P&L first' : undefined}
              className={cn(
                'flex h-12 w-full items-center gap-3 rounded-lg px-4 font-display text-[0.9375rem] font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50',
                active
                  ? 'bg-gradient-to-l from-[#323337] to-[rgba(70,79,111,0.3)] text-n-1 shadow-pill'
                  : 'text-n-3/75 hover:text-n-1 disabled:hover:text-n-3/75'
              )}
            >
              <item.icon className={cn('h-5 w-5', item.tint)} aria-hidden="true" />
              {item.label}
            </button>
          )
        })}
        <button
          type="button"
          onClick={p.onDocs}
          disabled={!p.pl || p.busy}
          title={p.pl ? undefined : 'Upload a P&L first'}
          className="flex h-12 w-full items-center gap-3 rounded-lg px-4 font-display text-[0.9375rem] font-semibold text-n-3/75 transition-colors hover:text-n-1 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:text-n-3/75"
        >
          <FileText className="h-5 w-5 text-accent-1" aria-hidden="true" />
          <span className="flex-1 text-left">Company documents</span>
          {p.docCount > 0 && (
            <span className="rounded-md bg-n-6 px-2 py-0.5 font-display text-xs font-semibold text-n-4d">
              {p.docCount}
            </span>
          )}
        </button>
      </div>

      <div className="-mx-4 my-4 h-px bg-n-6" />

      <div>
        <button
          type="button"
          onClick={() => setIndustriesOpen((o) => !o)}
          aria-expanded={industriesOpen}
          className="flex h-12 w-full items-center gap-3 px-4 font-display text-sm font-semibold text-n-4d transition-colors hover:text-n-3"
        >
          <ChevronDown
            className={cn('h-5 w-5 transition-transform', !industriesOpen && '-rotate-90')}
            aria-hidden="true"
          />
          Compare against
        </button>
        {industriesOpen && (
          <div role="radiogroup" aria-label="Peer industry" className="space-y-1">
            {p.industries.map((i) => {
              const active = i.id === p.industryId
              return (
                <button
                  key={i.id}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  disabled={p.busy}
                  onClick={() => p.onIndustry(i.id)}
                  title={i.description}
                  className={cn(
                    'flex h-12 w-full items-center gap-3 rounded-lg px-4 font-display text-[0.9375rem] font-semibold transition-colors disabled:cursor-not-allowed',
                    active
                      ? 'bg-n-6 text-n-1 shadow-pill'
                      : 'text-n-3/75 hover:text-n-1 disabled:hover:text-n-3/75'
                  )}
                >
                  <span
                    className={cn('ml-1 h-3.5 w-3.5 rounded', INDUSTRY_COLOR[i.id] ?? 'bg-n-4')}
                    aria-hidden="true"
                  />
                  <span className="ml-1 flex-1 text-left">{i.label}</span>
                  <span
                    className={cn(
                      'rounded-md px-2 py-0.5 font-display text-xs font-semibold text-n-4d',
                      active ? 'bg-n-7' : 'bg-n-6'
                    )}
                    title={`${i.filers} US public companies in the peer set`}
                  >
                    {i.filers}
                    <span className="sr-only"> public companies</span>
                  </span>
                </button>
              )
            })}
          </div>
        )}
      </div>

      <div className="-mx-4 my-4 h-px bg-n-6" />

      {/* Saved diagnostics. Takes the free height and scrolls inside it. */}
      <section className="flex min-h-[9rem] flex-1 flex-col" aria-labelledby="history-title">
        <button
          type="button"
          onClick={() => setHistoryOpen((o) => !o)}
          aria-expanded={historyOpen}
          className="flex h-12 w-full shrink-0 items-center gap-3 px-4 font-display text-sm font-semibold text-n-4d transition-colors hover:text-n-3"
        >
          <ChevronDown
            className={cn('h-5 w-5 transition-transform', !historyOpen && '-rotate-90')}
            aria-hidden="true"
          />
          <span id="history-title">History</span>
          {p.sessions.length > 0 && (
            <span className="rounded-md bg-n-6 px-2 py-0.5 text-xs text-n-4d">
              {p.sessions.length}
            </span>
          )}
        </button>
        {historyOpen &&
          (p.sessions.length === 0 ? (
            <p className="px-4 pb-2 text-sm leading-6 text-n-4d">
              Each diagnostic you run is saved here, so you can come back to it.
            </p>
          ) : (
            <ul className="scroll-quiet min-h-0 flex-1 space-y-1 overflow-y-auto">
              {p.sessions.map((s) => (
                <HistoryItem
                  key={s.id}
                  s={s}
                  active={s.id === p.activeSessionId}
                  busy={p.busy}
                  onOpen={() => p.onOpenSession(s.id)}
                  onDelete={() => p.onDeleteSession(s.id)}
                />
              ))}
            </ul>
          ))}
      </section>

      <div className="pt-6">
        {/* The P&L being diagnosed, and the way to change it. */}
        <div className="rounded-xl bg-n-6 p-2.5 shadow-[0_1.25rem_1.5rem_0_rgba(0,0,0,0.5)]">
          <div className="flex items-center gap-3 px-2.5 py-2.5">
            <div
              className={cn(
                'flex h-10 w-10 shrink-0 items-center justify-center rounded-full',
                p.pl ? 'bg-primary-2/15 text-primary-2' : 'bg-n-5 text-n-4d'
              )}
            >
              <FileSpreadsheet className="h-5 w-5" aria-hidden="true" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate font-display text-sm font-semibold text-n-1">
                {p.pl ? `FY${p.pl.fiscal_year} P&L` : 'No P&L yet'}
              </p>
              <p className="truncate text-sm text-n-4d">
                {p.pl
                  ? `${money(p.pl.revenue, 0)} revenue`
                  : 'Upload one to begin'}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={p.onUpload}
            disabled={p.busy}
            className={cn(
              'mt-1.5 flex h-11 w-full items-center justify-center rounded-xl font-display text-sm font-semibold text-n-1 transition-colors disabled:cursor-not-allowed disabled:opacity-50',
              p.pl
                ? 'border-2 border-n-5 hover:bg-n-5'
                : 'bg-primary-1 hover:bg-primary-1/90'
            )}
          >
            {p.pl ? 'Replace P&L' : 'Upload P&L'}
          </button>
        </div>

        <div
          role="radiogroup"
          aria-label="Theme"
          className="mt-2 flex rounded-xl bg-n-6 p-1"
        >
          {(['light', 'dark'] as const).map((t) => {
            const active = p.theme === t
            const Icon = t === 'light' ? Sun : Moon
            return (
              <button
                key={t}
                type="button"
                role="radio"
                aria-checked={active}
                onClick={() => p.onTheme(t)}
                className={cn(
                  'flex h-10 flex-1 items-center justify-center gap-2 rounded-[0.625rem] font-display text-sm font-semibold capitalize transition-colors',
                  active ? 'bg-n-7 text-n-1 shadow-pill' : 'text-n-4d hover:text-n-1'
                )}
              >
                <Icon className="h-5 w-5" aria-hidden="true" />
                {t}
              </button>
            )
          })}
        </div>
      </div>
    </nav>
  )
}
