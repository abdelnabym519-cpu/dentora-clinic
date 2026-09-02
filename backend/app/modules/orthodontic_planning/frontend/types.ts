export type OrthoProposalStatus = 'draft' | 'approved' | 'rejected'
export type OrthoSkeletalPattern = 'class_i' | 'class_ii' | 'class_iii'
export type OrthoGrowthStage = 'adolescent' | 'adult'
export type OrthoRelation = 'class_i' | 'class_ii' | 'class_iii'
export type OrthoObjective
  = | 'align'
    | 'correct_overjet'
    | 'correct_overbite'
    | 'correct_crossbite'
    | 'space_management'

export interface OrthoCapabilities {
  provider: string
  provider_version: string
  constraints_version: string
  decision_support_only: boolean
  deterministic: boolean
  approval_required: boolean
  planned_months_per_stage_weeks: number
  required_measurements: string[]
  min_charted_permanent_teeth: number
  movement_limits: Record<string, { per_stage: number, per_tooth_total: number }>
  envelopes: Record<string, number>
}

export interface OrthoDataSufficiency {
  is_plannable: boolean
  missing: string[]
  score: number
  charted_permanent: number
}

export interface OrthoAssessmentSummary {
  id: string
  patient_id: string
  skeletal_pattern: OrthoSkeletalPattern | null
  growth_stage: OrthoGrowthStage | null
  overjet_mm: number | null
  overbite_mm: number | null
  crowding_upper_mm: number | null
  crowding_lower_mm: number | null
  posterior_crossbite: boolean
  objectives: OrthoObjective[] | null
  is_plannable: boolean
  created_at: string
}

export interface OrthoProposalSummary {
  id: string
  patient_id: string
  assessment_id: string
  provider: string
  provider_version: string
  constraints_version: string
  status: OrthoProposalStatus
  stage_count: number
  planned_months: number
  score: number
  confidence: number
  hard_violation_count: number
  soft_finding_count: number
  created_at: string
}
