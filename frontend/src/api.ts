import type {
  AgentTurn,
  Briefing,
  CompanySummary,
  Comparison,
  Finding,
  FindingsTotals,
  Industry,
  IndustryProfile,
  Units,
  UploadPreview,
} from './types'

const BASE = '/api'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, init)
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (typeof body.detail === 'string') message = body.detail
      else if (Array.isArray(body.detail)) {
        message = body.detail
          .map((d: { loc?: string[]; msg?: string }) =>
            `${(d.loc ?? []).slice(1).join('.')} ${d.msg ?? ''}`.trim())
          .join('; ')
      }
    } catch {
      // No JSON body; keep the status line.
    }
    throw new Error(message)
  }
  return res.json() as Promise<T>
}

const post = <T>(path: string, body: unknown) =>
  request<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

export const getCompanies = () =>
  request<{ results: CompanySummary[] }>('/companies').then((r) => r.results)

export const getIndustries = () =>
  request<{ results: Industry[] }>('/industries').then((r) => r.results)

export const getIndustryProfile = (industry: string, band: string | null) =>
  request<IndustryProfile>(
    `/industries/${encodeURIComponent(industry)}/profile${band ? `?band=${encodeURIComponent(band)}` : ''}`)

/** Benchmark a P&L against the industry the user selected. */
export const getBenchmark = (id: string, industry: string) =>
  request<Comparison>(
    `/companies/${encodeURIComponent(id)}/benchmark?industry=${encodeURIComponent(industry)}`)

export const getBriefing = (id: string) =>
  request<Briefing>(`/companies/${encodeURIComponent(id)}/briefing`)

export const startSession = (companyId: string, industry: string) =>
  post<AgentTurn>('/sessions', { company_id: companyId, industry })

export const sendMessage = (sessionId: string, text: string) =>
  post<AgentTurn>(`/sessions/${sessionId}/messages`, { text })

export interface StreamHandlers {
  onStatus?: (text: string) => void
  /** Append streamed prose. */
  onDelta?: (text: string) => void
  /** Discard what was streamed - a later model call replaced it. */
  onReset?: () => void
}

/** Consume one agent turn as server-sent events, resolving with the final turn.
 *
 * EventSource is not used because these are POSTs with a JSON body, which it
 * cannot send; fetch + a reader over the same `data:` framing does the job.
 */
async function consumeStream(
  path: string,
  body: unknown,
  h: StreamHandlers,
): Promise<AgentTurn> {
  const res = await fetch(BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok || !res.body) {
    throw new Error(`${res.status} ${res.statusText}`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  let done: AgentTurn | null = null
  let failure: string | null = null

  for (;;) {
    const { value, done: finished } = await reader.read()
    if (finished) break
    buf += decoder.decode(value, { stream: true })
    // Frames are separated by a blank line; a partial tail stays buffered.
    const frames = buf.split('\n\n')
    buf = frames.pop() ?? ''
    for (const frame of frames) {
      const line = frame.split('\n').find((l) => l.startsWith('data: '))
      if (!line) continue
      const ev = JSON.parse(line.slice(6))
      if (ev.type === 'status') h.onStatus?.(ev.text)
      else if (ev.type === 'delta') h.onDelta?.(ev.text)
      else if (ev.type === 'reset') h.onReset?.()
      else if (ev.type === 'done') done = ev.payload as AgentTurn
      else if (ev.type === 'error') failure = ev.text
    }
  }

  if (failure) throw new Error(failure)
  if (!done) throw new Error('The diagnostic ended before it finished replying.')
  return done
}

export const startSessionStream = (
  companyId: string, industry: string, h: StreamHandlers,
) => consumeStream('/sessions/stream', { company_id: companyId, industry }, h)

export const sendMessageStream = (
  sessionId: string, text: string, h: StreamHandlers,
) => consumeStream(`/sessions/${sessionId}/messages/stream`, { text }, h)

export const uploadPreview = (file: File, sheet?: string) => {
  const form = new FormData()
  form.append('file', file)
  if (sheet) form.append('sheet', sheet)
  return request<UploadPreview>('/uploads', { method: 'POST', body: form })
}

export interface CreateCompanyBody {
  upload_id: string
  carry_context_from?: string | null
  mapping: Record<string, string | null>
  period: string
  units: Units
  industry: string
  fiscal_year: number
}

export const createCompanyFromUpload = (body: CreateCompanyBody) =>
  post<{
    company: CompanySummary
    financials: Record<string, number>
    missing_labels: string[]
    documents_carried: number
    /** Null for a single-period file: one period has nothing to average. */
    trend: TrendAnalysis | null
  }>('/uploads/company', body)

export interface TrendAnalysis {
  periods: string[]
  ebitda: number[]
  revenue: (number | null)[]
  current_period: string
  current_ebitda: number
  historical_average: number
  series_average: number
  variance_pct: number | null
  variance_usd: number
  commentary: string
  drivers: {
    field: string
    label: string
    change_usd: number
    contribution_usd: number
  }[]
}

export const getUploadTrend = (
  uploadId: string,
  mapping: Record<string, string | null>,
  units: Units,
) => post<TrendAnalysis>('/uploads/trend', {
  upload_id: uploadId, mapping, units,
})

export interface EbitdaHistory {
  periods: string[]
  ebitda: number[]
  count: number
  current_period: string | null
  current_ebitda: number | null
  historical_average: number | null
  variance_pct: number | null
  variance_usd: number | null
  status: 'no data' | 'baseline' | 'ahead' | 'behind' | 'in line' | 'flat'
  message: string
}

export const getEbitdaHistory = (companyId: string) =>
  request<EbitdaHistory>(
    `/companies/${encodeURIComponent(companyId)}/ebitda-history`)

export const addCompanyPeriods = (
  companyId: string,
  uploadId: string,
  mapping: Record<string, string | null>,
  units: Units,
) => post<EbitdaHistory>(
  `/companies/${encodeURIComponent(companyId)}/periods`,
  { upload_id: uploadId, mapping, units })

export interface OrgDocument {
  id: string
  filename: string
  chunks: number
  chars: number
  uploaded_at: number
}

export const getDocuments = (companyId: string) =>
  request<{ configured: boolean; accepted: string[]; results: OrgDocument[] }>(
    `/companies/${encodeURIComponent(companyId)}/documents`)

export const uploadDocument = (companyId: string, file: File) => {
  const form = new FormData()
  form.append('file', file)
  return request<OrgDocument>(
    `/companies/${encodeURIComponent(companyId)}/documents`,
    { method: 'POST', body: form })
}

export const deleteDocument = (companyId: string, docId: string) =>
  request<{ deleted: string }>(
    `/companies/${encodeURIComponent(companyId)}/documents/${docId}`,
    { method: 'DELETE' })

// --- saved diagnostics (chat history) -----------------------------------------

/** One row of the history list. Times are Unix seconds. */
export interface SessionSummary {
  id: string
  created_at: number
  updated_at: number
  company_id: string
  industry: string
  fiscal_year: number | null
  revenue: number | null
  findings_count: number
  message_count: number
  preview: string
}

/** Everything needed to reopen a diagnostic where it was left. */
export interface SavedSession {
  session_id: string
  company: CompanySummary
  industry: string
  messages: {
    role: 'user' | 'assistant'
    content: string
    guard?: AgentTurn['guard']
    /** Unix seconds. */
    at: number
  }[]
  trend: TrendAnalysis | null
  findings: Finding[]
  findings_totals: FindingsTotals
}

export const listSessions = () =>
  request<{ results: SessionSummary[] }>('/sessions').then((r) => r.results)

export const getSavedSession = (id: string) =>
  request<SavedSession>(`/sessions/${encodeURIComponent(id)}`)

export const deleteSession = (id: string) =>
  request<{ deleted: string }>(`/sessions/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  })

// --- insights ------------------------------------------------------------------

export interface InsightMetric {
  key: string
  label: string
  formula: string
  /** pct: a share, compared in points; pp: a growth gap in points; usd: dollars, compared in percent. */
  kind: 'pct' | 'pp' | 'usd'
  lower_is_better: boolean
  value: number | null
  benchmark: number
  difference: number | null
  difference_unit: 'pp' | '%'
  favourable: boolean | null
  /** Why there is no value yet, in words the user can act on. */
  missing: string | null
  /** What would fill the gap, so the card can offer it as a button. */
  action: 'add_total_fte' | 'add_sga_fte' | 'reupload' | null
}

export interface Insights {
  industry: string
  benchmarks_are_placeholder: boolean
  headcount: { total_fte: number | null; sga_fte: number | null }
  growth_basis: string | null
  metrics: InsightMetric[]
}

export const getInsights = (companyId: string, industry: string) =>
  request<Insights>(
    `/companies/${encodeURIComponent(companyId)}/insights?industry=${encodeURIComponent(industry)}`)

export const saveHeadcount = (
  companyId: string,
  industry: string,
  body: { total_fte: number; sga_fte: number | null },
) =>
  request<Insights>(
    `/companies/${encodeURIComponent(companyId)}/headcount?industry=${encodeURIComponent(industry)}`,
    { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
