import { useState } from 'react'
import { AlertTriangle, CheckCircle2, UserRound } from 'lucide-react'
import type { ChatMessage } from '../types'
import { cn } from '@/lib/utils'
import { AgentTile } from './Logo'

const clock = (at?: number) =>
  at
    ? new Date(at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
    : ''

// How a new message arrives: rising a little into place.
const rise = 'animate-in fade-in-0 slide-in-from-bottom-3 duration-300 ease-out'

const chip =
  'rounded-md bg-n-3/75 px-2 py-1 font-display text-xs font-semibold text-n-7 dark:bg-n-7 dark:text-n-1'

const BULLET = /^[-•]\s+/

/** Consecutive lines of one kind: prose, or "- " bullets. */
interface Run {
  list: boolean
  lines: string[]
}

/** Blocks are split on blank lines, then each block into runs, so a lead-in
 *  such as "The biggest gaps are:" directly above its bullets still gets the
 *  figures card rather than raw dashes. */
function runs(text: string): Run[] {
  const out: Run[] = []
  for (const block of text.trim().split(/\n\s*\n/)) {
    let current: Run | null = null
    for (const raw of block.split('\n')) {
      const line = raw.trim()
      if (!line) continue
      const list = BULLET.test(line)
      if (current && current.list === list) current.lines.push(line)
      else out.push((current = { list, lines: [line] }))
    }
  }
  return out
}

/** A reply in the shape the agent is asked to write: the point, the figures
 *  as short lines, what to do, then the question alone. */
function Reply({ text }: { text: string }) {
  const parts = runs(text)
  return (
    <div className="space-y-4">
      {parts.map((r, i) => {
        if (r.list) {
          return (
            <ul
              key={i}
              className="divide-y divide-n-3 rounded-xl bg-n-1 px-4 dark:divide-n-5 dark:bg-n-6"
            >
              {r.lines.map((l, j) => (
                <li key={j} className="py-3 text-[0.9375rem] leading-6">
                  {l.replace(BULLET, '')}
                </li>
              ))}
            </ul>
          )
        }
        const prose = r.lines.join('\n')
        const isQuestion = i === parts.length - 1 && /\?\s*$/.test(prose)
        return (
          <p key={i} className={cn('whitespace-pre-wrap', isQuestion && 'font-semibold')}>
            {prose}
          </p>
        )
      })}
    </div>
  )
}

function Verified({ m }: { m: ChatMessage }) {
  if (!m.guard) return null
  const bad = m.guard.unverified_figures
  return bad.length === 0 ? (
    <span
      className="inline-flex items-center gap-1 rounded-md bg-primary-2/15 px-2 py-1 font-display text-xs font-semibold text-[#178A43] dark:text-primary-2"
      title="Every dollar figure in this reply matches a number calculated from your P&L"
    >
      <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
      Figures checked
    </span>
  ) : (
    <span
      className="inline-flex items-center gap-1 rounded-md bg-accent-5/15 px-2 py-1 font-display text-xs font-semibold text-[#8A5F00] dark:text-accent-5"
      title="These figures did not match any number calculated from your P&L"
    >
      <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />
      Not verified: {bad.join(', ')}
    </span>
  )
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      type="button"
      className={chip}
      onClick={() => {
        navigator.clipboard?.writeText(text).then(
          () => {
            setCopied(true)
            setTimeout(() => setCopied(false), 1500)
          },
          () => {}
        )
      }}
    >
      {copied ? 'Copied' : 'Copy'}
    </button>
  )
}

function AgentMessage({ m, enter }: { m: ChatMessage; enter: boolean }) {
  // Decided once, on arrival: toggling the class later would replay it.
  const [animate] = useState(enter)
  return (
    <article aria-label="Agent" className={cn(animate && rise)}>
      <div className="rounded-2.5xl bg-n-2 px-5 pb-10 pt-5 text-base leading-7 lg:px-6 lg:pt-6 dark:bg-n-7">
        <Reply text={m.content} />
      </div>
      <div className="-mt-6 flex items-end gap-3 pl-5 lg:pl-6">
        <AgentTile />
        <div className="ml-auto flex flex-wrap items-center justify-end gap-2 duration-500 animate-in fade-in-0">
          <span className="font-display text-xs text-n-4 dark:text-n-4d">{clock(m.at)}</span>
          <Verified m={m} />
          <CopyButton text={m.content} />
        </div>
      </div>
    </article>
  )
}

function UserMessage({ m }: { m: ChatMessage }) {
  return (
    <article aria-label="You" className={rise}>
      <div className="rounded-2.5xl border-2 border-n-2 bg-n-1 px-5 pb-10 pt-5 text-base leading-7 lg:px-6 lg:pt-6 dark:border-transparent dark:bg-n-5/50">
        <p className="whitespace-pre-wrap">{m.content}</p>
      </div>
      {/* The time sits beside the avatar, mirroring the agent's row. */}
      <div className="-mt-6 flex items-end justify-end gap-3 pr-5 lg:pr-6">
        <span className="font-display text-xs text-n-4 dark:text-n-4d">{clock(m.at)}</span>
        <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-n-3 text-n-4 dark:bg-n-5 dark:text-n-4d">
          <UserRound className="h-6 w-6" aria-hidden="true" />
        </div>
      </div>
    </article>
  )
}

interface Props {
  messages: ChatMessage[]
  busy: boolean
  busyLabel: string
  partial: string
}

export function Conversation({ messages, busy, busyLabel, partial }: Props) {
  // A reply that streamed in is already on screen when it lands, so it takes
  // no entrance; one that arrives whole (or a reopened history) rises in.
  // Whether text was streaming is read off the render before the one that
  // adds the message, kept in state as React's "previous value" pattern.
  const [seen, setSeen] = useState({ partial, count: messages.length, streamedIn: false })
  if (seen.partial !== partial || seen.count !== messages.length) {
    setSeen({ partial, count: messages.length, streamedIn: seen.partial !== '' })
  }
  const streamedIn = seen.streamedIn

  return (
    <div className="space-y-10">
      {messages.map((m, i) =>
        m.role === 'assistant' ? (
          <AgentMessage key={i} m={m} enter={!streamedIn} />
        ) : (
          <UserMessage key={i} m={m} />
        )
      )}

      {busy && (
        <article aria-label="Agent" aria-busy="true" className={rise}>
          <div className="rounded-2.5xl bg-n-2 px-5 pb-10 pt-5 text-base leading-7 lg:px-6 lg:pt-6 dark:bg-n-7">
            {partial ? (
              <Reply text={partial} />
            ) : (
              <div role="status" className="flex items-center gap-3 text-n-4 dark:text-n-4d">
                <span className="flex gap-1" aria-hidden="true">
                  {[0, 1, 2].map((d) => (
                    <span
                      key={d}
                      className="h-2 w-2 animate-dot-pulse rounded-full bg-primary-1"
                      style={{ animationDelay: `${d * 0.16}s` }}
                    />
                  ))}
                </span>
                {busyLabel}
              </div>
            )}
          </div>
          <div className="-mt-6 pl-5 lg:pl-6">
            <AgentTile />
          </div>
        </article>
      )}
    </div>
  )
}
