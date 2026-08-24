import { describe, expect, it } from 'vitest'
import {
  nerveConfidenceBand,
  nerveOverlayState,
  nearTeeth,
  proximityByTooth,
  toNerveView,
  watchTeeth,
  type NerveAnalysisPayload
} from '../../module_layers/dental_3d/frontend/lib/nerveView'
import {
  renderableTeeth,
  type DentalToothView
} from '../../module_layers/dental_3d/frontend/lib/dentalArch'

function pathway(side: 'left' | 'right', overrides: Record<string, unknown> = {}) {
  return {
    side,
    region: 'mandibular_canal',
    source: 'canonical_demo_model',
    status: 'detected',
    confidence: 0.75,
    points: [
      { x: side === 'left' ? 2.65 : -2.65, y: -0.98, z: -1.85 },
      { x: side === 'left' ? 2.3 : -2.3, y: -0.84, z: -1.52 },
      { x: side === 'left' ? 2.02 : -2.02, y: -0.78, z: -1.02 }
    ],
    evidence: {
      basis: 'anatomical_model',
      note: 'canonical model',
      backing_documents: ['d-1']
    },
    ...overrides
  }
}

function proximity(tooth: number, overrides: Record<string, unknown> = {}) {
  return {
    tooth_number: tooth,
    side: tooth >= 31 && tooth <= 38 ? 'left' : 'right',
    distance_mm: 3.2,
    closest_point_index: 1,
    warning: 'watch',
    confidence: 0.75,
    ...overrides
  }
}

function analysis(overrides: Partial<NerveAnalysisPayload> = {}): NerveAnalysisPayload {
  return {
    id: 'n-1',
    patient_id: 'p-1',
    provider: 'canonical-mandible',
    method: 'canonical-mandible-model-v0',
    is_clinical: false,
    requires_review: true,
    pathways: [pathway('left'), pathway('right')],
    proximities: [
      proximity(38, { distance_mm: 1.53, warning: 'near', closest_point_index: 1 }),
      proximity(48, { distance_mm: 1.53, warning: 'near', closest_point_index: 1 }),
      proximity(35, { distance_mm: 3.09, warning: 'watch', closest_point_index: 4 }),
      proximity(31, { distance_mm: 10.37, warning: 'none', closest_point_index: 5 })
    ],
    performed_at: '2026-08-24T12:00:00Z',
    created_at: '2026-08-24T12:00:01Z',
    review_status: 'pending',
    reviewed_at: null,
    review_note: null,
    disclaimer: 'AI-assisted / simulated nerve detection — requires dentist verification.',
    ...overrides
  }
}

const RENDERABLE: DentalToothView[] = [
  { tooth_number: 38, present: true, visible: true, condition: 'healthy', color: null },
  { tooth_number: 48, present: true, visible: true, condition: 'healthy', color: null },
  { tooth_number: 35, present: true, visible: true, condition: 'crown', color: null },
  { tooth_number: 31, present: false, visible: true, condition: 'missing', color: null }
]

describe('toNerveView', () => {
  it('normalizes a full analysis payload', () => {
    const view = toNerveView(analysis())
    expect(view).not.toBeNull()
    expect(view!.provider).toBe('canonical-mandible')
    expect(view!.pathways.map(p => p.side)).toEqual(['left', 'right'])
    expect(view!.pathways[0].points).toHaveLength(3)
    expect(view!.counts).toEqual({ pathways: 2, near: 2, watch: 1 })
    expect(view!.proximities.map(p => p.toothNumber)).toEqual([31, 35, 38, 48])
    expect(view!.review.status).toBe('pending')
    expect(view!.disclaimer).toContain('simulated')
  })

  it('safety markers are fixed regardless of payload claims', () => {
    const view = toNerveView(analysis({ is_clinical: true, requires_review: false }))
    // Fixed markers — the backend schema cannot state otherwise, and
    // the projection never forwards a clinical claim.
    expect(view!.nonClinical).toBe(true)
    expect(view!.requiresReview).toBe(true)
  })

  it('null/undefined/empty payloads degrade to null', () => {
    expect(toNerveView(null)).toBeNull()
    expect(toNerveView(undefined)).toBeNull()
    expect(toNerveView({} as NerveAnalysisPayload)).toBeNull()
  })

  it('drops invalid pathways instead of repairing them', () => {
    const view = toNerveView(
      analysis({
        pathways: [
          pathway('left'),
          pathway('middle'), // invalid side
          pathway('right', { status: 'verified' }), // invalid status
          pathway('right', { confidence: 1.5 }), // out of bounds
          pathway('right', { points: [{ x: 1, y: 2, z: 3 }] }) // not a polyline
        ]
      })
    )
    expect(view!.pathways).toHaveLength(1)
    expect(view!.pathways[0].side).toBe('left')
  })

  it('drops invalid proximities instead of repairing them', () => {
    const view = toNerveView(
      analysis({
        proximities: [
          proximity(38),
          proximity(39), // invalid FDI
          proximity(48, { warning: 'unsafe' }), // not a band — never a clinical verdict
          proximity(47, { distance_mm: -1 }), // impossible distance
          proximity(46, { confidence: 2 }), // out of bounds
          proximity(45, { closest_point_index: -2 })
        ]
      })
    )
    expect(view!.proximities.map(p => p.toothNumber)).toEqual([38])
  })

  it('falls back to a pending review state for unknown status', () => {
    const view = toNerveView(analysis({ review_status: 'signed_off' }))
    expect(view!.review.status).toBe('pending')
  })

  it('mirrors evidence onto pathways', () => {
    const view = toNerveView(analysis())
    expect(view!.pathways[0].basis).toBe('anatomical_model')
    expect(view!.pathways[0].note).toBe('canonical model')
    expect(view!.pathways[0].backingDocuments).toEqual(['d-1'])
  })
})

describe('nerveOverlayState — viewer gating', () => {
  it('shows pathways on the synthetic arch when toggled on', () => {
    const state = nerveOverlayState(toNerveView(analysis()), true, true)
    expect(state.show).toBe(true)
    expect(state.pathways).toHaveLength(2)
  })

  it('never overlays a canonical pathway on real scan geometry', () => {
    const state = nerveOverlayState(toNerveView(analysis()), false, true)
    expect(state.show).toBe(false)
    expect(state.pathways).toHaveLength(0)
  })

  it('never overlays native DICOM findings on the unaligned synthetic arch', () => {
    const native = analysis({
      pathways: [pathway('left', { reference_space: { kind: 'dicom_patient' } })]
    })
    const state = nerveOverlayState(toNerveView(native), true, true)
    expect(state.show).toBe(false)
    expect(state.pathways).toEqual([])
  })

  it('respects the visibility toggle', () => {
    const state = nerveOverlayState(toNerveView(analysis()), true, false)
    expect(state.show).toBe(false)
  })

  it('empty without an analysis', () => {
    expect(nerveOverlayState(null, true, true).show).toBe(false)
  })
})

describe('proximityByTooth — FDI join', () => {
  it('joins proximities onto rendered teeth by FDI number', () => {
    const map = proximityByTooth(toNerveView(analysis()), renderableTeeth(RENDERABLE))
    expect([...map.keys()].sort((a, b) => a - b)).toEqual([35, 38, 48])
  })

  it('never lists a proximity for a tooth the scene does not render', () => {
    const map = proximityByTooth(toNerveView(analysis()), renderableTeeth(RENDERABLE))
    expect(map.has(31)).toBe(false) // absent tooth
  })

  it('returns an empty map without an analysis', () => {
    expect(proximityByTooth(null, renderableTeeth(RENDERABLE)).size).toBe(0)
  })
})

describe('nerveConfidenceBand', () => {
  it('bands confidence with the documented thresholds', () => {
    expect(nerveConfidenceBand(0.9)).toBe('high')
    expect(nerveConfidenceBand(0.8)).toBe('high')
    expect(nerveConfidenceBand(0.75)).toBe('medium')
    expect(nerveConfidenceBand(0.6)).toBe('medium')
    expect(nerveConfidenceBand(0.3)).toBe('low')
  })
})

describe('nearTeeth / watchTeeth — review starting points', () => {
  it('lists near and watch proximities', () => {
    const view = toNerveView(analysis())
    expect(nearTeeth(view).map(p => p.toothNumber)).toEqual([38, 48])
    expect(watchTeeth(view).map(p => p.toothNumber)).toEqual([35])
    expect(nearTeeth(null)).toEqual([])
    expect(watchTeeth(null)).toEqual([])
  })
})
