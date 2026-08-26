import type { ClinicalScene, PatientPointMm, PatientReferenceSpace, ReviewStatus } from './clinicalScene'
import type {
  RiskDisplayBand,
  RiskMapRegionPayload,
  RiskResultPayload
} from '../composables/useRiskEngine'

export interface ClinicalRiskRegion {
  id: string
  kind: 'polyline' | 'cylinder'
  frame: PatientReferenceSpace
  reviewStatus: ReviewStatus
  provenanceId: string
  displayBand: RiskDisplayBand
  factorIds: string[]
  evidenceIds: string[]
  points: PatientPointMm[]
  center: PatientPointMm | null
  axis: PatientPointMm | null
  radiusMm: number | null
  lengthMm: number | null
}

export type RiskClinicalScene = ClinicalScene & {
  riskRegions: ClinicalRiskRegion[]
}

function finitePoint(value: PatientPointMm | null | undefined): value is PatientPointMm {
  return Boolean(value)
    && Number.isFinite(value!.x)
    && Number.isFinite(value!.y)
    && Number.isFinite(value!.z)
}

function unitAxis(value: PatientPointMm | null | undefined): value is PatientPointMm {
  if (!finitePoint(value)) return false
  return Math.abs(Math.hypot(value.x, value.y, value.z) - 1) <= 1e-6
}

function reviewStatus(value: RiskResultPayload['review_status']): ReviewStatus {
  if (value === 'accepted') return 'accepted'
  if (value === 'rejected') return 'rejected'
  return 'pending'
}

function toRegion(
  payload: RiskMapRegionPayload,
  frame: PatientReferenceSpace,
  result: RiskResultPayload
): ClinicalRiskRegion | null {
  if (!payload.factor_ids.length || !payload.evidence_ids.length) return null
  if (payload.kind === 'polyline') {
    if (payload.points.length < 2 || !payload.points.every(finitePoint)) return null
    return {
      id: `risk:${result.id}:${payload.region_id}`,
      kind: 'polyline',
      frame,
      reviewStatus: reviewStatus(result.review_status),
      provenanceId: result.provenance.result_digest,
      displayBand: payload.display_band,
      factorIds: [...payload.factor_ids],
      evidenceIds: [...payload.evidence_ids],
      points: [...payload.points],
      center: null,
      axis: null,
      radiusMm: null,
      lengthMm: null
    }
  }
  const center = payload.center ?? null
  const axis = payload.axis ?? null
  const radius = Number(payload.radius_mm)
  const length = Number(payload.length_mm)
  if (!finitePoint(center) || !unitAxis(axis)) return null
  if (!Number.isFinite(radius) || radius <= 0 || !Number.isFinite(length) || length <= 0) return null
  return {
    id: `risk:${result.id}:${payload.region_id}`,
    kind: 'cylinder',
    frame,
    reviewStatus: reviewStatus(result.review_status),
    provenanceId: result.provenance.result_digest,
    displayBand: payload.display_band,
    factorIds: [...payload.factor_ids],
    evidenceIds: [...payload.evidence_ids],
    points: [],
    center,
    axis,
    radiusMm: radius,
    lengthMm: length
  }
}

/**
 * Attach only server-issued Risk Map regions that prove they share the
 * current ClinicalScene DICOM-patient/mm frame. No fallback/synthetic
 * geometry is ever created here.
 */
export function withRiskMap(
  scene: ClinicalScene | null,
  result: RiskResultPayload | null
): RiskClinicalScene | null {
  if (!scene) return null
  const empty: RiskClinicalScene = { ...scene, riskRegions: [] }
  if (!result || result.review_status === 'rejected') return empty
  const map = result.risk_map
  if (map.status !== 'available' || map.synthetic_geometry !== false || !map.frame) return empty
  if (
    map.frame.kind !== 'dicom_patient'
    || map.frame.unit !== 'mm'
    || map.frame.frame_of_reference_uid !== scene.frame.frameOfReferenceUid
  ) return empty

  const riskRegions = map.regions
    .map(region => toRegion(region, scene.frame, result))
    .filter((region): region is ClinicalRiskRegion => region !== null)
  return { ...scene, riskRegions }
}

export function riskRegionsOf(scene: ClinicalScene): ClinicalRiskRegion[] {
  return (scene as Partial<RiskClinicalScene>).riskRegions ?? []
}
