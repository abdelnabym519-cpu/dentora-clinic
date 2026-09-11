import type { ApiResponse } from '~~/app/types'

export interface ClinicalStageStatusPayload {
  stage: string
  state: 'ready' | 'missing' | 'stale' | 'unavailable'
  detail?: string | null
}

export interface AdvisoryClaimPayload {
  text: string
  evidence_ids: string[]
}

export interface AIClinicalReportPayload {
  contract_version: string
  patient_id: string
  status: string
  sections: Array<{
    section: string
    state: ClinicalStageStatusPayload['state'] | null
    evidence_refs: string[]
    claims: AdvisoryClaimPayload[]
  }>
  limitations: string[]
  provenance: { provider: string, model: string, report_output_digest: string, generated_at: string }
  advisory_only: boolean
  dentist_review_required: boolean
  autonomous_diagnosis: boolean
  autonomous_treatment_decision: boolean
}

export interface ReportReadinessPayload {
  ready_for_report: boolean
  stages: ClinicalStageStatusPayload[]
  missing_or_stale: string[]
  advisory_only: boolean
  dentist_control_required: boolean
}

/** Client for the compiled AI Clinical Report (advisory compilation of the clinical-AI pipeline). */
export function useAIClinicalReport(patientId: () => string) {
  const api = useApi()
  const report = ref<AIClinicalReportPayload | null>(null)
  const readiness = ref<ReportReadinessPayload | null>(null)
  const loading = ref(false)
  const mutating = ref(false)
  const error = ref<string | null>(null)

  async function loadReadiness(): Promise<void> {
    try {
      const response = await api.get<ApiResponse<ReportReadinessPayload>>(
        `/api/v1/ai_clinical_report/patients/${patientId()}/readiness`
      )
      readiness.value = response.data
    } catch {
      readiness.value = null
    }
  }

  async function generate(): Promise<boolean> {
    mutating.value = true
    error.value = null
    try {
      const response = await api.post<ApiResponse<AIClinicalReportPayload>>(
        '/api/v1/ai_clinical_report/generate',
        { patient_id: patientId() }
      )
      report.value = response.data
      return true
    } catch (e) {
      error.value = aiActionableError(e, 'AI clinical report could not be generated.')
      return false
    } finally {
      mutating.value = false
    }
  }

  return { report, readiness, loading, mutating, error, loadReadiness, generate }
}
