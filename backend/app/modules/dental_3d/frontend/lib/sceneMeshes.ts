/**
 * sceneMeshes — pure projection of dental scene meshes to renderables.
 *
 * Framework-free seam (ADR 0019): the backend speaks ``DentalMesh``
 * descriptors (``schemas.py``); the viewer wants a resolved, renderable
 * mesh reference. This module is the pure translation between the two
 * — no three.js, no Vue, no fetching — so it stays unit-testable and a
 * future renderer/backend swap only touches the adapters, never this
 * contract. Real mesh binaries are downloaded through the media
 * module's authorized route (``useDental3DMeshIO``), never inlined
 * here.
 */

/** Mesh descriptor as returned by the dental_3d scene API. */
export type DentalMeshPayload = {
  source: string
  format: string
  document_id: string | null
  label: string
  file_size: number
  uploaded_at: string
  url: string | null
}

/**
 * What can appear in a 3D scene. Phase 2 renders only ``surface``
 * meshes (intraoral scans); the other kinds are deliberate future
 * extensions (ADR 0020 scope) that extend this union — not the
 * viewer architecture.
 */
export type SceneMeshKind
  = 'surface' // full-arch intraoral scan
    | 'tooth' // segmented tooth (future — Phase 3)
    | 'nerve' // nerve canal path (future)
    | 'implant' // planned implant (future)

/** A renderable mesh reference, resolved to a downloadable document. */
export type SceneMeshRef = {
  id: string
  kind: SceneMeshKind
  source: string
  format: 'stl' | 'obj'
  label: string
  url: string
  documentId: string
  fileSize: number
}

/** Viewer load state for the active mesh. */
export type MeshLoadPhase = 'idle' | 'loading' | 'ready' | 'error'

/** Overlay chrome derived from (meshes, phase) — see ``meshOverlay``. */
export type MeshOverlayState = {
  renderSynthetic: boolean
  showLoading: boolean
  showError: boolean
  showBadge: boolean
}

/** Anything carrying optional server-derived meshes (a scene payload). */
export type MeshSceneSource = {
  meshes?: DentalMeshPayload[] | null
}

/**
 * Project scene mesh descriptors to renderable surface references.
 *
 * Synthetic/procedural descriptors and partial references (no
 * document, no URL, unsupported format) are dropped — the viewer only
 * ever sees meshes it can actually load, so the synthetic arch
 * fallback stays the default rather than an error path.
 */
export function toSceneMeshes(source: MeshSceneSource | null): SceneMeshRef[] {
  const meshes = source?.meshes ?? []
  const refs: SceneMeshRef[] = []
  for (const mesh of meshes) {
    if (mesh.source === 'synthetic') continue
    if (mesh.format !== 'stl' && mesh.format !== 'obj') continue
    if (!mesh.document_id || !mesh.url) continue
    refs.push({
      id: mesh.document_id,
      kind: 'surface',
      source: mesh.source,
      format: mesh.format,
      label: mesh.label,
      url: mesh.url,
      documentId: mesh.document_id,
      fileSize: mesh.file_size
    })
  }
  return refs
}

/**
 * The mesh the viewer should load: the first reference. The backend
 * returns meshes newest-first, so this is the latest scan — and the
 * natural future selection point once users can choose.
 */
export function pickActiveMesh(meshes: readonly SceneMeshRef[]): SceneMeshRef | null {
  return meshes[0] ?? null
}

/**
 * Overlay state machine for real-mesh rendering.
 *
 * No meshes → pure Phase 1 synthetic rendering, chrome-free. While a
 * real mesh loads (or fails) the synthetic arch stays visible — no
 * blank flash, and a failed scan never breaks the card. Only a ready
 * real mesh replaces the synthetic arch, with a badge identifying the
 * loaded scan.
 */
export function meshOverlay(
  meshes: readonly SceneMeshRef[],
  phase: MeshLoadPhase
): MeshOverlayState {
  if (meshes.length === 0) {
    return { renderSynthetic: true, showLoading: false, showError: false, showBadge: false }
  }
  switch (phase) {
    case 'ready':
      return { renderSynthetic: false, showLoading: false, showError: false, showBadge: true }
    case 'loading':
      return { renderSynthetic: true, showLoading: true, showError: false, showBadge: false }
    case 'error':
      return { renderSynthetic: true, showLoading: false, showError: true, showBadge: false }
    default:
      return { renderSynthetic: true, showLoading: false, showError: false, showBadge: false }
  }
}
