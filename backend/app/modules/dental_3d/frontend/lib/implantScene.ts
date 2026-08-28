import type { ClinicalScene, PatientPointMm, PatientReferenceSpace } from './clinicalScene'
import type {
  ImplantAssessmentPayload,
  ImplantPlanningPayload,
  ImplantPlanStatus
} from '../composables/useDental3DImplantPlanning'

export interface ClinicalImplantOverlay {
  id: string
  planId: string
  revisionNumber: number
  status: Exclude<ImplantPlanStatus, 'rejected'>
  center: PatientPointMm
  axis: PatientPointMm
  diameterMm: number
  lengthMm: number
  frame: PatientReferenceSpace
  assessment: ImplantAssessmentPayload
}

export interface ClinicalProstheticTargetOverlay {
  id: string
  center: PatientPointMm
  axis: PatientPointMm
  frame: PatientReferenceSpace
  reviewStatus: 'accepted'
}

export type ImplantClinicalScene = ClinicalScene & {
  implants: ClinicalImplantOverlay[]
  prostheticTargets: ClinicalProstheticTargetOverlay[]
}

function finitePoint(value: PatientPointMm): boolean {
  return Number.isFinite(value.x) && Number.isFinite(value.y) && Number.isFinite(value.z)
}

function unitAxis(value: PatientPointMm): boolean {
  if (!finitePoint(value)) return false
  const norm = Math.hypot(value.x, value.y, value.z)
  return Math.abs(norm - 1) <= 1e-6
}

/**
 * Add only server-owned implant/prosthetic geometry that proves it shares
 * the ClinicalScene DICOM patient frame. No renderer coordinate is persisted.
 */
export function withImplantPlanning(
  scene: ClinicalScene | null,
  planning: ImplantPlanningPayload | null
): ImplantClinicalScene | null {
  if (!scene) return null

  const implants: ClinicalImplantOverlay[] = []
  for (const plan of planning?.plans ?? []) {
    if (plan.status === 'rejected') continue
    const revision = plan.current_revision
    const candidate = revision.candidate
    if (candidate.frame_of_reference_uid !== scene.frame.frameOfReferenceUid) continue
    if (candidate.unit !== 'mm') continue
    if (!finitePoint(candidate.center) || !unitAxis(candidate.axis)) continue
    if (!Number.isFinite(candidate.diameter_mm) || candidate.diameter_mm <= 0) continue
    if (!Number.isFinite(candidate.length_mm) || candidate.length_mm <= 0) continue
    implants.push({
      id: revision.id,
      planId: plan.id,
      revisionNumber: revision.revision_number,
      status: plan.status,
      center: candidate.center,
      axis: candidate.axis,
      diameterMm: candidate.diameter_mm,
      lengthMm: candidate.length_mm,
      frame: scene.frame,
      assessment: revision.assessment
    })
  }

  const prostheticTargets: ClinicalProstheticTargetOverlay[] = []
  const target = planning?.latest_target
  if (
    target?.review_status === 'accepted'
    && target.frame_of_reference_uid === scene.frame.frameOfReferenceUid
    && finitePoint(target.platform_center)
    && unitAxis(target.axis)
  ) {
    prostheticTargets.push({
      id: target.id,
      center: target.platform_center,
      axis: target.axis,
      frame: scene.frame,
      reviewStatus: 'accepted'
    })
  }

  return {
    ...scene,
    implants,
    prostheticTargets
  }
}

export function implantPlanningOf(scene: ClinicalScene): Pick<
  ImplantClinicalScene,
  'implants' | 'prostheticTargets'
> {
  const value = scene as Partial<ImplantClinicalScene>
  return {
    implants: value.implants ?? [],
    prostheticTargets: value.prostheticTargets ?? []
  }
}
