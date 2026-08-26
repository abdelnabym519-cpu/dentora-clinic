import type { ApiResponse } from '~~/app/types'
import type { PatientPointMm } from '../lib/clinicalScene'

export type RiskFactorState = 'present' | 'absent' | 'not_available' | 'invalid_or_stale'
export type RiskDisplayBand = 'evidence_present' | 'evidence_absent' | 'data_gap' | 'invalid_source'
export type RiskReviewStatus = 'pending_review' | 'accepted' | 'rejected'

export interface RiskFactorPayload {
  factor_id: string
  label: string
  state: RiskFactorState
  display_band: RiskDisplayBand
  evidence_ids: string[]
  observed_value?: boolean | number | string | null
  unit?: string | null
  semantics: string
}

export interface RiskMapRegionPayload {
  region_id: string
  kind: 'polyline' | 'cylinder'
  display_band: RiskDisplayBand
  factor_ids: string[]
  evidence_ids: string[]
  points: PatientPointMm[]
  center?: PatientPointMm | null
  axis?: PatientPointMm | null
  radius_mm?: number | null
  length_mm?: number | null
}

export interface RiskMapPayload {
  status: 'available' | 'unavailable'
  frame?: {
    kind: 'dicom_patient'
    unit: 'mm'
    frame_of_reference_uid: string
  } | null
  regions: RiskMapRegionPayload[]
  reason?: string | null
  advisory_only: true
  synthetic_geometry: false
}

export interface RiskResultPayload {
  id: string
  patient_id: string
  result_version: number
  contract_version: string
  factors: RiskFactorPayload[]
  evidence: Array<{
    evidence_id: string
    source_module: string
    source_entity: string
    source_record_id?: string | null
    source_version?: string | null
    source_digest?: string | null
    validation_state?: string | null
  }>
  risk_map: RiskMapPayload
  provenance: {
    case_snapshot_version: number
    case_snapshot_contract_version: string
    source_digest: string
    input_digest: string
    result_digest: string
    engine_version: string
    policy_version: string
    generated_at: string
    availability_state: 'available' | 'partial' | 'unavailable' | 'invalid_or_stale'
  }
  review_status: RiskReviewStatus
  generated_by?: string | null
  reviewed_at?: string | null
  reviewed_by?: string | null
  advisory_only: true
  requires_review: true
  is_clinical: false
  disclaimer: string
}

export function useRiskEngine(patientId: () => string) {
  const api = useApi()
  const result = ref<RiskResultPayload | null>(null)
  const loading = ref(false)
  const mutating = ref(false)
  const error = ref<string | null>(null)

  function baseUrl(): string {
    return `/api/v1/risk_engine/patients/${patientId()}`
  }

  async function load(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const response = await api.get<ApiResponse<RiskResultPayload>>(`${baseUrl()}/latest`)
      result.value = response.data
    } catch {
      result.value = null
    } finally {
      loading.value = false
    }
  }

  async function generate(): Promise<boolean> {
    mutating.value = true
    error.value = null
    try {
      const response = await api.post<ApiResponse<RiskResultPayload>>(baseUrl(), {})
      result.value = response.data
      return true
    } catch {
      error.value = 'Risk evaluation could not be generated.'
      return false
    } finally {
      mutating.value = false
    }
  }

  async function review(decision: 'accepted' | 'rejected'): Promise<boolean> {
    if (!result.value) return false
    mutating.value = true
    error.value = null
    try {
      const response = await api.post<ApiResponse<RiskResultPayload>>(
        `/api/v1/risk_engine/results/${result.value.id}/review`,
        { decision }
      )
      result.value = response.data
      return true
    } catch {
      error.value = 'Risk review could not be recorded.'
      return false
    } finally {
      mutating.value = false
    }
  }

  return { result, loading, mutating, error, load, generate, review }
}
