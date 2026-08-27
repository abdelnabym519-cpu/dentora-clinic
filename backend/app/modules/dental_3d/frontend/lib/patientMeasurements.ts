import type { PatientPointMm } from './clinicalScene'

export interface PatientMeasurement {
  id: string
  start: PatientPointMm
  end: PatientPointMm
  distanceMm: number
}

export function distanceMm(start: PatientPointMm, end: PatientPointMm): number {
  return Math.hypot(end.x - start.x, end.y - start.y, end.z - start.z)
}

/** Measurements only exist between two explicit user-picked patient points. */
export function measurementFromLandmarks(
  start: PatientPointMm | null,
  end: PatientPointMm | null,
  id: string
): PatientMeasurement | null {
  if (!start || !end) return null
  const distance = distanceMm(start, end)
  if (!Number.isFinite(distance)) return null
  return { id, start, end, distanceMm: distance }
}

export function finitePatientPoint(point: PatientPointMm): boolean {
  return Number.isFinite(point.x) && Number.isFinite(point.y) && Number.isFinite(point.z)
}
