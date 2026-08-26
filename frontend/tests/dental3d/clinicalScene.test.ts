import { describe, expect, it } from 'vitest'
import { AiOverlayRegistry, registryFromClinicalScene } from '../../module_layers/dental_3d/frontend/lib/aiOverlayRegistry'
import {
  buildClinicalScene,
  validRigidMatrix,
  type AlignmentPayload,
  type ClinicalScenePayload
} from '../../module_layers/dental_3d/frontend/lib/clinicalScene'
import { synchronizePatientPoint } from '../../module_layers/dental_3d/frontend/lib/patientCoordinateSync'
import { distanceMm, measurementFromLandmarks } from '../../module_layers/dental_3d/frontend/lib/patientMeasurements'
import type { NerveAnalysisPayload } from '../../module_layers/dental_3d/frontend/lib/nerveView'

const FRAME_UID = '1.2.826.0.1.3680043.10.543.1'
const IDENTITY = [
  [1, 0, 0, 12],
  [0, 1, 0, -4],
  [0, 0, 1, 8],
  [0, 0, 0, 1]
]

function scene(): ClinicalScenePayload {
  return {
    patient_id: 'patient-1',
    meshes: [
      {
        source: 'intraoral_scan',
        format: 'ply',
        document_id: 'ios-1',
        label: 'IOS',
        url: '/api/v1/media/documents/ios-1/download'
      },
      {
        source: 'segmentation',
        format: 'stl',
        document_id: 'mandible-1',
        label: 'Mandible',
        url: '/api/v1/media/documents/mandible-1/download',
        anatomy_kind: 'mandible',
        reference_space: {
          kind: 'dicom_patient',
          unit: 'mm',
          frame_of_reference_uid: FRAME_UID
        },
        provenance: {
          identifier: 'segmentator-output-1',
          digest: `sha256:${'a'.repeat(64)}`,
          model_id: 'DentalSegmentator',
          model_version: '1'
        }
      }
    ],
    cbct_series: [{
      study_instance_uid: '1.2.3',
      series_instance_uid: '1.2.3.4',
      frame_of_reference_uid: FRAME_UID,
      document_ids: ['dicom-1', 'dicom-2'],
      instance_count: 2
    }]
  }
}

function alignment(overrides: Partial<AlignmentPayload> = {}): AlignmentPayload {
  return {
    id: 'alignment-1',
    status: 'accepted',
    transform: { matrix: IDENTITY },
    source_frame: { kind: 'ios_mesh', unit: 'mm' },
    target_frame: {
      kind: 'dicom_patient',
      unit: 'mm',
      frame_of_reference_uid: FRAME_UID
    },
    algorithm: 'open3d-ransac-icp',
    algorithm_version: '1',
    provenance: {
      ios: {
        identifier: 'ios-1',
        digest: `sha256:${'b'.repeat(64)}`,
        document_ids: ['ios-1']
      },
      anatomy_model_id: 'DentalSegmentator',
      anatomy_model_version: '1'
    },
    reviewed_at: '2026-08-25T12:00:00Z',
    ...overrides
  }
}

function nerve(): NerveAnalysisPayload {
  return {
    id: 'nerve-1',
    provider: 'cbct-model-service',
    method: 'DentalSegmentator',
    status: 'detected',
    review_status: 'pending',
    requires_review: true,
    is_clinical: false,
    pathways: [{
      finding_id: 'left-canal',
      side: 'left',
      region: 'mandibular_canal',
      source: 'model_inference',
      status: 'detected',
      confidence: 0.82,
      reference_space: {
        kind: 'dicom_patient',
        unit: 'mm',
        frame_of_reference_uid: FRAME_UID
      },
      points: [{ x: 10, y: 20, z: 30 }, { x: 11, y: 22, z: 33 }],
      evidence: { basis: 'cbct_inference', backing_documents: ['dicom-1'] }
    }],
    provenance: {
      model_id: 'DentalSegmentator',
      model_version: '1',
      input_digest: `sha256:${'c'.repeat(64)}`,
      frame_of_reference_uid: FRAME_UID
    }
  }
}

describe('ClinicalScene patient-space safety', () => {
  it('preserves the accepted server transform and native mm coordinates verbatim', () => {
    const result = buildClinicalScene(scene(), alignment(), nerve())
    expect(result?.frame).toEqual({ kind: 'dicom_patient', unit: 'mm', frameOfReferenceUid: FRAME_UID })
    expect(result?.geometry.find(layer => layer.kind === 'ios_surface')?.patientTransform).toEqual(IDENTITY)
    expect(result?.geometry.find(layer => layer.kind === 'mandible')?.patientTransform).toEqual([
      [1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]
    ])
    expect(result?.nerves[0]?.points[0]).toEqual({ x: 10, y: 20, z: 30 })
  })

  it('never renders IOS without a dentist-accepted alignment', () => {
    const result = buildClinicalScene(scene(), alignment({ status: 'pending_review' }), nerve())
    expect(result?.geometry.some(layer => layer.kind === 'ios_surface')).toBe(false)
    expect(result?.blockers).toContain('alignment_not_accepted_or_frame_mismatch')
  })

  it('never renders an alignment or overlay from a different patient frame', () => {
    const result = buildClinicalScene(scene(), alignment({
      target_frame: { kind: 'dicom_patient', unit: 'mm', frame_of_reference_uid: '9.9.9' }
    }), {
      ...nerve(),
      pathways: [{
        ...nerve().pathways![0]!,
        reference_space: { kind: 'dicom_patient', unit: 'mm', frame_of_reference_uid: '9.9.9' }
      }]
    })
    expect(result).toBeNull()
  })

  it('drops anatomy without explicit patient-space provenance', () => {
    const payload = scene()
    payload.meshes![1]!.provenance = null
    const result = buildClinicalScene(payload, alignment(), nerve())
    expect(result?.geometry.some(layer => layer.kind === 'mandible')).toBe(false)
  })

  it('rejects non-rigid matrices', () => {
    expect(validRigidMatrix([[2, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])).toBeNull()
  })
})

describe('patient-space tools', () => {
  it('measures only two explicit landmarks in millimetres', () => {
    expect(distanceMm({ x: 0, y: 0, z: 0 }, { x: 3, y: 4, z: 12 })).toBe(13)
    expect(measurementFromLandmarks(null, { x: 1, y: 1, z: 1 }, 'm')).toBeNull()
    expect(measurementFromLandmarks({ x: 0, y: 0, z: 0 }, { x: 0, y: 0, z: 2 }, 'm')?.distanceMm).toBe(2)
  })

  it('synchronizes only matching DICOM patient frames', () => {
    const target = { kind: 'dicom_patient' as const, unit: 'mm' as const, frameOfReferenceUid: FRAME_UID }
    expect(synchronizePatientPoint({ frameOfReferenceUid: FRAME_UID, unit: 'mm', point: { x: 1, y: 2, z: 3 } }, target)).toEqual({ x: 1, y: 2, z: 3 })
    expect(synchronizePatientPoint({ frameOfReferenceUid: '9.9.9', unit: 'mm', point: { x: 1, y: 2, z: 3 } }, target)).toBeNull()
  })
})

describe('AI overlay registry', () => {
  it('registers current real overlays and rejects mismatched or rejected additions', () => {
    const clinical = buildClinicalScene(scene(), alignment(), nerve())!
    expect(registryFromClinicalScene(clinical).list('mandibular_nerve')).toHaveLength(1)
    const registry = new AiOverlayRegistry(clinical.frame)
    expect(registry.register({
      id: 'future-overlay',
      type: 'future-ai',
      frame: { ...clinical.frame, frameOfReferenceUid: '9.9.9' },
      reviewStatus: 'pending',
      provenanceId: 'p',
      visible: true,
      data: {}
    })).toBe(false)
    expect(registry.register({
      id: 'rejected-overlay',
      type: 'future-ai',
      frame: clinical.frame,
      reviewStatus: 'rejected',
      provenanceId: 'p',
      visible: true,
      data: {}
    })).toBe(false)
  })
})
