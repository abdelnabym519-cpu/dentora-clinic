import type { ApiResponse } from '~~/app/types'

export interface SummaryClaimPayload {
  claim_id: string
  text: string
  evidence_ids: string[]
  uncertainty?: string | null
}

export interface AICaseSummaryPayload {
  id: string
  patient_id: string
  summary_version: number
  content: {
    advisory_only: true
    clinical_output: false
    claims: SummaryClaimPayload[]
    data_gaps: Array<{ section: string, status: string, reason?: string | null }>
  }
  provenance: { provider: string, model: string, input_digest: string, output_digest: string }
  review_status: 'pending_review' | 'accepted' | 'rejected'
  clinical_output: boolean
  generated_at: string
  advisory_only?: true
}

/**
 * Client for AI Case Summary (advisory, evidence-traceable). Generation
 * uses the clinic-configured LLM provider; a dentist must review every
 * result (backend enforces review-state transitions).
 */
export function useAICaseSummary(patientId: () => string) {
  const api = useApi()
  const summary = ref<AICaseSummaryPayload | null>(null)
  const loading = ref(false)
  const mutating = ref(false)
  const error = ref<string | null>(null)

  function baseUrl(): string {
    return `/api/v1/ai_case_summary/patients/${patientId()}`
  }

  async function load(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const response = await api.get<ApiResponse<AICaseSummaryPayload>>(`${baseUrl()}/latest`)
      summary.value = response.data
    } catch {
      summary.value = null
    } finally {
      loading.value = false
    }
  }

  async function generate(): Promise<boolean> {
    mutating.value = true
    error.value = null
    try {
      const response = await api.post<ApiResponse<AICaseSummaryPayload>>(baseUrl(), {})
      summary.value = response.data
      return true
    } catch (e) {
      error.value = aiActionableError(e, 'AI case summary could not be generated.')
      return false
    } finally {
      mutating.value = false
    }
  }

  async function review(decision: 'accepted' | 'rejected'): Promise<boolean> {
    if (!summary.value) return false
    mutating.value = true
    error.value = null
    try {
      const response = await api.post<ApiResponse<AICaseSummaryPayload>>(
        `/api/v1/ai_case_summary/summaries/${summary.value.id}/review`,
        { decision }
      )
      summary.value = response.data
      return true
    } catch (e) {
      error.value = aiActionableError(e, 'The review decision could not be recorded.')
      return false
    } finally {
      mutating.value = false
    }
  }

  return { summary, loading, mutating, error, load, generate, review }
}
