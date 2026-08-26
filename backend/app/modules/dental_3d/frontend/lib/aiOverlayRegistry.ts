import type { ClinicalScene, PatientReferenceSpace, ReviewStatus } from './clinicalScene'

export interface AiOverlay<T = unknown> {
  id: string
  type: string
  frame: PatientReferenceSpace
  reviewStatus: ReviewStatus
  provenanceId: string
  visible: boolean
  data: T
}

export class AiOverlayRegistry {
  readonly #frame: PatientReferenceSpace
  readonly #overlays = new Map<string, AiOverlay>()

  constructor(frame: PatientReferenceSpace) {
    this.#frame = frame
  }

  register<T>(overlay: AiOverlay<T>): boolean {
    if (overlay.frame.kind !== 'dicom_patient' || overlay.frame.unit !== 'mm') return false
    if (overlay.frame.frameOfReferenceUid !== this.#frame.frameOfReferenceUid) return false
    if (!overlay.provenanceId || overlay.reviewStatus === 'rejected') return false
    this.#overlays.set(overlay.id, overlay)
    return true
  }

  setVisible(id: string, visible: boolean): void {
    const overlay = this.#overlays.get(id)
    if (overlay) overlay.visible = visible
  }

  list(type?: string): AiOverlay[] {
    return [...this.#overlays.values()].filter(item => !type || item.type === type)
  }
}

export function registryFromClinicalScene(scene: ClinicalScene): AiOverlayRegistry {
  const registry = new AiOverlayRegistry(scene.frame)
  for (const pathway of scene.nerves) {
    registry.register({
      id: pathway.id,
      type: 'mandibular_nerve',
      frame: pathway.frame,
      reviewStatus: pathway.reviewStatus,
      provenanceId: pathway.provenance.identifier,
      visible: true,
      data: pathway
    })
  }
  for (const layer of scene.geometry.filter(item => item.provenance.modelId)) {
    registry.register({
      id: layer.id,
      type: `anatomy:${layer.kind}`,
      frame: layer.frame,
      reviewStatus: layer.reviewStatus,
      provenanceId: layer.provenance.identifier,
      visible: true,
      data: layer
    })
  }
  return registry
}
