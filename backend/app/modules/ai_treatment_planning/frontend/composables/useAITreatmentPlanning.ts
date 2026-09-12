import type { ApiResponse } from '~~/app/types'

export interface PlanningStepPayload {
  step_id: string
  description: string
  purpose: string
  evidence_ids: string[]
  risk_factor_ids: string[]
}

export interface TreatmentOptionPayload {
  option_id: string
  title: string
  clinical_intent: string
  rationale: string
  evidence_ids: string[]
  risk_factor_ids: string[]
  steps: PlanningStepPayload[]
  uncertainties: string[]
  alternatives_or_tradeoffs: string[]
}

export interface AITreatmentPlanningPayload {
  id: string
  patient_id: string
  planning_version: number
  content: {
    advisory_only: true
    no_automatic_execution: true
    options: TreatmentOptionPayload[]
    data_gaps: Array<{ section: string, status: string, reason?: string | null }>
  }
  provenance: { provider: string, model: string, input_digest: string, output_digest: string }
  review_status: 'pending_review' | 'accepted' | 'rejected'
  clinical_output: boolean
  canonical_treatment_plan_created: boolean
}

/** Client for AI Treatment Planning drafts (advisory; dentist acceptance required before simulation). */
export function useAITreatmentPlanning(patientId: () => string) {
  const api = useApi()
  const planning = ref<AITreatmentPlanningPayload | null>(null)
  const loading = ref(false)
  const mutating = ref(false)
  const error = ref<string | null>(null)

  function baseUrl(): string {
    return `/api/v1/ai_treatment_planning/patients/${patientId()}`
  }

  async function load(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const response = await api.get<ApiResponse<AITreatmentPlanningPayload>>(`${baseUrl()}/latest`)
      planning.value = response.data
    } catch {
      planning.value = null
    } finally {
      loading.value = false
    }
  }

  async function generate(): Promise<boolean> {
    mutating.value = true
    error.value = null
    try {
      const response = await api.post<ApiResponse<AITreatmentPlanningPayload>>(baseUrl(), {})
      planning.value = response.data
      return true
    } catch (e) {
      error.value = aiActionableError(e, 'AI treatment planning could not be generated.')
      return false
    } finally {
      mutating.value = false
    }
  }

  async function review(decision: 'accepted' | 'rejected'): Promise<boolean> {
    if (!planning.value) return false
    mutating.value = true
    error.value = null
    try {
      const response = await api.post<ApiResponse<AITreatmentPlanningPayload>>(
        `/api/v1/ai_treatment_planning/results/${planning.value.id}/review`,
        { decision }
      )
      planning.value = response.data
      return true
    } catch (e) {
      error.value = aiActionableError(e, 'The planning review decision could not be recorded.')
      return false
    } finally {
      mutating.value = false
    }
  }

  return { planning, loading, mutating, error, load, generate, review }
}
