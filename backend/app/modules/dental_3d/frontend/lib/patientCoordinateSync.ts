import type { PatientPointMm, PatientReferenceSpace } from './clinicalScene'
import { finitePatientPoint } from './patientMeasurements'

export interface PatientCoordinateEvent {
  frameOfReferenceUid: string
  unit: 'mm'
  point: PatientPointMm
}

export function synchronizePatientPoint(
  event: PatientCoordinateEvent,
  target: PatientReferenceSpace
): PatientPointMm | null {
  if (event.unit !== 'mm' || event.frameOfReferenceUid !== target.frameOfReferenceUid) return null
  return finitePatientPoint(event.point) ? event.point : null
}
