/**
 * State + API client for orthodontic planning (decision support).
 *
 * Thin wrapper over `useApi()` mirroring `usePathologyDetection` /
 * `usePeriodontogram`: all error mapping stays on the server
 * (404/409/422/503); the composable surfaces message strings.
 */

import { computed, ref } from 'vue'
import type {
  OrthoAssessmentSummary,
  OrthoCapabilities,
  OrthoProposalSummary
} from '../types'

interface ApiResponse<T> {
  data: T
  message?: string | null
}

export function useOrthodonticPlanning(patientId: () => string) {
  const api = useApi()

  const capabilities = ref<OrthoCapabilities | null>(null)
  const assessments = ref<OrthoAssessmentSummary[]>([])
  const proposals = ref<OrthoProposalSummary[]>([])
  const isLoading = ref(false)
  const isGenerating = ref(false)
  const error = ref<string | null>(null)

  const latestAssessment = computed(() => assessments.value[0] ?? null)
  const latestProposal = computed(() => proposals.value[0] ?? null)
  const hasProposals = computed(() => proposals.value.length > 0)

  function extractDetail(payload: unknown, fallback: string): string {
    if (typeof payload === 'string') return payload
    if (payload && typeof payload === 'object' && 'message' in payload) {
      return String((payload as { message?: unknown }).message ?? fallback)
    }
    return fallback
  }

  async function fetchCapabilities(): Promise<void> {
    try {
      const response = await api.get<ApiResponse<OrthoCapabilities>>(
        '/api/v1/orthodontic_planning/capabilities'
      )
      capabilities.value = response.data
    } catch {
      capabilities.value = null
    }
  }

  async function fetchCase(): Promise<void> {
    isLoading.value = true
    error.value = null
    try {
      const [assessmentRes, proposalRes] = await Promise.all([
        api.get<ApiResponse<OrthoAssessmentSummary[]>>(
          `/api/v1/orthodontic_planning/patients/${patientId()}/assessments`
        ),
        api.get<ApiResponse<OrthoProposalSummary[]>>(
          `/api/v1/orthodontic_planning/patients/${patientId()}/proposals`
        )
      ])
      assessments.value = assessmentRes.data
      proposals.value = proposalRes.data
    } catch (err: unknown) {
      error.value = err instanceof Error ? err.message : String(err)
    } finally {
      isLoading.value = false
    }
  }

  /**
   * Ask the backend planner for a proposal off the latest assessment.
   * Returns true on success; on failure fills `error` (including the
   * fail-closed 422 missing-data and safety-refusal cases).
   */
  async function generatePlan(): Promise<boolean> {
    if (!latestAssessment.value) {
      error.value = 'No assessment recorded for this patient yet.'
      return false
    }
    isGenerating.value = true
    error.value = null
    try {
      await api.post<ApiResponse<OrthoProposalSummary>>(
        `/api/v1/orthodontic_planning/assessments/${latestAssessment.value.id}/plan`,
        {}
      )
      await fetchCase()
      return true
    } catch (err: unknown) {
      const detail = (err as { data?: unknown })?.data ?? err
      error.value = extractDetail(detail, 'Planning request failed.')
      return false
    } finally {
      isGenerating.value = false
    }
  }

  return {
    capabilities,
    assessments,
    proposals,
    latestAssessment,
    latestProposal,
    hasProposals,
    isLoading,
    isGenerating,
    error,
    fetchCapabilities,
    fetchCase,
    generatePlan
  }
}
