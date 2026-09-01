/**
 * segmentationView — pure projection of segmentation analyses to views.
 *
 * Framework-free seam (ADR 0019 / ADR 0021): the backend speaks
 * ``SegmentationAnalysisResponse`` descriptors (``segmentation.py``);
 * the card and viewer want normalized view models. This module is the
 * pure translation — no three.js, no Vue, no fetching — so it stays
 * unit-testable, mirroring ``dentalArch.ts`` / ``sceneMeshes.ts``.
 *
 * Safety invariants mirrored from the backend contracts: analyses are
 * **non-clinical decision support** (``nonClinical: true`` is the only
 * representable state) and always **require dentist review**. The
 * projection never invents statuses, confidences or teeth — invalid
 * entries are dropped, never repaired.
 */

import type { DentalToothView } from './dentalArch'

export type SegmentedToothStatus = 'segmented' | 'uncertain' | 'missing'

export type SegmentationReviewStatus = 'pending' | 'accepted' | 'rejected'

export type ConfidenceBand = 'high' | 'medium' | 'low'

/** Confidence bands — mirrors backend thresholds (ADR 0021). */
export const CONFIDENCE_BAND_HIGH = 0.8
export const CONFIDENCE_BAND_MEDIUM = 0.6

/** One tooth-level proposal, normalized for display. */
export type SegmentedToothView = {
  toothNumber: number
  status: SegmentedToothStatus
  confidence: number
  archRegion: string
  basis: string
  note: string | null
  backingDocuments: string[]
}

/** A whole analysis, normalized for the card + viewer overlays. */
export type SegmentationAnalysisView = {
  id: string
  provider: string
  method: string
  nonClinical: true
  requiresReview: true
  performedAt: string | null
  teeth: SegmentedToothView[]
  counts: { segmented: number, uncertain: number, missing: number }
  review: {
    status: SegmentationReviewStatus
    at: string | null
    note: string | null
  }
  disclaimer: string
}

/** Raw tooth payload as returned by the segmentation API. */
export type SegmentationToothPayload = {
  tooth_number: number
  status: string
  confidence: number
  evidence?: {
    basis?: string | null
    arch_region?: string | null
    backing_documents?: string[] | null
    note?: string | null
  } | null
}

/** Raw analysis payload as returned by the segmentation API. */
export type SegmentationAnalysisPayload = {
  id: string
  provider: string
  method: string
  is_clinical?: boolean
  requires_review?: boolean
  teeth?: SegmentationToothPayload[] | null
  performed_at?: string | null
  created_at?: string | null
  review_status?: string | null
  reviewed_at?: string | null
  review_note?: string | null
  segmented_count?: number
  uncertain_count?: number
  missing_count?: number
  disclaimer?: string | null
}

const VALID_STATUSES: ReadonlySet<string> = new Set(['segmented', 'uncertain', 'missing'])
const VALID_REVIEWS: ReadonlySet<string> = new Set(['pending', 'accepted', 'rejected'])

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

function toToothView(payload: SegmentationToothPayload): SegmentedToothView | null {
  if (!VALID_STATUSES.has(payload.status)) return null
  if (!isRenderableFdi(payload.tooth_number)) return null
  const confidence = Number(payload.confidence)
  if (!Number.isFinite(confidence) || confidence < 0 || confidence > 1) return null
  return {
    toothNumber: payload.tooth_number,
    status: payload.status as SegmentedToothStatus,
    confidence,
    archRegion: payload.evidence?.arch_region ?? '',
    basis: payload.evidence?.basis ?? '',
    note: payload.evidence?.note ?? null,
    backingDocuments: payload.evidence?.backing_documents ?? []
  }
}

/**
 * Normalize an API analysis payload for display; null when there is
 * nothing (yet) to show. Invalid tooth entries are dropped — the UI
 * never renders data it cannot trust, and never repairs it either.
 */
export function toSegmentationView(
  payload: SegmentationAnalysisPayload | null | undefined
): SegmentationAnalysisView | null {
  if (!payload || !payload.id) return null
  const teeth = (payload.teeth ?? [])
    .map(toToothView)
    .filter((t): t is SegmentedToothView => t !== null)
    .sort((a, b) => a.toothNumber - b.toothNumber)
  const reviewStatus = VALID_REVIEWS.has(payload.review_status ?? '')
    ? (payload.review_status as SegmentationReviewStatus)
    : 'pending'
  return {
    id: payload.id,
    provider: payload.provider ?? '',
    method: payload.method ?? '',
    // Fixed safety markers — the backend schema cannot state otherwise.
    nonClinical: true,
    requiresReview: true,
    performedAt: payload.performed_at ?? payload.created_at ?? null,
    teeth,
    counts: {
      segmented: teeth.filter(t => t.status === 'segmented').length,
      uncertain: teeth.filter(t => t.status === 'uncertain').length,
      missing: teeth.filter(t => t.status === 'missing').length
    },
    review: {
      status: reviewStatus,
      at: payload.reviewed_at ?? null,
      note: payload.review_note ?? null
    },
    disclaimer:
      payload.disclaimer
      ?? 'Automatic tooth segmentation is non-clinical decision support; a dentist must review and decide.'
  }
}

/**
 * FDI join for the viewer: segmentation states keyed by tooth number,
 * restricted to the teeth actually being rendered (``renderableTeeth``
 * — present + visible). Teeth without a proposal are simply absent
 * from the map (rendered without overlay).
 */
export function segmentationStates(
  analysis: SegmentationAnalysisView | null,
  renderableTeeth: readonly DentalToothView[]
): Map<number, SegmentedToothView> {
  const states = new Map<number, SegmentedToothView>()
  if (!analysis) return states
  const byNumber = new Map(analysis.teeth.map(t => [t.toothNumber, t]))
  for (const tooth of renderableTeeth) {
    const state = byNumber.get(tooth.tooth_number)
    if (state && state.status !== 'missing') {
      states.set(tooth.tooth_number, state)
    }
  }
  return states
}

/** Band a confidence value for display (mirrors backend thresholds). */
export function confidenceBand(confidence: number): ConfidenceBand {
  if (confidence >= CONFIDENCE_BAND_HIGH) return 'high'
  if (confidence >= CONFIDENCE_BAND_MEDIUM) return 'medium'
  return 'low'
}

/** Uncertain proposals — the dentist's review starting point. */
export function uncertainTeeth(analysis: SegmentationAnalysisView | null): SegmentedToothView[] {
  return analysis ? analysis.teeth.filter(t => t.status === 'uncertain') : []
}

/**
 * Overlay state for the viewer: labels render on the synthetic arch
 * only — per-tooth alignment to real scan geometry arrives with a real
 * segmentation model (Phase 4+), never guessed here.
 */
export function overlayState(
  analysis: SegmentationAnalysisView | null,
  renderSynthetic: boolean,
  renderableTeeth: readonly DentalToothView[]
): { showLabels: boolean, states: Map<number, SegmentedToothView> } {
  if (!analysis || !renderSynthetic) {
    return { showLabels: false, states: new Map<number, SegmentedToothView>() }
  }
  return {
    showLabels: analysis.teeth.length > 0,
    states: segmentationStates(analysis, renderableTeeth)
  }
}
