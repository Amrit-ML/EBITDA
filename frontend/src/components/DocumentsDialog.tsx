import { useEffect, useRef, useState } from 'react'
import { FileText, Loader2, Plus, Trash2 } from 'lucide-react'
import { deleteDocument, getDocuments, uploadDocument, type OrgDocument } from '../api'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'

export function DocumentsDialog({
  companyId,
  open,
  onOpenChange,
  onCountChange,
}: {
  companyId: string
  open: boolean
  onOpenChange: (open: boolean) => void
  onCountChange?: (count: number) => void
}) {
  const [docs, setDocs] = useState<OrgDocument[]>([])
  const [accepted, setAccepted] = useState<string[]>([])
  const [configured, setConfigured] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  async function refresh() {
    try {
      const d = await getDocuments(companyId)
      setDocs(d.results)
      setAccepted(d.accepted)
      setConfigured(d.configured)
      onCountChange?.(d.results.length)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  useEffect(() => {
    if (open) {
      setError(null)
      refresh()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, companyId])

  async function onPick(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? [])
    e.target.value = ''
    if (!files.length) return
    setBusy(true)
    setError(null)
    for (const f of files) {
      try {
        await uploadDocument(companyId, f)
      } catch (err) {
        setError(`${f.name}: ${(err as Error).message}`)
        break
      }
    }
    await refresh()
    setBusy(false)
  }

  async function onDelete(id: string) {
    setBusy(true)
    try {
      await deleteDocument(companyId, id)
      await refresh()
    } catch (e) {
      setError((e as Error).message)
    }
    setBusy(false)
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !busy && onOpenChange(o)}>
      <DialogContent>
        <DialogTitle>Company documents</DialogTitle>
        <DialogDescription>
          Org charts, contracts, leases and policies. The agent reads these for facts a P&amp;L
          cannot show, so it asks you fewer questions.
        </DialogDescription>

        {!configured ? (
          <p className="mt-6 rounded-xl bg-n-2 px-4 py-3 text-sm leading-6 dark:bg-n-7">
            Document search is switched off. Add the Pinecone key to backend/.env and restart the
            server.
          </p>
        ) : (
          <>
            <input
              ref={fileRef}
              type="file"
              multiple
              accept={accepted.join(',')}
              onChange={onPick}
              className="hidden"
            />
            <button
              type="button"
              disabled={busy}
              onClick={() => fileRef.current?.click()}
              className="mt-6 flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-primary-1 font-display text-base font-semibold text-n-1 transition hover:bg-primary-1/90 enabled:active:scale-[0.98] disabled:cursor-wait disabled:opacity-70"
            >
              {busy ? (
                <Loader2 className="h-5 w-5 motion-safe:animate-spin" aria-hidden="true" />
              ) : (
                <Plus className="h-5 w-5" strokeWidth={2.5} aria-hidden="true" />
              )}
              {busy ? 'Reading documents…' : 'Add documents'}
            </button>
            {accepted.length > 0 && (
              <p className="mt-2 text-center font-display text-xs text-n-4 dark:text-n-4d">
                {accepted.join('  ')}
              </p>
            )}

            {error && (
              <p
                role="alert"
                className="mt-4 rounded-xl bg-accent-1/10 px-4 py-3 text-sm leading-6 text-[#B23C08] dark:text-[#F08A5D]"
              >
                {error}
              </p>
            )}

            {docs.length === 0 ? (
              <p className="mt-6 text-center text-sm leading-6 text-n-4 dark:text-n-4d">
                No documents yet. Without them the agent works from your P&amp;L and the peer
                comparison alone.
              </p>
            ) : (
              <ul className="scroll-quiet -mx-2 mt-6 max-h-72 space-y-1 overflow-y-auto">
                {docs.map((d) => (
                  <li
                    key={d.id}
                    className="flex items-center gap-3 rounded-xl p-2 transition-colors duration-300 animate-in fade-in-0 slide-in-from-bottom-1 hover:bg-n-2 dark:hover:bg-n-7"
                  >
                    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-accent-1/10 text-accent-1">
                      <FileText className="h-5 w-5" aria-hidden="true" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-display text-sm font-semibold">
                        {d.filename}
                      </span>
                      <span className="block text-xs text-n-4 dark:text-n-4d">
                        {d.chunks} passage{d.chunks === 1 ? '' : 's'} read
                      </span>
                    </span>
                    <button
                      type="button"
                      onClick={() => onDelete(d.id)}
                      disabled={busy}
                      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-n-4 transition-colors hover:bg-accent-1/10 hover:text-accent-1 disabled:opacity-40 dark:text-n-4d"
                      aria-label={`Remove ${d.filename}`}
                      title="Remove"
                    >
                      <Trash2 className="h-4 w-4" aria-hidden="true" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}
