import { describe, expect, it } from 'vitest'
import {
  confidenceBand,
  overlayState,
  segmentationStates,
  toSegmentationView,
  uncertainTeeth,
  type SegmentationAnalysisPayload
} from '../../module_layers/dental_3d/frontend/lib/segmentationView'
import type { DentalToothView } from '../../module_layers/dental_3d/frontend/lib/dentalArch'

function analysis(overrides: Partial<SegmentationAnalysisPayload> = {}): SegmentationAnalysisPayload {
  return {
    id: 'a-1',
    patient_id: 'p-1',
    provider: 'arch-partition',
    method: 'deterministic-arch-partition-v0',
    is_clinical: false,
    requires_review: true,
    teeth: [
      {
        tooth_number: 11,
        status: 'segmented',
        confidence: 0.9,
        evidence: { basis: 'mesh_backed', arch_region: 'Q1-incisor', backing_documents: ['d-1'] }
      },
      { tooth_number: 16, status: 'uncertain', confidence: 0.5, evidence: { basis: 'odontogram_record', arch_region: 'Q1-molar' } },
      { tooth_number: 46, status: 'missing', confidence: 1.0, evidence: { basis: 'odontogram_record', arch_region: 'Q4-molar' } }
    ],
    performed_at: '2026-08-23T12:00:00Z',
    created_at: '2026-08-23T12:00:01Z',
    review_status: 'pending',
    reviewed_at: null,
    review_note: null,
    segmented_count: 1,
    uncertain_count: 1,
    missing_count: 1,
    disclaimer: 'Automatic tooth segmentation is non-clinical decision support.',
    ...overrides
  }
}

const RENDERABLE: DentalToothView[] = [
  { tooth_number: 11, present: true, visible: true, condition: 'healthy', color: null },
  { tooth_number: 16, present: true, visible: true, condition: 'crown', color: null },
  { tooth_number: 46, present: false, visible: true, condition: 'missing', color: null }
]

describe('toSegmentationView', () => {
  it('normalizes a full analysis payload', () => {
    const view = toSegmentationView(analysis())
    expect(view).not.toBeNull()
    expect(view!.id).toBe('a-1')
    expect(view!.provider).toBe('arch-partition')
    expect(view!.nonClinical).toBe(true)
    expect(view!.requiresReview).toBe(true)
    expect(view!.counts).toEqual({ segmented: 1, uncertain: 1, missing: 1 })
    expect(view!.review.status).toBe('pending')
  })

  it('safety markers are fixed regardless of payload claims', () => {
    // A hostile/buggy payload cannot flip the safety semantics.
    const view = toSegmentationView(analysis({ is_clinical: true, requires_review: false }))
    expect(view!.nonClinical).toBe(true)
    expect(view!.requiresReview).toBe(true)
  })

  it('null/undefined/empty payloads degrade to null', () => {
    expect(toSegmentationView(null)).toBeNull()
    expect(toSegmentationView(undefined)).toBeNull()
    expect(toSegmentationView({} as SegmentationAnalysisPayload)).toBeNull()
  })

  it('drops invalid teeth instead of repairing them', () => {
    const payload = analysis({
      teeth: [
        { tooth_number: 11, status: 'segmented', confidence: 0.9 },
        { tooth_number: 99, status: 'segmented', confidence: 0.9 },
        { tooth_number: 21, status: 'diagnosed', confidence: 0.9 },
        { tooth_number: 22, status: 'segmented', confidence: 1.5 }
      ]
    })
    const view = toSegmentationView(payload)
    expect(view!.teeth.map(t => t.toothNumber)).toEqual([11])
    expect(view!.counts).toEqual({ segmented: 1, uncertain: 0, missing: 0 })
  })

  it('sorts teeth by FDI number and mirrors evidence', () => {
    const view = toSegmentationView(
      analysis({
        teeth: [
          { tooth_number: 46, status: 'missing', confidence: 1 },
          { tooth_number: 16, status: 'uncertain', confidence: 0.5, evidence: { arch_region: 'Q1-molar', note: 'crown' } },
          { tooth_number: 11, status: 'segmented', confidence: 0.75 }
        ]
      })
    )
    expect(view!.teeth.map(t => t.toothNumber)).toEqual([11, 16, 46])
    expect(view!.teeth[1].archRegion).toBe('Q1-molar')
    expect(view!.teeth[1].note).toBe('crown')
  })

  it('falls back to a pending review state for unknown status', () => {
    const view = toSegmentationView(analysis({ review_status: 'final' as never }))
    expect(view!.review.status).toBe('pending')
  })
})

describe('segmentationStates — FDI join', () => {
  it('joins proposals onto rendered teeth by FDI number', () => {
    const view = toSegmentationView(analysis())
    const states = segmentationStates(view, RENDERABLE)
    expect([...states.keys()].sort((a, b) => a - b)).toEqual([11, 16])
    expect(states.get(16)!.status).toBe('uncertain')
  })

  it('missing proposals never overlay a rendered tooth', () => {
    // 46 is rendered as absent (missing) — its proposal must not label it.
    const view = toSegmentationView(analysis())
    expect(segmentationStates(view, RENDERABLE).has(46)).toBe(false)
  })

  it('returns an empty map without an analysis', () => {
    expect(segmentationStates(null, RENDERABLE).size).toBe(0)
  })
})

describe('confidenceBand', () => {
  it('bands confidence with the documented thresholds', () => {
    expect(confidenceBand(0.9)).toBe('high')
    expect(confidenceBand(0.8)).toBe('high')
    expect(confidenceBand(0.79)).toBe('medium')
    expect(confidenceBand(0.6)).toBe('medium')
    expect(confidenceBand(0.59)).toBe('low')
    expect(confidenceBand(0)).toBe('low')
  })
})

describe('uncertainTeeth', () => {
  it('lists uncertain proposals for the review starting point', () => {
    const view = toSegmentationView(analysis())
    expect(uncertainTeeth(view).map(t => t.toothNumber)).toEqual([16])
    expect(uncertainTeeth(null)).toEqual([])
  })
})

describe('overlayState — viewer integration contract', () => {
  it('shows labels on the synthetic arch when an analysis exists', () => {
    const view = toSegmentationView(analysis())
    const overlay = overlayState(view, true, RENDERABLE)
    expect(overlay.showLabels).toBe(true)
    expect(overlay.states.size).toBe(2)
  })

  it('hides labels when real scan geometry replaces the synthetic arch', () => {
    const view = toSegmentationView(analysis())
    const overlay = overlayState(view, false, RENDERABLE)
    expect(overlay.showLabels).toBe(false)
    expect(overlay.states.size).toBe(0)
  })

  it('hides labels without an analysis (Phase 1/2 behaviour unchanged)', () => {
    const overlay = overlayState(null, true, RENDERABLE)
    expect(overlay.showLabels).toBe(false)
  })
})
