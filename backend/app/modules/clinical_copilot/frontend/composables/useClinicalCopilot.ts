import type { ApiResponse } from '~~/app/types'

export type CopilotFocus = 'case_review' | 'risk_context' | 'treatment_options' | 'simulation_context' | 'second_review'

export interface ClinicalStageStatePayload {
  stage: string
  state: 'ready' | 'missing' | 'stale' | 'unavailable'
}

export interface ClinicalCopilotContextPayload {
  stages: ClinicalStageStatePayload[]
  missing_or_stale: string[]
  ready_for_advice: boolean
  input_digest: string
  advisory_only: boolean
  dentist_control_required: boolean
}

export interface ClinicalCopilotAdvisoryPayload {
  patient_id: string
  claims: Array<{ text: string, evidence_ids: string[] }>
  limitations: string[]
  provenance: { provider: string, model: string, generated_at: string }
  advisory_only: boolean
  dentist_review_required: boolean
  autonomous_diagnosis: boolean
  autonomous_treatment_decision: boolean
}

/** Client for the guarded Clinical Copilot advisory (readiness gates + dentist control preserved). */
export function useClinicalCopilot(patientId: () => string) {
  const api = useApi()
  const context = ref<ClinicalCopilotContextPayload | null>(null)
  const advisory = ref<ClinicalCopilotAdvisoryPayload | null>(null)
  const loading = ref(false)
  const mutating = ref(false)
  const error = ref<string | null>(null)

  async function loadContext(): Promise<void> {
    try {
      const response = await api.get<ApiResponse<ClinicalCopilotContextPayload>>(
        `/api/v1/clinical_copilot/patients/${patientId()}/context`
      )
      context.value = response.data
    } catch {
      context.value = null
    }
  }

  async function advise(focus: CopilotFocus): Promise<boolean> {
    mutating.value = true
    error.value = null
    try {
      const response = await api.post<ApiResponse<ClinicalCopilotAdvisoryPayload>>(
        '/api/v1/clinical_copilot/advise',
        { patient_id: patientId(), focus }
      )
      advisory.value = response.data
      return true
    } catch (e) {
      error.value = aiActionableError(e, 'Clinical Copilot advisory could not be generated.')
      return false
    } finally {
      mutating.value = false
    }
  }

  return { context, advisory, loading, mutating, error, loadContext, advise }
}
