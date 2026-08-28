export type SimulatorArch = 'maxillary' | 'mandibular'
export type PreviewMode = 'before' | 'after' | 'overlay'

export interface CapabilityReason {
  code: string
  message: string
}

export interface SimulatorCapability {
  patient_id: string
  whole_arch_mesh_count: number
  per_tooth_mesh_count: number
  reviewed_per_tooth_mesh_count: number
  accepted_alignment: boolean
  translation_eligible: boolean
  rotation_eligible: boolean
  reasons: CapabilityReason[]
  clinical_prediction: false
  treatment_approval: false
}

export interface AuthoredMovementPayload {
  tooth: { value: string, system: 'FDI' }
  translate_x_mm: number
  translate_y_mm: number
  translate_z_mm: number
  rotate_tip_deg: number
  rotate_torque_deg: number
  rotate_rotation_deg: number
}

export interface ToothPosePayload {
  tooth: { value: string, system: 'FDI' }
  coordinate_frame: string
  translate_x_mm: number
  translate_y_mm: number
  translate_z_mm: number
  rotate_tip_deg: number
  rotate_torque_deg: number
  rotate_rotation_deg: number
  translation_renderable: boolean
  rotation_renderable: boolean
}

export interface SimulationResultPayload {
  stages: Array<{ index: number, deltas: unknown[] }>
  poses_by_stage: Array<Record<string, ToothPosePayload>>
  findings: Array<{ code: string, message: string, tooth?: string | null }>
  reproducibility_digest: string
  synthetic_geometry: false
  mutates_source_geometry: false
  clinical_prediction: false
  treatment_approval: false
}

export interface SimulationResponsePayload {
  capability: SimulatorCapability
  result: SimulationResultPayload
}

export interface SchematicTooth {
  fdi: string
  arch: SimulatorArch
  x: number
  y: number
  z: number
}

const UPPER = ['18', '17', '16', '15', '14', '13', '12', '11', '21', '22', '23', '24', '25', '26', '27', '28']
const LOWER = ['48', '47', '46', '45', '44', '43', '42', '41', '31', '32', '33', '34', '35', '36', '37', '38']

/**
 * Non-patient schematic arch used only for FDI selection/navigation.
 * Coordinates are arbitrary display units and must never be interpreted as anatomy.
 */
export function schematicTeeth(arch: SimulatorArch): SchematicTooth[] {
  const ids = arch === 'maxillary' ? UPPER : LOWER
  return ids.map((fdi, index) => {
    const t = index / (ids.length - 1)
    const angle = Math.PI * (0.12 + 0.76 * t)
    const radius = arch === 'maxillary' ? 7.2 : 6.6
    return {
      fdi,
      arch,
      x: -Math.cos(angle) * radius,
      y: Math.sin(angle) * radius - 4.2,
      z: 0
    }
  })
}

export function fdiArch(fdi: string): SimulatorArch {
  if (!/^[1-8][1-8]$/.test(fdi)) throw new Error(`invalid FDI tooth: ${fdi}`)
  return '1256'.includes(fdi[0]!) ? 'maxillary' : 'mandibular'
}

export function stageLabel(index: number, stageCount: number): string {
  if (!Number.isInteger(index) || index < 0) throw new Error('stage index must be non-negative')
  if (!Number.isInteger(stageCount) || stageCount < 0) throw new Error('stage count must be non-negative')
  if (stageCount === 0) return 'No staged simulation'
  return `Stage ${Math.min(index + 1, stageCount)} of ${stageCount}`
}

export function capabilityHeadline(capability: SimulatorCapability | null): string {
  if (!capability) return 'Checking patient geometry…'
  if (capability.translation_eligible) {
    return capability.rotation_eligible
      ? 'Reviewed per-tooth geometry is eligible for translation and rotation preview.'
      : 'Translation is eligible; rotation remains locked until trusted tooth-local frames exist.'
  }
  return 'Patient-specific tooth movement is locked by the geometry safety gate.'
}

export function movementPayload(
  fdi: string,
  values: {
    x: number
    y: number
    z: number
    tip: number
    torque: number
    rotation: number
  }
): AuthoredMovementPayload {
  if (!/^[1-8][1-8]$/.test(fdi)) throw new Error(`invalid FDI tooth: ${fdi}`)
  for (const value of Object.values(values)) {
    if (!Number.isFinite(value)) throw new Error('movement values must be finite')
  }
  return {
    tooth: { value: fdi, system: 'FDI' },
    translate_x_mm: values.x,
    translate_y_mm: values.y,
    translate_z_mm: values.z,
    rotate_tip_deg: values.tip,
    rotate_torque_deg: values.torque,
    rotate_rotation_deg: values.rotation
  }
}
