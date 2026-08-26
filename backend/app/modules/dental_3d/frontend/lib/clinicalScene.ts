/** Patient-space presentation contract for ThreeUI.
 *
 * The browser only composes server-issued artifacts. It never registers,
 * recentres, rescales, repairs, or fabricates clinical geometry.
 */

import type { NerveAnalysisPayload } from './nerveView'

export type PatientPointMm = Readonly<{ x: number, y: number, z: number }>
export type Matrix4Rows = readonly [
  readonly [number, number, number, number],
  readonly [number, number, number, number],
  readonly [number, number, number, number],
  readonly [number, number, number, number]
]

export type PatientReferenceSpace = Readonly<{
  kind: 'dicom_patient'
  unit: 'mm'
  frameOfReferenceUid: string
}>

export type ClinicalGeometryKind = 'ios_surface' | 'anatomy' | 'tooth' | 'mandible'
export type ClinicalMeshFormat = 'stl' | 'ply' | 'obj'
export type ReviewStatus = 'pending' | 'accepted' | 'rejected' | 'not_applicable'

export interface ClinicalProvenance {
  source: string
  identifier: string
  digest: string | null
  modelId: string | null
  modelVersion: string | null
  performedAt: string | null
}

export interface ClinicalGeometryLayer {
  id: string
  kind: ClinicalGeometryKind
  label: string
  format: ClinicalMeshFormat
  url: string
  frame: PatientReferenceSpace
  /** Identity for patient-native layers; accepted server transform for IOS. */
  patientTransform: Matrix4Rows
  reviewStatus: ReviewStatus
  provenance: ClinicalProvenance
}

export interface ClinicalNervePathway {
  id: string
  side: 'left' | 'right'
  status: 'detected' | 'uncertain'
  confidence: number
  points: PatientPointMm[]
  frame: PatientReferenceSpace
  reviewStatus: ReviewStatus
  provenance: ClinicalProvenance
}

export interface ClinicalCbctSeries {
  studyInstanceUid: string
  seriesInstanceUid: string
  frame: PatientReferenceSpace
  imageUrls: string[]
  instanceCount: number
}

export interface ClinicalScene {
  contract: 'dentora-clinical-scene-v1'
  patientId: string
  frame: PatientReferenceSpace
  geometry: ClinicalGeometryLayer[]
  nerves: ClinicalNervePathway[]
  cbct: ClinicalCbctSeries
  alignment: {
    id: string
    status: 'accepted'
    algorithm: string
    algorithmVersion: string
    reviewedAt: string | null
    reviewNote: string | null
  } | null
  blockers: string[]
}

export interface ClinicalMeshPayload {
  source: string
  format: string
  document_id: string | null
  label?: string | null
  url: string | null
  reference_space?: {
    kind?: string | null
    unit?: string | null
    frame_of_reference_uid?: string | null
  } | null
  anatomy_kind?: string | null
  provenance?: {
    identifier?: string | null
    digest?: string | null
    model_id?: string | null
    model_version?: string | null
    performed_at?: string | null
  } | null
}

export interface ClinicalScenePayload {
  patient_id: string
  meshes?: ClinicalMeshPayload[] | null
  cbct_series?: Array<{
    study_instance_uid: string
    series_instance_uid: string
    frame_of_reference_uid?: string | null
    document_ids?: string[] | null
    instance_count?: number | null
  }> | null
}

export interface AlignmentPayload {
  id?: string | null
  status?: string | null
  transform?: { matrix?: number[][] | null } | null
  source_frame?: { kind?: string | null, unit?: string | null } | null
  target_frame?: {
    kind?: string | null
    unit?: string | null
    frame_of_reference_uid?: string | null
  } | null
  algorithm?: string | null
  algorithm_version?: string | null
  provenance?: {
    ios?: { identifier?: string | null, digest?: string | null, document_ids?: string[] | null } | null
    anatomy_model_id?: string | null
    anatomy_model_version?: string | null
  } | null
  performed_at?: string | null
  reviewed_at?: string | null
  review_note?: string | null
}

const IDENTITY: Matrix4Rows = [
  [1, 0, 0, 0],
  [0, 1, 0, 0],
  [0, 0, 1, 0],
  [0, 0, 0, 1]
]

function finitePoint(point: { x?: number | null, y?: number | null, z?: number | null }): PatientPointMm | null {
  const x = Number(point.x)
  const y = Number(point.y)
  const z = Number(point.z)
  return Number.isFinite(x) && Number.isFinite(y) && Number.isFinite(z) ? { x, y, z } : null
}

export function validRigidMatrix(value: number[][] | null | undefined): Matrix4Rows | null {
  if (!value || value.length !== 4 || value.some(row => row.length !== 4)) return null
  if (value.flat().some(component => !Number.isFinite(component))) return null
  const last = value[3]
  if (!last || Math.abs(last[0]!) > 1e-7 || Math.abs(last[1]!) > 1e-7 || Math.abs(last[2]!) > 1e-7 || Math.abs(last[3]! - 1) > 1e-7) return null
  const rotation = value.slice(0, 3).map(row => row.slice(0, 3))
  for (const row of rotation) {
    if (Math.abs(row.reduce((sum, item) => sum + item * item, 0) - 1) > 1e-5) return null
  }
  for (let left = 0; left < 3; left += 1) {
    for (let right = left + 1; right < 3; right += 1) {
      const dot = rotation[left]!.reduce((sum, item, index) => sum + item * rotation[right]![index]!, 0)
      if (Math.abs(dot) > 1e-5) return null
    }
  }
  const r = rotation
  const determinant = r[0]![0]! * (r[1]![1]! * r[2]![2]! - r[1]![2]! * r[2]![1]!)
    - r[0]![1]! * (r[1]![0]! * r[2]![2]! - r[1]![2]! * r[2]![0]!)
    + r[0]![2]! * (r[1]![0]! * r[2]![1]! - r[1]![1]! * r[2]![0]!)
  if (Math.abs(determinant - 1) > 1e-5) return null
  return value as unknown as Matrix4Rows
}

function patientSpace(frameOfReferenceUid: string): PatientReferenceSpace {
  return { kind: 'dicom_patient', unit: 'mm', frameOfReferenceUid }
}

function meshKind(mesh: ClinicalMeshPayload): ClinicalGeometryKind | null {
  if (mesh.source === 'intraoral_scan') return 'ios_surface'
  if (mesh.source !== 'segmentation' && mesh.source !== 'cbct') return null
  if (mesh.anatomy_kind === 'tooth') return 'tooth'
  if (mesh.anatomy_kind === 'mandible') return 'mandible'
  if (mesh.anatomy_kind === 'anatomy') return 'anatomy'
  return null
}

function meshFormat(value: string): ClinicalMeshFormat | null {
  return value === 'stl' || value === 'ply' || value === 'obj' ? value : null
}

/** Compose only artifacts that can prove they share one DICOM patient frame. */
export function buildClinicalScene(
  scene: ClinicalScenePayload | null,
  alignment: AlignmentPayload | null,
  nerve: NerveAnalysisPayload | null
): ClinicalScene | null {
  if (!scene) return null
  const acceptedFrame = alignment?.status === 'accepted'
    && alignment.target_frame?.kind === 'dicom_patient'
    && alignment.target_frame.unit === 'mm'
    ? alignment.target_frame.frame_of_reference_uid
    : null
  const cbctPayload = (scene.cbct_series ?? []).find(series =>
    Boolean(series.frame_of_reference_uid)
    && (!acceptedFrame || series.frame_of_reference_uid === acceptedFrame)
  )
  if (!cbctPayload?.frame_of_reference_uid || !cbctPayload.document_ids?.length) return null

  const frame = patientSpace(cbctPayload.frame_of_reference_uid)
  const blockers: string[] = []
  const transform = validRigidMatrix(alignment?.transform?.matrix)
  const acceptedAlignment = alignment?.status === 'accepted'
    && alignment.id
    && transform
    && alignment.source_frame?.kind === 'ios_mesh'
    && alignment.source_frame.unit === 'mm'
    && acceptedFrame === frame.frameOfReferenceUid
    ? alignment
    : null
  if (alignment && !acceptedAlignment) blockers.push('alignment_not_accepted_or_frame_mismatch')

  const geometry: ClinicalGeometryLayer[] = []
  for (const mesh of scene.meshes ?? []) {
    const format = meshFormat(mesh.format)
    const kind = meshKind(mesh)
    if (!format || !kind || !mesh.document_id || !mesh.url || mesh.source === 'synthetic') continue
    if (kind === 'ios_surface') {
      const iosDocuments = acceptedAlignment?.provenance?.ios?.document_ids ?? []
      if (!acceptedAlignment || !transform || !iosDocuments.includes(mesh.document_id)) {
        blockers.push(`unregistered_ios:${mesh.document_id}`)
        continue
      }
      geometry.push({
        id: mesh.document_id,
        kind,
        label: mesh.label ?? 'Registered IOS',
        format,
        url: mesh.url,
        frame,
        patientTransform: transform,
        reviewStatus: 'accepted',
        provenance: {
          source: mesh.source,
          identifier: acceptedAlignment.provenance?.ios?.identifier ?? mesh.document_id,
          digest: acceptedAlignment.provenance?.ios?.digest ?? null,
          modelId: null,
          modelVersion: null,
          performedAt: acceptedAlignment.performed_at ?? null
        }
      })
      continue
    }
    const reference = mesh.reference_space
    if (reference?.kind !== 'dicom_patient' || reference.unit !== 'mm' || reference.frame_of_reference_uid !== frame.frameOfReferenceUid) {
      blockers.push(`unregistered_anatomy:${mesh.document_id}`)
      continue
    }
    if (!mesh.provenance?.identifier || !mesh.provenance.digest) {
      blockers.push(`missing_anatomy_provenance:${mesh.document_id}`)
      continue
    }
    geometry.push({
      id: mesh.document_id,
      kind,
      label: mesh.label ?? 'DentalSegmentator anatomy',
      format,
      url: mesh.url,
      frame,
      patientTransform: IDENTITY,
      reviewStatus: 'pending',
      provenance: {
        source: mesh.source,
        identifier: mesh.provenance.identifier,
        digest: mesh.provenance.digest,
        modelId: mesh.provenance.model_id ?? null,
        modelVersion: mesh.provenance.model_version ?? null,
        performedAt: mesh.provenance.performed_at ?? null
      }
    })
  }

  const nerves: ClinicalNervePathway[] = []
  const nerveReview: ReviewStatus = nerve?.review_status === 'accepted' || nerve?.review_status === 'rejected'
    ? nerve.review_status
    : 'pending'
  if (nerve && nerve.status !== 'failed' && nerveReview !== 'rejected') {
    for (const [index, pathway] of (nerve.pathways ?? []).entries()) {
      const reference = pathway.reference_space
      if (reference?.kind !== 'dicom_patient' || reference.unit !== 'mm' || reference.frame_of_reference_uid !== frame.frameOfReferenceUid) continue
      const points = (pathway.points ?? []).map(finitePoint).filter((point): point is PatientPointMm => point !== null)
      if (points.length < 2 || (pathway.side !== 'left' && pathway.side !== 'right')) continue
      const confidence = Number(pathway.confidence)
      if (!Number.isFinite(confidence) || confidence < 0 || confidence > 1) continue
      nerves.push({
        id: pathway.finding_id ?? `${nerve.id}:pathway:${index}`,
        side: pathway.side,
        status: pathway.status === 'uncertain' ? 'uncertain' : 'detected',
        confidence,
        points,
        frame,
        reviewStatus: nerveReview,
        provenance: {
          source: pathway.source ?? 'model_inference',
          identifier: nerve.provenance?.input_digest ?? nerve.id,
          digest: nerve.provenance?.input_digest ?? null,
          modelId: nerve.provenance?.model_id ?? null,
          modelVersion: nerve.provenance?.model_version ?? null,
          performedAt: nerve.performed_at ?? null
        }
      })
    }
  }

  return {
    contract: 'dentora-clinical-scene-v1',
    patientId: scene.patient_id,
    frame,
    geometry,
    nerves,
    cbct: {
      studyInstanceUid: cbctPayload.study_instance_uid,
      seriesInstanceUid: cbctPayload.series_instance_uid,
      frame,
      imageUrls: cbctPayload.document_ids.map(id => `/api/v1/media/documents/${id}/download`),
      instanceCount: cbctPayload.instance_count ?? cbctPayload.document_ids.length
    },
    alignment: acceptedAlignment
      ? {
          id: acceptedAlignment.id!,
          status: 'accepted',
          algorithm: acceptedAlignment.algorithm ?? '',
          algorithmVersion: acceptedAlignment.algorithm_version ?? '',
          reviewedAt: acceptedAlignment.reviewed_at ?? null,
          reviewNote: acceptedAlignment.review_note ?? null
        }
      : null,
    blockers: [...new Set(blockers)]
  }
}
