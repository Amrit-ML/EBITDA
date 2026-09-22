import { cn } from '@/lib/utils'

/** The OnPoint Insights mark: a ring around five dots pointing forward.
 *  Traced from the brand file at 760×800; drawn in currentColor. */
export function OnPointMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 760 800" className={className} aria-hidden="true" fill="currentColor">
      <ellipse
        cx="379.5" cy="399.5" rx="350.5" ry="369.5"
        fill="none" stroke="currentColor" strokeWidth="58"
      />
      <circle cx="301" cy="243" r="46" />
      <circle cx="406" cy="331" r="46" />
      <circle cx="519" cy="418" r="46" />
      <circle cx="402" cy="498" r="46" />
      <circle cx="282" cy="576" r="46" />
    </svg>
  )
}

/** The agent's avatar: the mark in white on a brand-blue tile. */
export function AgentTile({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        'flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-primary-1 text-n-1 shadow-tile',
        className
      )}
    >
      <OnPointMark className="h-6 w-6" />
    </div>
  )
}

export function Wordmark() {
  return (
    <div className="flex items-center gap-3">
      <OnPointMark className="h-9 w-9 shrink-0 text-primary-1d" />
      <div className="leading-none">
        <span className="block font-display text-xl font-bold tracking-tight text-n-1">
          EBITDA Engine
        </span>
        <span className="mt-1 block font-display text-xs font-medium text-n-4d">
          by OnPoint Insights
        </span>
      </div>
    </div>
  )
}
