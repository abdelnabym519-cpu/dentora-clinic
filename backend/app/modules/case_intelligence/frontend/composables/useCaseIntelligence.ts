import type { ApiResponse } from '~~/app/types'

export type AvailabilityStatus = 'available' | 'not_available' | 'invalid_or_stale'

export interface CaseSectionPayload {
  status: AvailabilityStatus
  data?: unknown
  evidence: Array<{ evidence_id: string, source_module: string, source_entity: string }>
  reason?: string | null
}

export interface CaseSnapshotPayload {
  contract_version: string
  case_snapshot_version: number
  identity: { clinic_id: string, patient_id: string }
  reference_frame: CaseSectionPayload
  clinical_state: Record<string, CaseSectionPayload>
  availability: Record<string, AvailabilityStatus>
  input_digest?: string
}

/**
 * Client for the deterministic Case Intelligence evidence snapshot.
 * Case Intelligence aggregates existing clinical evidence — it performs
 * no AI reasoning by design (ADR 0027).
 */
export function useCaseIntelligence(patientId: () => string) {
  const api = useApi()
  const snapshot = ref<CaseSnapshotPayload | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function load(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const response = await api.get<ApiResponse<CaseSnapshotPayload>>(
        `/api/v1/case_intelligence/patients/${patientId()}`
      )
      snapshot.value = response.data
    } catch (e) {
      snapshot.value = null
      error.value = aiActionableError(e, 'Case Intelligence snapshot could not be loaded.')
    } finally {
      loading.value = false
    }
  }

  const sectionSummary = computed(() => {
    if (!snapshot.value) return []
    return Object.entries(snapshot.value.clinical_state).map(([name, section]) => ({
      name,
      status: section.status,
      evidenceCount: section.evidence?.length ?? 0,
      reason: section.reason ?? null
    }))
  })

  return { snapshot, sectionSummary, loading, error, load }
}
