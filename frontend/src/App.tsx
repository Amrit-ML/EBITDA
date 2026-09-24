import { useEffect, useRef, useState } from 'react'
import { AlertTriangle, ListChecks, Menu, Plus } from 'lucide-react'
import { deleteSession, getDocuments, getIndustries,
         getSavedSession, listSessions, sendMessageStream, startSessionStream,
         type SessionSummary } from './api'
import type { AgentTurn, ChatMessage, CompanySummary, Finding, Industry } from './types'
import { useTheme } from '@/lib/theme'
import { cn } from '@/lib/utils'
import { Sidebar, type View } from './components/Sidebar'
import { InsightsView } from './components/InsightsView'
import { Welcome } from './components/Welcome'
import { Conversation } from './components/Conversation'
import { Composer } from './components/Composer'
import { OpportunitiesDialog } from './components/OpportunitiesDialog'
import { UploadDialog } from './components/UploadDialog'
import { DocumentsDialog } from './components/DocumentsDialog'
import { OnPointMark } from './components/Logo'

export default function App() {
  const [theme, setTheme] = useTheme()
  const [industries, setIndustries] = useState<Industry[]>([])
  const [industryId, setIndustryId] = useState('')

  // The P&L being diagnosed, and what its upload told us.
  const [pl, setPl] = useState<CompanySummary | null>(null)
  const [docCounts, setDocCounts] = useState<Record<string, number>>({})

  const [sessionId, setSessionId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  // Opportunities the agent has recorded: actions and reasons, never savings.
  const [findings, setFindings] = useState<Finding[]>([])
  // Saved diagnostics, newest first (chat_history/ on the server).
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  // Which page the centre shows: the conversation or the Insights ratios.
  const [view, setView] = useState<View>('diagnostic')

  const [busy, setBusy] = useState(false)
  const [busyLabel, setBusyLabel] = useState('')
  const [partial, setPartial] = useState('')
  const [error, setError] = useState<string | null>(null)

  const [uploadOpen, setUploadOpen] = useState(false)
  const [docsOpen, setDocsOpen] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const [oppsOpen, setOppsOpen] = useState(false)

  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    getIndustries()
      .then((ind) => {
        setIndustries(ind)
        setIndustryId((cur) => cur || ind[0]?.id || '')
      })
      .catch((e: Error) => setError(e.message))
    refreshSessions()
  }, [])

  const plId = pl?.id ?? null

  useEffect(() => {
    if (!plId) return
    let live = true
    getDocuments(plId)
      .then((d) => live && setDocCounts((prev) => ({ ...prev, [plId]: d.results.length })))
      .catch(() => {
        // The count is a convenience; a search outage must not surface here.
      })
    return () => {
      live = false
    }
  }, [plId])

  // Follow the conversation: jump on each new message, and keep pace with a
  // streaming reply only while the reader is already near the bottom.
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    el.scrollTo({ top: el.scrollHeight, behavior: reduce ? 'auto' : 'smooth' })
  }, [messages.length, busy])

  useEffect(() => {
    const el = scrollRef.current
    if (el && el.scrollHeight - el.scrollTop - el.clientHeight < 160) {
      el.scrollTop = el.scrollHeight
    }
  }, [partial])

  useEffect(() => {
    if (!menuOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMenuOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [menuOpen])

  function refreshSessions() {
    listSessions()
      .then(setSessions)
      .catch(() => {
        // The list is a convenience; the current diagnostic works without it.
      })
  }

  // The agent's figures were computed against one P&L and one peer set, so
  // changing either starts the conversation over. This is done here, on the
  // user's action, rather than by watching the values: reopening a saved
  // diagnostic changes both, and must not wipe what it just loaded.
  function changeIndustry(id: string) {
    if (id === industryId) return
    setIndustryId(id)
    resetSession()
  }

  async function openSession(id: string) {
    setMenuOpen(false)
    setView('diagnostic')
    if (busy || id === sessionId) return
    try {
      const s = await getSavedSession(id)
      setPl(s.company)
      setIndustryId(s.industry)
      setSessionId(s.session_id)
      setMessages(
        s.messages.map((m) => ({
          role: m.role,
          content: m.content,
          guard: m.guard,
          at: m.at * 1000,
        }))
      )
      setFindings(s.findings)
      setPartial('')
      setError(null)
    } catch (e) {
      setError((e as Error).message)
      refreshSessions()
    }
  }

  async function removeSession(id: string) {
    try {
      await deleteSession(id)
      if (id === sessionId) resetSession()
    } catch (e) {
      setError((e as Error).message)
    }
    refreshSessions()
  }

  function resetSession() {
    setSessionId(null)
    setMessages([])
    setFindings([])
    setError(null)
  }

  function absorb(turn: AgentTurn) {
    setMessages((m) => [
      ...m,
      {
        role: 'assistant',
        content: turn.message,
        guard: turn.guard,
        trace: turn.trace,
        cost: turn.turn_cost_usd,
        at: Date.now(),
      },
    ])
    setFindings(turn.findings)
  }

  // Status drives the waiting label, deltas append to the live reply, and a
  // reset clears it when a later model call replaces what was streamed.
  const streamHandlers = {
    onStatus: (t: string) => setBusyLabel(t),
    onDelta: (t: string) => setPartial((prev) => prev + t),
    onReset: () => setPartial(''),
  }

  async function begin() {
    if (!pl || !industryId) return
    resetSession()
    setView('diagnostic')
    setBusy(true)
    setBusyLabel('Comparing your costs with peer companies…')
    setPartial('')
    try {
      const turn = await startSessionStream(pl.id, industryId, streamHandlers)
      setSessionId(turn.session_id)
      absorb(turn)
      refreshSessions()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setPartial('')
      setBusy(false)
    }
  }

  async function send(text: string) {
    if (!sessionId) return
    setMessages((m) => [...m, { role: 'user', content: text, at: Date.now() }])
    setBusy(true)
    setBusyLabel('Working through the numbers…')
    setError(null)
    setPartial('')
    try {
      absorb(await sendMessageStream(sessionId, text, streamHandlers))
      refreshSessions()
    } catch (e) {
      // The backend rolled the turn back; take the message back out too.
      setMessages((m) => m.slice(0, -1))
      setError((e as Error).message)
    } finally {
      setPartial('')
      setBusy(false)
    }
  }

  const industryLabel = industries.find((i) => i.id === industryId)?.label ?? ''
  const docCount = plId ? docCounts[plId] ?? 0 : 0
  const inConversation = messages.length > 0 || busy
  const onInsights = view === 'insights' && !!pl
  const canStart = !!pl && !!industryId

  const openUpload = () => {
    setMenuOpen(false)
    setUploadOpen(true)
  }
  const openDocs = () => {
    setMenuOpen(false)
    setDocsOpen(true)
  }

  const sidebarProps = {
    industries,
    industryId,
    onIndustry: changeIndustry,
    pl,
    docCount,
    busy,
    onUpload: openUpload,
    onDocs: openDocs,
    theme,
    onTheme: setTheme,
    sessions,
    activeSessionId: sessionId,
    onOpenSession: openSession,
    onDeleteSession: removeSession,
    view,
    onView: (v: View) => {
      setMenuOpen(false)
      setView(v)
    },
  }

  const menuButton = (
    <button
      type="button"
      onClick={() => setMenuOpen(true)}
      className="-ml-2 flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-n-4 hover:text-n-7 lg:hidden dark:text-n-4d dark:hover:text-n-1"
      aria-label="Open menu"
    >
      <Menu className="h-6 w-6" />
    </button>
  )

  // Header actions for a diagnostic under way. On a phone they shrink to
  // icons; their names are still spoken.
  const headerButton =
    'flex h-10 shrink-0 items-center gap-2 rounded-xl border-2 border-n-3 px-3 font-display text-sm font-semibold transition hover:border-n-4/40 enabled:active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-50 sm:px-3.5 dark:border-n-5 dark:hover:border-n-4'
  const diagnosticActions = sessionId && (
    <div className="ml-auto flex shrink-0 items-center gap-2">
      <button type="button" onClick={() => setOppsOpen(true)} className={headerButton}>
        <ListChecks className="h-4 w-4" aria-hidden="true" />
        <span className="sr-only sm:not-sr-only">Opportunities</span>
        {findings.length > 0 && (
          <span
            key={findings.length}
            className="rounded-md bg-primary-2/15 px-1.5 text-xs tabular-nums text-[#178A43] duration-300 animate-in fade-in-0 zoom-in-75 dark:text-primary-2"
          >
            {findings.length}
          </span>
        )}
      </button>
      <button
        type="button"
        onClick={begin}
        disabled={busy || !canStart}
        className={headerButton}
        title="Start again with the same P&L; this one stays in History"
      >
        <Plus className="h-4 w-4" strokeWidth={2.5} aria-hidden="true" />
        <span className="sr-only sm:not-sr-only">New diagnostic</span>
      </button>
    </div>
  )

  return (
    <div className="flex h-full bg-n-7 text-n-7 dark:text-n-1">
      <aside className="hidden w-72 shrink-0 lg:block xl:w-80">
        <Sidebar {...sidebarProps} />
      </aside>

      <div className="flex min-w-0 flex-1 lg:py-4 lg:pr-4 xl:py-6 xl:pr-6">
        <div className="flex min-w-0 flex-1 overflow-hidden bg-n-1 lg:rounded-2.5xl dark:bg-n-6">
          <main className="flex min-w-0 flex-1 flex-col">
            {inConversation || onInsights ? (
              <header className="flex h-[4.5rem] shrink-0 items-center gap-3 border-b border-n-3 px-5 lg:px-10 dark:border-n-5">
                {menuButton}
                <h1 className="min-w-0 truncate font-display text-lg font-bold tracking-tight lg:text-2xl">
                  {onInsights ? 'Insights' : 'EBITDA diagnostic'}
                </h1>
                {industryLabel && (
                  <span className="hidden shrink-0 rounded-md bg-n-2 px-2 py-1 font-display text-xs font-semibold text-n-4 md:inline dark:bg-n-7 dark:text-n-4d">
                    vs {industryLabel.toLowerCase()} industry
                  </span>
                )}
                {!onInsights && diagnosticActions}
              </header>
            ) : (
              // Below lg the sidebar, and with it the wordmark, is hidden.
              <div className="flex h-16 shrink-0 items-center gap-3 px-5 lg:hidden">
                {menuButton}
                <span className="flex min-w-0 items-center gap-2">
                  <OnPointMark className="h-6 w-6 shrink-0 text-primary-1 dark:text-primary-1d" />
                  <span className="truncate font-display text-base font-bold tracking-tight">
                    EBITDA Engine
                  </span>
                </span>
              </div>
            )}

            {error && (
              <div
                role="alert"
                className="mx-5 mt-4 flex items-start gap-3 rounded-xl bg-accent-1/10 px-4 py-3 duration-300 animate-in fade-in-0 slide-in-from-top-2 lg:mx-10"
              >
                <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-accent-1" aria-hidden="true" />
                <p className="min-w-0 flex-1 text-sm leading-6 text-[#B23C08] dark:text-[#F08A5D]">
                  {error}
                </p>
                <button
                  type="button"
                  onClick={() => setError(null)}
                  className="shrink-0 font-display text-sm font-semibold text-n-7 hover:underline dark:text-n-1"
                >
                  Dismiss
                </button>
              </div>
            )}

            <div ref={scrollRef} data-scroll-pane className="scroll-quiet min-h-0 flex-1 overflow-y-auto">
              {/* Insights is a dashboard, so it gets the width; a conversation
                  keeps a readable measure. */}
              <div
                className={cn(
                  'mx-auto px-5 py-8 lg:px-10 lg:py-10',
                  onInsights ? 'max-w-[72rem]' : 'max-w-[50rem]'
                )}
              >
                {onInsights ? (
                  <InsightsView
                    companyId={pl!.id}
                    industry={industryId}
                    industryLabel={industryLabel}
                    onUpload={openUpload}
                  />
                ) : inConversation ? (
                  <Conversation
                    messages={messages}
                    busy={busy}
                    busyLabel={busyLabel}
                    partial={partial}
                  />
                ) : (
                  <Welcome
                    pl={pl}
                    industryLabel={industryLabel}
                    docCount={docCount}
                    busy={busy}
                    onUpload={openUpload}
                    onDocs={openDocs}
                    onStart={begin}
                  />
                )}
              </div>
            </div>

            {/* Before a conversation there is nothing to reply to; the steps
                above are the only way in. */}
            {inConversation && !onInsights && (
              <div className="shrink-0 px-5 pb-5 lg:px-10 lg:pb-6">
                <div className="mx-auto max-w-[50rem]">
                  <Composer
                    enabled={!!sessionId}
                    busy={busy}
                    canAttach={!!pl && !busy}
                    placeholder={sessionId ? 'Reply to the agent' : 'The agent is replying…'}
                    onSend={send}
                    onAttach={openDocs}
                  />
                </div>
              </div>
            )}
          </main>
        </div>
      </div>

      {/* Small screens: the sidebar slides in over the page. */}
      {menuOpen && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Menu">
          <div className="absolute inset-0 bg-n-7/60 animate-in fade-in-0" onClick={() => setMenuOpen(false)} />
          <div className="absolute inset-y-0 left-0 w-[18.75rem] max-w-[85vw] shadow-lift animate-in slide-in-from-left">
            <Sidebar {...sidebarProps} onClose={() => setMenuOpen(false)} />
          </div>
        </div>
      )}
      <OpportunitiesDialog
        open={oppsOpen}
        onOpenChange={setOppsOpen}
        findings={findings}
        pl={pl}
        industryLabel={industryLabel}
      />

      {uploadOpen && (
        <UploadDialog
          industryId={industryId}
          industryLabel={industryLabel}
          carryContextFrom={plId}
          onClose={() => setUploadOpen(false)}
          onCreated={(c) => {
            setUploadOpen(false)
            setPl(c)
            resetSession()
          }}
        />
      )}

      {pl && (
        <DocumentsDialog
          companyId={pl.id}
          open={docsOpen}
          onOpenChange={setDocsOpen}
          onCountChange={(n) => setDocCounts((prev) => ({ ...prev, [pl.id]: n }))}
        />
      )}
    </div>
  )
}
