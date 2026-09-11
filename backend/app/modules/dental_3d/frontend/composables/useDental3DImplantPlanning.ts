import type { ApiResponse } from '~~/app/types'
import { errorMessage } from '~~/app/utils/error'
import type { PatientPointMm } from '../lib/clinicalScene'

/**
 * Fallbacks for when the backend supplied no explanation. Implant
 * planning rejects unmet prerequisites with a 409 whose detail names
 * them ("Prosthetic target is stale", "Nerve analysis is required");
 * `errorMessage` surfaces that text so the dentist sees the actual
 * prerequisite instead of a generic failure.
 */
const PLANNING_UNAVAILABLE = 'Implant planning is unavailable.'
const TARGET_SAVE_FAILED = 'The prosthetic target could not be saved.'
const TARGET_REVIEW_FAILED = 'The prosthetic target review could not be recorded.'
const PLAN_SAVE_FAILED = 'The implant draft could not be saved.'
const PLAN_EDIT_FAILED = 'The implant revision could not be saved.'
const PLAN_ACCEPT_BLOCKED = 'The plan cannot be accepted until its prosthetic target is current and accepted.'
const PLAN_REVIEW_FAILED = 'The implant plan review could not be recorded.'

export type ImplantPlanStatus = 'draft' | 'proposed' | 'accepted' | 'rejected'
export type ProstheticReviewStatus = 'pending_review' | 'accepted' | 'rejected'

export interface ImplantAxis {
  x: number
  y: number
  z: number
}

export interface ProstheticTargetPayload {
  id: string
  patient_id: string
  alignment_id: string
  platform_center: PatientPointMm
  axis: ImplantAxis
  frame_of_reference_uid: string
  source_type: 'dentist_defined' | 'registered_ios' | 'prosthetic_scan' | 'prosthetic_design'
  source_reference_space: 'ios_mesh' | 'dicom_patient'
  source_frame_of_reference_uid?: string | null
  source_method: string
  source_identifier: string
  source_digest?: string | null
  source_document_ids: string[]
  review_status: ProstheticReviewStatus
  reviewed_at?: string | null
  review_note?: string | null
}

export interface PlanningCheckPayload {
  status: 'AVAILABLE' | 'UNAVAILABLE'
  value: number | null
  unit?: string | null
  semantics: string
}

export interface ImplantCandidatePayload {
  center: PatientPointMm
  axis: ImplantAxis
  diameter_mm: number
  length_mm: number
  frame_of_reference_uid: string
  unit: 'mm'
  catalog_entry_id?: string | null
  dimension_source: string
}

export interface ImplantAssessmentPayload {
  prosthetic_offset_mm: PlanningCheckPayload
  prosthetic_axis_angle_deg: PlanningCheckPayload
  nerve_surface_to_centerline_mm: PlanningCheckPayload
  bone_axis_span_mm: PlanningCheckPayload
  bone_width_1_mm: PlanningCheckPayload
  bone_width_2_mm: PlanningCheckPayload
  bone_contained_fraction: PlanningCheckPayload
  bone_contained_volume_mm3: PlanningCheckPayload
  intersects_nerve_centerline: boolean | null
  clinical_threshold_status: 'NO_CLINICAL_THRESHOLD_DEFINED'
}

export interface ImplantPlanPayload {
  id: string
  patient_id: string
  status: ImplantPlanStatus
  current_revision: {
    id: string
    plan_id: string
    revision_number: number
    candidate: ImplantCandidatePayload
    assessment: ImplantAssessmentPayload
    planning_case: {
      frame_of_reference_uid: string
      alignment_id: string
      prosthetic_target_id?: string | null
      prosthetic_status: 'accepted' | 'unavailable'
      nerve_analysis_id?: string | null
      bone_volume_status: 'UNAVAILABLE'
    }
    policy?: {
      criteria: Array<{
        name: string
        direction: 'asc' | 'desc'
      }>
    } | null
  }
  reviewed_at?: string | null
  review_note?: string | null
  requires_review: true
  is_clinical: false
  disclaimer: string
}

export interface ImplantPlanningPayload {
  prosthetic: {
    status: 'available' | 'unavailable'
    target?: ProstheticTargetPayload | null
    reason?: string | null
  }
  latest_target?: ProstheticTargetPayload | null
  plans: ImplantPlanPayload[]
}

export interface DentistDefinedTargetInput {
  alignment_id: string
  platform_center: PatientPointMm
  axis: ImplantAxis
  frame_of_reference_uid: string
  source_identifier: string
}

export function useDental3DImplantPlanning(patientId: () => string) {
  const api = useApi()
  const snapshot = ref<ImplantPlanningPayload | null>(null)
  const loading = ref(false)
  const mutating = ref(false)
  const error = ref<string | null>(null)

  function baseUrl(): string {
    return `/api/v1/dental_3d/patients/${patientId()}`
  }

  async function load(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      // Ambient load (mounted with the patient summary card) — the card
      // renders the failure inline, so no global toast.
      const response = await api.get<ApiResponse<ImplantPlanningPayload>>(
        `${baseUrl()}/implant-planning`,
        { silent: true }
      )
      snapshot.value = response.data
    } catch (e: unknown) {
      snapshot.value = null
      error.value = errorMessage(e, PLANNING_UNAVAILABLE)
    } finally {
      loading.value = false
    }
  }

  async function createDentistTarget(input: DentistDefinedTargetInput): Promise<boolean> {
    mutating.value = true
    error.value = null
    try {
      await api.post<ApiResponse<ProstheticTargetPayload>>(
        `${baseUrl()}/prosthetic-targets`,
        {
          alignment_id: input.alignment_id,
          platform_center: input.platform_center,
          axis: input.axis,
          frame_of_reference_uid: input.frame_of_reference_uid,
          source_type: 'dentist_defined',
          source_reference_space: 'dicom_patient',
          source_frame_of_reference_uid: input.frame_of_reference_uid,
          source_method: 'explicit_dentist_entry',
          source_identifier: input.source_identifier,
          source_document_ids: []
        },
        { silent: true }
      )
      await load()
      return true
    } catch (e: unknown) {
      error.value = errorMessage(e, TARGET_SAVE_FAILED)
      return false
    } finally {
      mutating.value = false
    }
  }

  async function reviewTarget(decision: 'accepted' | 'rejected', note?: string): Promise<boolean> {
    const targetId = snapshot.value?.latest_target?.id
    if (!targetId) return false
    mutating.value = true
    error.value = null
    try {
      await api.post<ApiResponse<ProstheticTargetPayload>>(
        `${baseUrl()}/prosthetic-targets/${targetId}/review`,
        { decision, note: note ?? null },
        { silent: true }
      )
      await load()
      return true
    } catch (e: unknown) {
      error.value = errorMessage(e, TARGET_REVIEW_FAILED)
      return false
    } finally {
      mutating.value = false
    }
  }

  async function createManualPlan(candidate: ImplantCandidatePayload): Promise<boolean> {
    mutating.value = true
    error.value = null
    try {
      await api.post<ApiResponse<ImplantPlanPayload>>(
        `${baseUrl()}/implant-plans`,
        { candidate },
        { silent: true }
      )
      await load()
      return true
    } catch (e: unknown) {
      error.value = errorMessage(e, PLAN_SAVE_FAILED)
      return false
    } finally {
      mutating.value = false
    }
  }

  async function editPlan(planId: string, candidate: ImplantCandidatePayload): Promise<boolean> {
    mutating.value = true
    error.value = null
    try {
      await api.put<ApiResponse<ImplantPlanPayload>>(
        `${baseUrl()}/implant-plans/${planId}`,
        { candidate },
        { silent: true }
      )
      await load()
      return true
    } catch (e: unknown) {
      error.value = errorMessage(e, PLAN_EDIT_FAILED)
      return false
    } finally {
      mutating.value = false
    }
  }

  async function reviewPlan(
    planId: string,
    decision: 'accepted' | 'rejected',
    note?: string
  ): Promise<boolean> {
    mutating.value = true
    error.value = null
    try {
      await api.post<ApiResponse<ImplantPlanPayload>>(
        `${baseUrl()}/implant-plans/${planId}/review`,
        { decision, note: note ?? null },
        { silent: true }
      )
      await load()
      return true
    } catch (e: unknown) {
      error.value = errorMessage(
        e,
        decision === 'accepted' ? PLAN_ACCEPT_BLOCKED : PLAN_REVIEW_FAILED
      )
      return false
    } finally {
      mutating.value = false
    }
  }

  return {
    snapshot,
    loading,
    mutating,
    error,
    load,
    createDentistTarget,
    reviewTarget,
    createManualPlan,
    editPlan,
    reviewPlan
  }
}
