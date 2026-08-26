import { describe, expect, it } from 'vitest'
import type { ClinicalScene } from '../../module_layers/dental_3d/frontend/lib/clinicalScene'
import { riskRegionsOf, withRiskMap } from '../../module_layers/dental_3d/frontend/lib/riskMap'
import type { RiskResultPayload } from '../../module_layers/dental_3d/frontend/composables/useRiskEngine'

const FRAME = '2.25.9001'

function clinical(): ClinicalScene {
  const frame = { kind: 'dicom_patient' as const, unit: 'mm' as const, frameOfReferenceUid: FRAME }
  return {
    contract: 'dentora-clinical-scene-v1',
    patientId: 'patient-1',
    frame,
    geometry: [],
    nerves: [],
    cbct: {
      studyInstanceUid: '1.2.3',
      seriesInstanceUid: '1.2.3.4',
      frame,
      imageUrls: ['/dicom/1'],
      instanceCount: 1
    },
    alignment: {
      id: 'alignment-1',
      status: 'accepted',
      algorithm: 'fixture',
      algorithmVersion: '1',
      reviewedAt: null,
      reviewNote: null
    },
    blockers: []
  }
}

function result(frame = FRAME): RiskResultPayload {
  return {
    id: 'risk-1',
    patient_id: 'patient-1',
    result_version: 1,
    contract_version: '1.0',
    factors: [],
    evidence: [],
    risk_map: {
      status: 'available',
      frame: { kind: 'dicom_patient', unit: 'mm', frame_of_reference_uid: frame },
      regions: [
        {
          region_id: 'nerve-1',
          kind: 'polyline',
          display_band: 'evidence_present',
          factor_ids: ['accepted_nerve_pathway_present'],
          evidence_ids: ['E001'],
          points: [{ x: 1, y: 2, z: 3 }, { x: 4, y: 5, z: 6 }]
        },
        {
          region_id: 'implant-1',
          kind: 'cylinder',
          display_band: 'evidence_absent',
          factor_ids: ['accepted_implant_intersects_accepted_nerve_centerline'],
          evidence_ids: ['E002'],
          points: [],
          center: { x: 8, y: 9, z: 10 },
          axis: { x: 0, y: 0, z: 1 },
          radius_mm: 2,
          length_mm: 10
        }
      ],
      advisory_only: true,
      synthetic_geometry: false
    },
    provenance: {
      case_snapshot_version: 2,
      case_snapshot_contract_version: '1.0',
      source_digest: `sha256:${'a'.repeat(64)}`,
      input_digest: `sha256:${'b'.repeat(64)}`,
      result_digest: `sha256:${'c'.repeat(64)}`,
      engine_version: '1.0.0',
      policy_version: 'observed-facts-v1',
      generated_at: '2026-08-25T12:00:00Z',
      availability_state: 'available'
    },
    review_status: 'pending_review',
    advisory_only: true,
    requires_review: true,
    is_clinical: false,
    disclaimer: 'Observed-fact decision support only; no diagnosis, risk score, or validated clinical threshold.'
  }
}

describe('3D Risk Map patient-space gating', () => {
  it('preserves server patient-space regions and evidence links', () => {
    const scene = withRiskMap(clinical(), result())!
    const regions = riskRegionsOf(scene)
    expect(regions).toHaveLength(2)
    expect(regions[0]?.points).toEqual([{ x: 1, y: 2, z: 3 }, { x: 4, y: 5, z: 6 }])
    expect(regions[0]?.factorIds).toEqual(['accepted_nerve_pathway_present'])
    expect(regions[1]?.center).toEqual({ x: 8, y: 9, z: 10 })
    expect(regions.every(region => region.frame.frameOfReferenceUid === FRAME)).toBe(true)
  })

  it('fails closed on DICOM patient frame mismatch', () => {
    const scene = withRiskMap(clinical(), result('9.9.9'))!
    expect(riskRegionsOf(scene)).toEqual([])
  })

  it('never manufactures geometry for an unavailable map', () => {
    const payload = result()
    payload.risk_map = {
      status: 'unavailable',
      regions: [],
      reason: 'validated_anatomy_not_available',
      advisory_only: true,
      synthetic_geometry: false
    }
    const scene = withRiskMap(clinical(), payload)!
    expect(riskRegionsOf(scene)).toEqual([])
  })

  it('does not render rejected Risk Engine output', () => {
    const payload = result()
    payload.review_status = 'rejected'
    const scene = withRiskMap(clinical(), payload)!
    expect(riskRegionsOf(scene)).toEqual([])
  })

  it('rejects invalid geometry instead of normalizing or repairing it', () => {
    const payload = result()
    payload.risk_map.regions[1]!.axis = { x: 0, y: 0, z: 2 }
    const scene = withRiskMap(clinical(), payload)!
    expect(riskRegionsOf(scene)).toHaveLength(1)
    expect(riskRegionsOf(scene)[0]?.kind).toBe('polyline')
  })
})
