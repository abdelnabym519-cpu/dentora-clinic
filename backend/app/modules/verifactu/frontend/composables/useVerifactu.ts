// Composable wrapping the /api/v1/verifactu/* endpoints.
//
// Returns reactive references plus action methods. Uses the shared
// `useApi` composable for auth + token refresh.
import type { ApiResponse, PaginatedResponse } from '~~/app/types'

export interface VerifactuSettings {
  id: string
  clinic_id: string
  enabled: boolean
  environment: 'test' | 'prod'
  nif_emisor: string | null
  nombre_razon_emisor: string | null
  numero_instalacion: string
  last_huella: string | null
  next_send_after: string | null
  last_aeat_response_at: string | null
  has_active_certificate: boolean
  producer_nif: string | null
  producer_name: string | null
  producer_id_sistema: string
  producer_version: string | null
  declaracion_responsable_signed_at: string | null
  declaracion_responsable_signed_by: string | null
}

export interface ProducerDefaults {
  name: string
  nif: string
  id_sistema: string
  version: string
}

export interface ProducerInfoUpdate {
  producer_nif: string
  producer_name: string
  producer_id_sistema: string
  producer_version: string
  sign_declaracion: boolean
}

export interface VerifactuCertificate {
  id: string
  clinic_id: string
  subject_cn: string | null
  issuer_cn: string | null
  nif_titular: string | null
  valid_from: string | null
  valid_until: string | null
  is_active: boolean
  uploaded_by: string | null
  created_at: string
}

export interface VerifactuRecord {
  id: string
  clinic_id: string
  invoice_id: string
  record_type: string
  tipo_factura: string
  tipo_rectificativa: string | null
  serie_numero: string
  fecha_expedicion: string
  cuota_total: string
  importe_total: string
  huella: string
  huella_anterior: string | null
  is_first_record: boolean
  state: string
  aeat_csv: string | null
  aeat_estado_envio: string | null
  aeat_estado_registro: string | null
  aeat_codigo_error: number | null
  aeat_descripcion_error: string | null
  aeat_timestamp_presentacion: string | null
  subsanacion: boolean
  submission_attempt: number
  last_attempt_at: string | null
  created_at: string
}

export interface VerifactuRecordDetail extends VerifactuRecord {
  xml_payload: string | null
  aeat_response_xml: string | null
}

export type VerifactuErrorField
  = | 'emisor'
    | 'destinatario'
    | 'linea'
    | 'cabecera'
    | 'cadena'
    | 'transporte'
    | 'sistema'
    | 'rectificativa'

export type VerifactuErrorCTA
  = | 'edit_clinic'
    | 'edit_billing_party'
    | 'edit_lines'
    | 'edit_producer'
    | 'retry'
    | 'contact_support'

export interface VerifactuQueueItem {
  id: string
  invoice_id: string
  serie_numero: string
  importe_total: string
  state: string
  aeat_codigo_error: number | null
  aeat_descripcion_error: string | null
  aeat_descripcion_error_es: string | null
  aeat_error_field: VerifactuErrorField | null
  aeat_error_cta: VerifactuErrorCTA | null
  submission_attempt: number
  last_attempt_at: string | null
}

export interface VerifactuRecordAttempt {
  id: string
  record_id: string
  attempt_no: number
  huella: string
  state: string
  aeat_codigo_error: number | null
  aeat_descripcion_error: string | null
  created_at: string
}

export interface NifCheckResult {
  is_valid: boolean
  warning: string | null
}

export interface RetryAllResult {
  regenerated: number
  failed: { record_id: string, error: string }[]
  remaining: number
}

export interface VerifactuHealth {
  enabled: boolean
  environment: string | null
  has_certificate: boolean
  certificate_valid_until: string | null
  last_aeat_response_at: string | null
  next_send_after: string | null
  pending_count: number
  rejected_count: number
}

/**
 * Per-call transport options forwarded to the shared `useApi` wrapper.
 *
 * `silent` keeps a failure inside the calling component — which renders
 * its own operation-specific error — instead of raising a global toast.
 * `operation` names the action in that toast when it is not suppressed.
 *
 * Ambient Verifactu probes (the global compliance banner, the invoice
 * panel's background record lookup, the advisory NIF check) MUST be
 * silent: they run on screens owned by other modules, so their failure
 * has to stay a Verifactu fact and never read as "this page is
 * forbidden". Explicit Verifactu actions keep the shared reporting.
 */
export interface VerifactuRequestOptions {
  silent?: boolean
  operation?: string
}

export const useVerifactu = () => {
  const api = useApi()

  /** Normalize the caller's transport options for `useApi`. */
  const req = (o: VerifactuRequestOptions = {}) => ({
    silent: o.silent,
    operation: o.operation
  })

  return {
    async getSettings(o: VerifactuRequestOptions = {}) {
      const r = await api.get<ApiResponse<VerifactuSettings>>('/api/v1/verifactu/settings', req(o))
      return r.data
    },
    async updateSettings(body: Partial<Pick<VerifactuSettings, 'enabled' | 'environment'>>, o: VerifactuRequestOptions = {}) {
      const r = await api.put<ApiResponse<VerifactuSettings>>('/api/v1/verifactu/settings', body, req(o))
      return r.data
    },
    async getProducerDefaults(o: VerifactuRequestOptions = {}) {
      const r = await api.get<ApiResponse<ProducerDefaults>>('/api/v1/verifactu/producer/defaults', req(o))
      return r.data
    },
    async updateProducer(body: ProducerInfoUpdate, o: VerifactuRequestOptions = {}) {
      const r = await api.put<ApiResponse<VerifactuSettings>>('/api/v1/verifactu/producer', body, req(o))
      return r.data
    },
    async revokeDeclaration(o: VerifactuRequestOptions = {}) {
      const r = await api.del<ApiResponse<VerifactuSettings>>('/api/v1/verifactu/producer/declaracion', req(o))
      return r.data
    },
    async getActiveCertificate(o: VerifactuRequestOptions = {}) {
      const r = await api.get<ApiResponse<VerifactuCertificate | null>>('/api/v1/verifactu/certificate', req(o))
      return r.data
    },
    async getCertificateHistory(o: VerifactuRequestOptions = {}) {
      const r = await api.get<ApiResponse<VerifactuCertificate[]>>('/api/v1/verifactu/certificate/history', req(o))
      return r.data
    },
    async uploadCertificate(file: File, password: string, o: VerifactuRequestOptions = {}) {
      const fd = new FormData()
      fd.append('file', file)
      fd.append('password', password)
      const r = await api.post<ApiResponse<VerifactuCertificate>>('/api/v1/verifactu/certificate', fd, req(o))
      return r.data
    },
    async listRecords(params: { page?: number, page_size?: number, state?: string, tipo_factura?: string, invoice_id?: string } = {}, o: VerifactuRequestOptions = {}) {
      const qs = new URLSearchParams()
      for (const [k, v] of Object.entries(params)) {
        if (v !== undefined && v !== null) qs.set(k, String(v))
      }
      const url = `/api/v1/verifactu/records${qs.toString() ? `?${qs.toString()}` : ''}`
      const r = await api.get<PaginatedResponse<VerifactuRecord>>(url, req(o))
      return r
    },
    async getLatestRecordForInvoice(invoiceId: string, o: VerifactuRequestOptions = {}) {
      const r = await api.get<PaginatedResponse<VerifactuRecord>>(
        `/api/v1/verifactu/records?invoice_id=${invoiceId}&page_size=1`,
        req(o)
      )
      return r.data?.[0] ?? null
    },
    async getRecord(id: string, o: VerifactuRequestOptions = {}) {
      const r = await api.get<ApiResponse<VerifactuRecordDetail>>(`/api/v1/verifactu/records/${id}`, req(o))
      return r.data
    },
    async listQueue(state?: string, o: VerifactuRequestOptions = {}) {
      const r = await api.get<ApiResponse<VerifactuQueueItem[]>>(
        '/api/v1/verifactu/queue',
        { ...req(o), query: state ? { state } : undefined }
      )
      return r.data
    },
    async retryRecord(id: string, opts: { regenerate?: boolean } & VerifactuRequestOptions = {}) {
      const qs = opts.regenerate === false ? '?regenerate=false' : ''
      const r = await api.post<ApiResponse<VerifactuRecord>>(
        `/api/v1/verifactu/queue/${id}/retry${qs}`,
        null,
        req(opts)
      )
      return r.data
    },
    async retryAllRejected(o: VerifactuRequestOptions = {}) {
      const r = await api.post<ApiResponse<RetryAllResult>>(
        '/api/v1/verifactu/queue/retry-all',
        null,
        req(o)
      )
      return r.data
    },
    async listRecordAttempts(id: string, o: VerifactuRequestOptions = {}) {
      const r = await api.get<ApiResponse<VerifactuRecordAttempt[]>>(
        `/api/v1/verifactu/records/${id}/attempts`,
        req(o)
      )
      return r.data
    },
    async checkNif(value: string, o: VerifactuRequestOptions = {}) {
      const r = await api.get<ApiResponse<NifCheckResult>>(
        `/api/v1/verifactu/nif-check?value=${encodeURIComponent(value)}`,
        req(o)
      )
      return r.data
    },
    async processNow(o: VerifactuRequestOptions = {}) {
      const r = await api.post<ApiResponse<{ processed: number }>>(
        '/api/v1/verifactu/queue/process-now',
        null,
        req(o)
      )
      return r.data
    },
    async health(o: VerifactuRequestOptions = {}) {
      const r = await api.get<ApiResponse<VerifactuHealth>>('/api/v1/verifactu/health', req(o))
      return r.data
    },
    async listVatMapping(o: VerifactuRequestOptions = {}) {
      const r = await api.get<ApiResponse<{ items: VatClassificationItem[] }>>(
        '/api/v1/verifactu/vat-mapping',
        req(o)
      )
      return r.data.items
    },
    async upsertVatMapping(
      vat_type_id: string,
      body: { classification: string | null, exemption_cause?: string | null, notes?: string | null },
      o: VerifactuRequestOptions = {}
    ) {
      const r = await api.put<ApiResponse<VatClassificationItem>>(
        `/api/v1/verifactu/vat-mapping/${vat_type_id}`,
        body,
        req(o)
      )
      return r.data
    }
  }
}

export interface VatClassificationItem {
  vat_type_id: string
  label: string
  rate: string
  is_default: boolean
  inferred_classification: string
  inferred_exemption_cause: string | null
  override_classification: string | null
  override_exemption_cause: string | null
  override_notes: string | null
}
