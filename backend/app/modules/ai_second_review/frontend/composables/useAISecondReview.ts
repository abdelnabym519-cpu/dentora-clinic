import type { ApiResponse } from '~~/app/types'

export interface SecondReviewFindingPayload {
  finding_id: string
  category: string
  statement: string
  evidence_ids: string[]
  risk_factor_ids: string[]
  planning_refs: string[]
  simulation_refs: string[]
}

export interface AISecondReviewPayload {
  id: string
  patient_id: string
  review_version: number
  chain_reference: {
    case_snapshot_version: number
    planning_id: string
    planning_output_digest: string
  }
  content: {
    advisory_only: true
    no_treatment_approval: true
    no_canonical_record_mutation: true
    findings: SecondReviewFindingPayload[]
    data_gaps: Array<{ section: string, status: string, reason?: string | null }>
  }
  provenance: { provider: string, model: string }
  review_status: string
  clinical_output: boolean
  approves_treatment: false
}

export interface SimulationOptionPayload {
  id: string
  simulation_version: number
  generated_at: string
}

/**
 * Client for AI Second Review. Generation REQUIRES an existing treatment
 * simulation (`simulation_id`) — the card offers the patient's simulations
 * as the eligible input set. The result is advisory-only; the dentist must
 * explicitly mark it reviewed.
 */
export function useAISecondReview(patientId: () => string) {
  const api = useApi()
  const review = ref<AISecondReviewPayload | null>(null)
  const simulations = ref<SimulationOptionPayload[]>([])
  const loading = ref(false)
  const mutating = ref(false)
  const error = ref<string | null>(null)

  function baseUrl(): string {
    return `/api/v1/ai_second_review/patients/${patientId()}`
  }

  async function load(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const response = await api.get<ApiResponse<AISecondReviewPayload>>(`${baseUrl()}/latest`)
      review.value = response.data
    } catch {
      review.value = null
    } finally {
      loading.value = false
    }
  }

  async function loadSimulations(): Promise<void> {
    try {
      const response = await api.get<ApiResponse<SimulationOptionPayload[]>>(
        `/api/v1/treatment_simulation/patients/${patientId()}/history`
      )
      simulations.value = response.data ?? []
    } catch {
      simulations.value = []
    }
  }

  async function generate(simulationId: string): Promise<boolean> {
    mutating.value = true
    error.value = null
    try {
      const response = await api.post<ApiResponse<AISecondReviewPayload>>(baseUrl(), {
        simulation_id: simulationId
      })
      review.value = response.data
      return true
    } catch (e) {
      error.value = aiActionableError(
        e,
        'AI second review requires a treatment simulation of an accepted plan.'
      )
      return false
    } finally {
      mutating.value = false
    }
  }

  async function markReviewed(): Promise<boolean> {
    if (!review.value) return false
    mutating.value = true
    error.value = null
    try {
      const response = await api.post<ApiResponse<AISecondReviewPayload>>(
        `/api/v1/ai_second_review/results/${review.value.id}/review`,
        { reviewed: true }
      )
      review.value = response.data
      return true
    } catch (e) {
      error.value = aiActionableError(e, 'The review confirmation could not be recorded.')
      return false
    } finally {
      mutating.value = false
    }
  }

  return { review, simulations, loading, mutating, error, load, loadSimulations, generate, markReviewed }
}
