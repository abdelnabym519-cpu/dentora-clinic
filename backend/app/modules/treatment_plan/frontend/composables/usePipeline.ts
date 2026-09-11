/**
 * Pipeline composable — drives the bandeja de planes (5 tabs).
 *
 * Backend: GET /api/v1/treatment_plan/treatment-plans/pipeline
 * Returns shaped PipelineRow with patient + budget + next_appointment
 * data ready for the table / cards.
 */

import type { PaginatedResponse } from '~~/app/types'
import { errorMessage } from '~~/app/utils/error'
import { latestGuard } from '~~/app/utils/latestGuard'

export type PipelineTab
  = | 'por_presupuestar'
    | 'esperando_paciente'
    | 'sin_cita'
    | 'sin_proxima_cita'
    | 'cerrados'

export interface PipelinePatientBrief {
  id: string
  first_name: string
  last_name: string
  phone: string | null
}

export interface PipelineBudgetBrief {
  id: string
  status: string
  total: number | null
  valid_until: string | null
  last_reminder_sent_at: string | null
  viewed_at: string | null
}

export interface PipelineNextAppointment {
  id: string
  start_at: string
  cabinet_id: string | null
  professional_id: string | null
}

export interface PipelineRow {
  plan_id: string
  plan_number: string
  plan_title: string | null
  plan_status: string
  days_in_status: number
  closure_reason: string | null
  items_total: number
  items_completed: number
  patient: PipelinePatientBrief
  budget: PipelineBudgetBrief | null
  next_appointment: PipelineNextAppointment | null
}

export interface PipelineFilters {
  doctor_id?: string
  q?: string
  page?: number
  page_size?: number
}

export function usePipeline() {
  const api = useApi()
  const { t } = useI18n()

  // Tab, page, doctor filter and search all re-trigger the board. A late
  // answer used to overwrite `tab` too, so the board could flip itself back to
  // the column the user had already left.
  const pipelineGuard = latestGuard()

  const tab = ref<PipelineTab>('por_presupuestar')
  const rows = ref<PipelineRow[]>([])
  const total = ref(0)
  const page = ref(1)
  const pageSize = ref(20)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const filters = reactive<PipelineFilters>({})

  async function fetchPipeline(opts: {
    tab?: PipelineTab
    page?: number
    page_size?: number
    doctor_id?: string
    q?: string
  } = {}) {
    const isLatest = pipelineGuard.begin()
    loading.value = true
    error.value = null
    try {
      const targetTab = opts.tab ?? tab.value
      const params = new URLSearchParams()
      params.append('tab', targetTab)
      params.append('page', String(opts.page ?? page.value ?? 1))
      params.append('page_size', String(opts.page_size ?? pageSize.value ?? 20))
      const doctorId = opts.doctor_id ?? filters.doctor_id
      const search = opts.q ?? filters.q
      if (doctorId) params.append('doctor_id', doctorId)
      if (search) params.append('q', search)

      const response = await api.get<PaginatedResponse<PipelineRow>>(
        `/api/v1/treatment_plan/treatment-plans/pipeline?${params}`
      )
      if (!isLatest()) return
      tab.value = targetTab
      rows.value = response.data ?? []
      total.value = response.total
      page.value = response.page
      pageSize.value = response.page_size
    } catch (e) {
      if (!isLatest()) return
      error.value = errorMessage(e, t('errors.loadFailed'))
      rows.value = []
      total.value = 0
    } finally {
      if (isLatest()) loading.value = false
    }
  }

  async function setTab(next: PipelineTab) {
    if (tab.value === next) return
    page.value = 1
    await fetchPipeline({ tab: next, page: 1 })
  }

  async function refresh() {
    await fetchPipeline({})
  }

  return {
    // State
    tab,
    rows,
    total,
    page,
    pageSize,
    loading,
    error,
    filters,

    // Actions
    fetchPipeline,
    setTab,
    refresh
  }
}
