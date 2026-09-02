import { describe, expect, it } from 'vitest'
import {
  capabilityHeadline,
  fdiArch,
  movementPayload,
  schematicTeeth,
  stageLabel,
  type SimulatorCapability
} from '../../module_layers/orthodontic_simulator/frontend/lib/simulator'

function capability(overrides: Partial<SimulatorCapability> = {}): SimulatorCapability {
  return {
    patient_id: 'patient-1',
    whole_arch_mesh_count: 1,
    per_tooth_mesh_count: 0,
    reviewed_per_tooth_mesh_count: 0,
    accepted_alignment: false,
    translation_eligible: false,
    rotation_eligible: false,
    reasons: [],
    clinical_prediction: false,
    treatment_approval: false,
    ...overrides
  }
}

describe('orthodontic simulator frontend domain', () => {
  it('builds stable schematic FDI selectors without claiming patient anatomy', () => {
    const upper = schematicTeeth('maxillary')
    const lower = schematicTeeth('mandibular')

    expect(upper).toHaveLength(16)
    expect(lower).toHaveLength(16)
    expect(new Set([...upper, ...lower].map(tooth => tooth.fdi)).size).toBe(32)
    expect(upper.every(tooth => tooth.arch === 'maxillary')).toBe(true)
    expect(lower.every(tooth => tooth.arch === 'mandibular')).toBe(true)
  })

  it('resolves FDI arch and rejects invalid identities', () => {
    expect(fdiArch('11')).toBe('maxillary')
    expect(fdiArch('36')).toBe('mandibular')
    expect(() => fdiArch('99')).toThrow(/invalid FDI/i)
  })

  it('reports stage labels deterministically', () => {
    expect(stageLabel(0, 0)).toBe('No staged simulation')
    expect(stageLabel(0, 3)).toBe('Stage 1 of 3')
    expect(stageLabel(9, 3)).toBe('Stage 3 of 3')
    expect(() => stageLabel(-1, 2)).toThrow()
  })

  it('keeps the current patient locked when per-tooth geometry is missing', () => {
    expect(capabilityHeadline(capability())).toMatch(/locked by the geometry safety gate/i)
    expect(capabilityHeadline(capability({ translation_eligible: true }))).toMatch(/translation is eligible/i)
  })

  it('creates finite client-authored movement only and carries no geometry identifiers', () => {
    const payload = movementPayload('11', { x: 0.2, y: 0, z: 0, tip: 0, torque: 0, rotation: 0 })
    expect(payload.tooth).toEqual({ value: '11', system: 'FDI' })
    expect(payload.translate_x_mm).toBe(0.2)
    expect(payload).not.toHaveProperty('document_id')
    expect(payload).not.toHaveProperty('coordinate_frame')
    expect(() => movementPayload('11', { x: Number.NaN, y: 0, z: 0, tip: 0, torque: 0, rotation: 0 })).toThrow(/finite/i)
  })
})
