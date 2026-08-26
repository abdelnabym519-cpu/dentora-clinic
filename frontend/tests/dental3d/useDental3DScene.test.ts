import { describe, expect, it } from 'vitest'
import {
  summarizeScene,
  toViewerTeeth,
  type DentalScenePayload
} from '../../module_layers/dental_3d/frontend/composables/useDental3DScene'

function scene(overrides: Partial<DentalScenePayload> = {}): DentalScenePayload {
  return {
    patient_id: 'p-1',
    generator: 'synthetic',
    persisted: false,
    teeth: [
      { tooth_number: 11, present: true, condition: 'healthy', color: null, visible: true },
      { tooth_number: 16, present: true, condition: 'caries', color: null, visible: true },
      { tooth_number: 46, present: false, condition: 'missing', color: null, visible: true },
      { tooth_number: 25, present: true, condition: 'crown', color: '#EF4444', visible: false }
    ],
    segmentation: { status: 'not_available' },
    ...overrides
  }
}

describe('toViewerTeeth', () => {
  it('drops absent and hidden teeth and sorts by FDI number', () => {
    const teeth = toViewerTeeth(scene())
    expect(teeth.map(t => t.tooth_number)).toEqual([11, 16])
  })

  it('returns an empty list when the scene failed to load', () => {
    expect(toViewerTeeth(null)).toEqual([])
  })
})

describe('summarizeScene', () => {
  it('counts rendered teeth and non-healthy findings', () => {
    expect(summarizeScene(scene())).toEqual({ rendered: 2, flagged: 1 })
  })

  it('degrades to zeros without a scene', () => {
    expect(summarizeScene(null)).toEqual({ rendered: 0, flagged: 0 })
  })
})
