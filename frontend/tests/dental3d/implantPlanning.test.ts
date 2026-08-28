import { describe, expect, it } from 'vitest'
import type { ClinicalScene } from '../../module_layers/dental_3d/frontend/lib/clinicalScene'
import {
  withImplantPlanning
} from '../../module_layers/dental_3d/frontend/lib/implantScene'
import type {
  ImplantPlanningPayload,
  ImplantPlanPayload
} from '../../module_layers/dental_3d/frontend/composables/useDental3DImplantPlanning'

const FRAME = '2.25.123'

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

function check(value: number | null, unit = 'mm') {
  return value === null
    ? { status: 'UNAVAILABLE' as const, value: null, unit, semantics: 'fixture' }
    : { status: 'AVAILABLE' as const, value, unit, semantics: 'fixture' }
}

function plan(status: ImplantPlanPayload['status'] = 'draft', frame = FRAME): ImplantPlanPayload {
  return {
    id: 'plan-1',
    patient_id: 'patient-1',
    status,
    current_revision: {
      id: 'revision-1',
      plan_id: 'plan-1',
      revision_number: 2,
      candidate: {
        center: { x: 10, y: 20, z: 30 },
        axis: { x: 0, y: 0, z: 1 },
        diameter_mm: 4,
        length_mm: 10,
        frame_of_reference_uid: frame,
        unit: 'mm',
        dimension_source: 'explicit'
      },
      assessment: {
        prosthetic_offset_mm: check(0),
        prosthetic_axis_angle_deg: check(0, 'deg'),
        nerve_surface_to_centerline_mm: check(3),
        bone_axis_span_mm: check(null),
        bone_width_1_mm: check(null),
        bone_width_2_mm: check(null),
        bone_contained_fraction: check(null, 'ratio'),
        bone_contained_volume_mm3: check(null, 'mm3'),
        intersects_nerve_centerline: false,
        clinical_threshold_status: 'NO_CLINICAL_THRESHOLD_DEFINED'
      },
      planning_case: {
        frame_of_reference_uid: frame,
        alignment_id: 'alignment-1',
        prosthetic_target_id: 'target-1',
        prosthetic_status: 'accepted',
        nerve_analysis_id: 'nerve-1',
        bone_volume_status: 'UNAVAILABLE'
      }
    },
    requires_review: true,
    is_clinical: false,
    disclaimer: 'Engineering implant-planning decision support only; dentist approval is required.'
  }
}

function planning(planValue: ImplantPlanPayload): ImplantPlanningPayload {
  return {
    prosthetic: {
      status: 'available',
      target: {
        id: 'target-1',
        patient_id: 'patient-1',
        alignment_id: 'alignment-1',
        platform_center: { x: 10, y: 20, z: 25 },
        axis: { x: 0, y: 0, z: 1 },
        frame_of_reference_uid: FRAME,
        source_type: 'dentist_defined',
        source_reference_space: 'dicom_patient',
        source_frame_of_reference_uid: FRAME,
        source_method: 'explicit',
        source_identifier: 'target',
        source_document_ids: [],
        review_status: 'accepted'
      }
    },
    latest_target: {
      id: 'target-1',
      patient_id: 'patient-1',
      alignment_id: 'alignment-1',
      platform_center: { x: 10, y: 20, z: 25 },
      axis: { x: 0, y: 0, z: 1 },
      frame_of_reference_uid: FRAME,
      source_type: 'dentist_defined',
      source_reference_space: 'dicom_patient',
      source_frame_of_reference_uid: FRAME,
      source_method: 'explicit',
      source_identifier: 'target',
      source_document_ids: [],
      review_status: 'accepted'
    },
    plans: [planValue]
  }
}

describe('implant planning patient-space overlay contract', () => {
  it('preserves server-owned implant and prosthetic coordinates verbatim', () => {
    const result = withImplantPlanning(clinical(), planning(plan()))!
    expect(result.implants).toHaveLength(1)
    expect(result.implants[0]?.center).toEqual({ x: 10, y: 20, z: 30 })
    expect(result.implants[0]?.axis).toEqual({ x: 0, y: 0, z: 1 })
    expect(result.implants[0]?.diameterMm).toBe(4)
    expect(result.implants[0]?.lengthMm).toBe(10)
    expect(result.prostheticTargets[0]?.center).toEqual({ x: 10, y: 20, z: 25 })
  })

  it('does not register rejected plans', () => {
    const result = withImplantPlanning(clinical(), planning(plan('rejected')))!
    expect(result.implants).toEqual([])
  })

  it('does not register a plan from another DICOM patient frame', () => {
    const result = withImplantPlanning(clinical(), planning(plan('draft', '9.9.9')))!
    expect(result.implants).toEqual([])
  })

  it('does not normalize or repair an invalid server axis in the renderer', () => {
    const payload = planning(plan())
    payload.plans[0]!.current_revision.candidate.axis = { x: 0, y: 0, z: 2 }
    const result = withImplantPlanning(clinical(), payload)!
    expect(result.implants).toEqual([])
  })
})
