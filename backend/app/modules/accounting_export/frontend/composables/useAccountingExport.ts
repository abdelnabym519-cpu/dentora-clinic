interface ApiOk<T> { data: T }

export interface ExportFilters {
  date_from?: string
  date_to?: string
  status?: string[]
}

export interface ExportPreview {
  invoice_count: number
  payment_count: number
  total_base: string
  total_cuota: string
  total: string
  sample_invoices: Record<string, unknown>[]
  sample_payments: Record<string, unknown>[]
}

function qs(filters: ExportFilters, extra: Record<string, string> = {}): string {
  const p = new URLSearchParams()
  if (filters.date_from) p.append('date_from', filters.date_from)
  if (filters.date_to) p.append('date_to', filters.date_to)
  for (const s of filters.status ?? []) p.append('status', s)
  for (const [k, v] of Object.entries(extra)) p.append(k, v)
  return p.toString()
}

export function useAccountingExport() {
  const api = useApi()
  const apiHeaders = useApiHeaders()
  const config = useRuntimeConfig()

  /**
   * The page renders failures inline (`previewError`), including the 422 a
   * bad date range produces — a status the shared layer deliberately never
   * toasts. Silencing here keeps that inline state the single report.
   */
  async function preview(filters: ExportFilters): Promise<ApiOk<ExportPreview>> {
    const s = qs(filters)
    return await api.get<ApiOk<ExportPreview>>(
      `/api/v1/accounting_export/preview${s ? `?${s}` : ''}`,
      { silent: true }
    )
  }

  // Authenticated blob download (JWT in header, so a plain <a href> won't do).
  async function download(filters: ExportFilters, separator: ',' | ';' = ';'): Promise<void> {
    const url = config.public.apiBaseUrl
      + `/api/v1/accounting_export/run?${qs(filters, { separator })}`
    const res = await fetch(url, { headers: apiHeaders() })
    if (!res.ok) {
      // Keep the server's own reason: a 403 names the missing permission and a
      // 422 explains the range. "HTTP 403" gives the user nothing to act on.
      let detail = ''
      try {
        const body = await res.json() as { detail?: unknown }
        if (typeof body?.detail === 'string') detail = body.detail
      } catch {
        // A non-JSON error body adds nothing to the status line.
      }
      throw new Error(detail || `HTTP ${res.status}`)
    }
    const blob = await res.blob()
    const blobUrl = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = blobUrl
    a.download = `gestoria_${filters.date_from ?? 'inicio'}_${filters.date_to ?? 'fin'}.zip`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(blobUrl)
  }

  return { preview, download }
}
