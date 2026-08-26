/**
 * nerveView — pure projection of nerve-detection analyses to views.
 *
 * Framework-free seam (ADR 0019 / ADR 0022): the backend speaks
 * ``NerveDetectionAnalysisResponse`` descriptors (``nerve.py``); the
 * card and viewer want normalized view models. This module is the
 * pure translation — no three.js, no Vue, no fetching — so it stays
 * unit-testable, mirroring ``dentalArch.ts`` / ``segmentationView.ts``.
 *
 * Safety invariants mirrored from the backend contracts: analyses are
 * **AI-assisted / simulated, non-clinical decision support**
 * (``nonClinical: true`` is the only representable state) and always
 * **require dentist verification**. Proximities are AI-estimated
 * planning support — the projection never invents pathways, distances
 * or warnings, and never labels a tooth clinically unsafe: invalid
 * entries are dropped, never repaired.
 */

import type { DentalToothView } from './dentalArch'

export type NerveSide = 'left' | 'right'

export type NervePathwayStatus = 'detected' | 'uncertain'

export type NerveProximityWarning = 'near' | 'watch' | 'none'

export type NerveReviewStatus = 'pending' | 'accepted' | 'rejected' | 'not_applicable'
export type NerveDetectionStatus = 'detected' | 'no_detection' | 'uncertain' | 'failed'

export type ConfidenceBand = 'high' | 'medium' | 'low'

/** Confidence bands — mirrors backend thresholds (ADR 0021 / ADR 0022). */
export const CONFIDENCE_BAND_HIGH = 0.8
export const CONFIDENCE_BAND_MEDIUM = 0.6

/** One pathway polyline point in the canonical arch frame. */
export type NervePointView = { x: number, y: number, z: number }

/** One mandibular pathway, normalized for display. */
export type NervePathwayView = {
  side: NerveSide
  region: string
  source: string
  status: NervePathwayStatus
  confidence: number
  referenceSpace: 'canonical_arch' | 'dicom_patient'
  points: NervePointView[]
  basis: string
  note: string | null
  backingDocuments: string[]
}

/** One AI-estimated tooth proximity, normalized for display. */
export type NerveProximityView = {
  toothNumber: number
  side: NerveSide
  distanceMm: number
  closestPointIndex: number
  warning: NerveProximityWarning
  confidence: number
}

/** A whole analysis, normalized for the card + viewer overlays. */
export type NerveAnalysisView = {
  id: string
  provider: string
  method: string
  nonClinical: true
  requiresReview: boolean
  status: NerveDetectionStatus
  failure: { code: string, message: string } | null
  performedAt: string | null
  pathways: NervePathwayView[]
  proximities: NerveProximityView[]
  counts: { pathways: number, near: number, watch: number }
  review: {
    status: NerveReviewStatus
    at: string | null
    note: string | null
  }
  disclaimer: string
}

/** Raw pathway payload as returned by the nerve-detection API. */
export type NervePathwayPayload = {
  finding_id?: string | null
  side?: string | null
  region?: string | null
  source?: string | null
  status?: string | null
  confidence?: number | null
  reference_space?: {
    kind?: string | null
    unit?: string | null
    frame_of_reference_uid?: string | null
  } | null
  points?: Array<{ x?: number | null, y?: number | null, z?: number | null }> | null
  evidence?: {
    basis?: string | null
    note?: string | null
    backing_documents?: string[] | null
  } | null
}

/** Raw proximity payload as returned by the nerve-detection API. */
export type NerveProximityPayload = {
  tooth_number?: number | null
  side?: string | null
  distance_mm?: number | null
  closest_point_index?: number | null
  warning?: string | null
  confidence?: number | null
}

/** Raw analysis payload as returned by the nerve-detection API. */
export type NerveAnalysisPayload = {
  id: string
  provider: string
  method: string
  status?: string | null
  is_clinical?: boolean
  requires_review?: boolean
  failure?: { code?: string | null, message?: string | null } | null
  provenance?: {
    model_id?: string | null
    model_version?: string | null
    adapter?: string | null
    input_digest?: string | null
    study_instance_uid?: string | null
    series_instance_uid?: string | null
    frame_of_reference_uid?: string | null
  } | null
  pathways?: NervePathwayPayload[] | null
  proximities?: NerveProximityPayload[] | null
  performed_at?: string | null
  created_at?: string | null
  review_status?: string | null
  reviewed_at?: string | null
  review_note?: string | null
  disclaimer?: string | null
}

const VALID_SIDES: ReadonlySet<string> = new Set(['left', 'right'])
const VALID_PATHWAY_STATUSES: ReadonlySet<string> = new Set(['detected', 'uncertain'])
const VALID_WARNINGS: ReadonlySet<string> = new Set(['near', 'watch', 'none'])
const VALID_REVIEWS: ReadonlySet<string> = new Set(['pending', 'accepted', 'rejected', 'not_applicable'])
const VALID_OUTCOMES: ReadonlySet<string> = new Set(['detected', 'no_detection', 'uncertain', 'failed'])

function isFiniteConfidence(value: number): boolean {
  return Number.isFinite(value) && value >= 0 && value <= 1
}

function toPathwayView(payload: NervePathwayPayload): NervePathwayView | null {
  if (!VALID_SIDES.has(payload.side ?? '')) return null
  if (!VALID_PATHWAY_STATUSES.has(payload.status ?? '')) return null
  const confidence = Number(payload.confidence)
  if (!isFiniteConfidence(confidence)) return null
  const points: NervePointView[] = []
  for (const point of payload.points ?? []) {
    const x = Number(point?.x)
    const y = Number(point?.y)
    const z = Number(point?.z)
    if (Number.isFinite(x) && Number.isFinite(y) && Number.isFinite(z)) {
      points.push({ x, y, z })
    }
  }
  if (points.length < 2) return null // a single point is not a pathway
  return {
    side: payload.side as NerveSide,
    region: payload.region ?? 'mandibular_canal',
    source: payload.source ?? '',
    status: payload.status as NervePathwayStatus,
    confidence,
    referenceSpace: payload.reference_space?.kind === 'dicom_patient'
      ? 'dicom_patient'
      : 'canonical_arch',
    points,
    basis: payload.evidence?.basis ?? '',
    note: payload.evidence?.note ?? null,
    backingDocuments: payload.evidence?.backing_documents ?? []
  }
}

function isRenderableFdi(number: number): boolean {
  const quadrant = Math.trunc(number / 10)
  const units = number % 10
  return (
    Number.isInteger(number)
    && ((quadrant >= 1 && quadrant <= 4) || (quadrant >= 5 && quadrant <= 8))
    && units >= 1
    && units <= (quadrant >= 5 ? 5 : 8)
  )
}

function toProximityView(payload: NerveProximityPayload): NerveProximityView | null {
  const toothNumber = Number(payload.tooth_number)
  if (!isRenderableFdi(toothNumber)) return null
  if (!VALID_SIDES.has(payload.side ?? '')) return null
  if (!VALID_WARNINGS.has(payload.warning ?? '')) return null
  const distanceMm = Number(payload.distance_mm)
  const confidence = Number(payload.confidence)
  const closestPointIndex = Number(payload.closest_point_index)
  if (!Number.isFinite(distanceMm) || distanceMm < 0) return null
  if (!isFiniteConfidence(confidence)) return null
  if (!Number.isInteger(closestPointIndex) || closestPointIndex < 0) return null
  return {
    toothNumber,
    side: payload.side as NerveSide,
    distanceMm,
    closestPointIndex,
    warning: payload.warning as NerveProximityWarning,
    confidence
  }
}

/**
 * Normalize an API analysis payload for display; null when there is
 * nothing (yet) to show. Invalid pathway/proximity entries are dropped
 * — the UI never renders data it cannot trust, and never repairs it.
 */
export function toNerveView(payload: NerveAnalysisPayload | null | undefined): NerveAnalysisView | null {
  if (!payload || !payload.id) return null
  const pathways = (payload.pathways ?? [])
    .map(toPathwayView)
    .filter((p): p is NervePathwayView => p !== null)
    .sort((a, b) => a.side.localeCompare(b.side))
  const proximities = (payload.proximities ?? [])
    .map(toProximityView)
    .filter((p): p is NerveProximityView => p !== null)
    .sort((a, b) => a.toothNumber - b.toothNumber)
  const reviewStatus = VALID_REVIEWS.has(payload.review_status ?? '')
    ? (payload.review_status as NerveReviewStatus)
    : 'pending'
  return {
    id: payload.id,
    provider: payload.provider ?? '',
    method: payload.method ?? '',
    status: VALID_OUTCOMES.has(payload.status ?? '')
      ? payload.status as NerveDetectionStatus
      : 'uncertain',
    failure: payload.failure?.code && payload.failure?.message
      ? { code: payload.failure.code, message: payload.failure.message }
      : null,
    // Fixed safety markers — the backend schema cannot state otherwise.
    nonClinical: true,
    // Only an explicit operational failure is non-reviewable. A forged
    // ``requires_review: false`` cannot suppress review of anatomy output.
    requiresReview: payload.status === 'failed' ? false : true,
    performedAt: payload.performed_at ?? payload.created_at ?? null,
    pathways,
    proximities,
    counts: {
      pathways: pathways.length,
      near: proximities.filter(p => p.warning === 'near').length,
      watch: proximities.filter(p => p.warning === 'watch').length
    },
    review: {
      status: reviewStatus,
      at: payload.reviewed_at ?? null,
      note: payload.review_note ?? null
    },
    disclaimer:
      payload.disclaimer
      ?? 'AI-assisted / simulated nerve detection — non-clinical decision support; a dentist must verify.'
  }
}

/**
 * Overlay state for the viewer: pathways render on the synthetic arch
 * only — the canonical model's coordinates are meaningful in that
 * frame. Aligning a canonical pathway to real scan geometry would
 * pretend an alignment nobody has, so the viewer does not do it.
 */
export function nerveOverlayState(
  analysis: NerveAnalysisView | null,
  renderSynthetic: boolean,
  visible: boolean
): { show: boolean, pathways: NervePathwayView[] } {
  if (!analysis || !renderSynthetic || !visible) {
    return { show: false, pathways: [] }
  }
  const pathways = analysis.pathways.filter(pathway => pathway.referenceSpace === 'canonical_arch')
  return { show: pathways.length > 0, pathways }
}

/**
 * FDI join for proximity display: proximities keyed by tooth number,
 * restricted to teeth actually rendered (present + visible) so the UI
 * never lists a proximity for a tooth the scene does not show.
 */
export function proximityByTooth(
  analysis: NerveAnalysisView | null,
  renderableTeeth: readonly DentalToothView[]
): Map<number, NerveProximityView> {
  const states = new Map<number, NerveProximityView>()
  if (!analysis) return states
  const byNumber = new Map(analysis.proximities.map(p => [p.toothNumber, p]))
  for (const tooth of renderableTeeth) {
    const proximity = byNumber.get(tooth.tooth_number)
    if (proximity) states.set(tooth.tooth_number, proximity)
  }
  return states
}

/** Band a confidence value for display (mirrors backend thresholds). */
export function nerveConfidenceBand(confidence: number): ConfidenceBand {
  if (confidence >= CONFIDENCE_BAND_HIGH) return 'high'
  if (confidence >= CONFIDENCE_BAND_MEDIUM) return 'medium'
  return 'low'
}

/** Proximities in the ``near`` band — the dentist's review starting point. */
export function nearTeeth(analysis: NerveAnalysisView | null): NerveProximityView[] {
  return analysis ? analysis.proximities.filter(p => p.warning === 'near') : []
}

/** Proximities in the ``watch`` band. */
export function watchTeeth(analysis: NerveAnalysisView | null): NerveProximityView[] {
  return analysis ? analysis.proximities.filter(p => p.warning === 'watch') : []
}
