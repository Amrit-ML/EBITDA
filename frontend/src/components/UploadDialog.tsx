import { useState } from 'react'
import { Loader2, Upload } from 'lucide-react'
import { createCompanyFromUpload, uploadPreview, type TrendAnalysis } from '../api'
import type { CompanySummary } from '../types'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { cn } from '@/lib/utils'

const ACCEPT = '.csv,.tsv,.txt,.xlsx,.xlsm,.xls,.ods,.pdf,.pptx'

export function UploadDialog({
  industryId,
  industryLabel,
  carryContextFrom,
  onClose,
  onCreated,
}: {
  industryId: string
  industryLabel: string
  carryContextFrom: string | null
  onClose: () => void
  onCreated: (c: CompanySummary, trend: TrendAnalysis | null) => void
}) {
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)

  async function handleFile(file: File) {
    setBusy(true)
    setError(null)
    try {
      setStatus('Reading your P&L…')
      const p = await uploadPreview(file)
      if (!p.suggested_mapping.revenue) {
        throw new Error(
          'No revenue line was found in this file, so it cannot be compared. Try a clearer export with a line named Revenue or Net sales.'
        )
      }
      setStatus('Comparing with peer companies…')
      const mapping = Object.fromEntries(
        p.fields.map((f) => [f.key, p.suggested_mapping[f.key]?.label ?? null])
      )
      const period = p.default_period ?? p.periods[0]?.key ?? ''
      const fiscalYear =
        p.periods.find((x) => x.key === period)?.year ?? new Date().getFullYear()
      const units = p.detected_units ?? 'dollars'
      const res = await createCompanyFromUpload({
        upload_id: p.upload_id,
        carry_context_from: carryContextFrom,
        mapping,
        period,
        units,
        industry: industryId,
        fiscal_year: fiscalYear,
      })
      // The server works out the trend when the file has several periods and
      // keeps it with the P&L, so a reopened diagnostic still has its chart.
      onCreated(res.company, res.trend)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
      setStatus('')
    }
  }

  // Escape, the backdrop and the close button all arrive here; closing is
  // refused while a file is being read.
  return (
    <Dialog open onOpenChange={(o) => !o && !busy && onClose()}>
      <DialogContent>
        <DialogTitle>Upload your P&amp;L</DialogTitle>
        <DialogDescription>
          Compared with {industryLabel.toLowerCase()} companies. The file is read in memory and
          never saved.
        </DialogDescription>

        <label
          onDragOver={(e) => {
            e.preventDefault()
            if (!busy) setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragging(false)
            const f = e.dataTransfer.files?.[0]
            if (f && !busy) handleFile(f)
          }}
          className={cn(
            'mt-6 flex flex-col items-center rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors has-[:focus-visible]:border-primary-1',
            dragging ? 'border-primary-1 bg-primary-1/5' : 'border-n-3 dark:border-n-5',
            busy ? 'cursor-wait' : 'cursor-pointer hover:border-primary-1/60'
          )}
        >
          <input
            type="file"
            className="sr-only"
            accept={ACCEPT}
            disabled={busy}
            onChange={(e) => {
              const f = e.target.files?.[0]
              e.target.value = ''
              if (f) handleFile(f)
            }}
          />
          <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-accent-2/15 text-accent-2">
            {busy ? (
              <Loader2 className="h-6 w-6 motion-safe:animate-spin" aria-hidden="true" />
            ) : (
              <Upload className="h-6 w-6" aria-hidden="true" />
            )}
          </span>
          <span className="mt-4 font-display text-base font-semibold" aria-live="polite">
            {busy ? status : 'Choose a file, or drop it here'}
          </span>
          <span className="mt-1 text-sm leading-6 text-n-4 dark:text-n-4d">
            CSV, Excel, PDF or PowerPoint. Line items can run down rows or across columns.
          </span>
        </label>

        {error && (
          <p
            role="alert"
            className="mt-4 rounded-xl bg-accent-1/10 px-4 py-3 text-sm leading-6 text-[#B23C08] dark:text-[#F08A5D]"
          >
            {error}
          </p>
        )}
      </DialogContent>
    </Dialog>
  )
}
