/**
 * Fetch + project a patient's dental 3D scene for the summary card.
 *
 * The API contract mirrors the backend schemas
 * (``app/modules/dental_3d/schemas.py``). ``toViewerTeeth`` /
 * ``summarizeScene`` are pure so they are unit-testable without a
 * Nuxt app; the composable itself follows the DiagnosesCard fetch
 * pattern (client-side ``useAsyncData``, keyed by patient).
 *
 * Phase 2 adds real-mesh I/O (``useDental3DMeshIO``): authorized
 * binary download for the viewer and multipart upload for the card.
 * Binary/multipart requests deliberately bypass the JSON-oriented
 * ``useApi`` wrapper and follow the media module's ``useDocuments``
 * pattern (``$fetch`` + explicit auth header) — same conventions, no
 * new abstraction.
 *
 * Phase 4 adds ``useDental3DNerveDetection``: run / load / review the
 * mandibular nerve-detection analysis (ADR 0022) — same fetch/review
 * pattern as the Phase 3 segmentation composable.
 */
import type { ApiResponse } from '~~/app/types'
import { errorMessage, errorStatus } from '~~/app/utils/error'
import type { DentalToothView } from '../lib/dentalArch'
import type { DentalMeshPayload, SceneMeshRef } from '../lib/sceneMeshes'
import type { NerveAnalysisPayload } from '../lib/nerveView'
import type { AlignmentPayload } from '../lib/clinicalScene'

/**
 * Fallbacks used only when the backend gave no explanation at all. When
 * it did (409 readiness gate, 503 provider unavailable, 403 permission),
 * `errorMessage` surfaces that text instead — a blocked clinical action
 * must state its actual prerequisite.
 */
const SEGMENTATION_UNAVAILABLE = 'Segmentation is unavailable for this patient.'
const SEGMENTATION_RUN_FAILED = 'Segmentation could not be run.'
const SEGMENTATION_REVIEW_FAILED = 'The segmentation review could not be recorded.'
const NERVE_UNAVAILABLE = 'Nerve detection is unavailable for this patient.'
const NERVE_RUN_FAILED = 'Nerve detection could not be run.'
const NERVE_REVIEW_FAILED = 'The nerve-detection review could not be recorded.'

export interface DentalSceneSegmentation {
  status: 'not_available' | 'synthetic' | 'completed'
  method?: string | null
  teeth_found?: number
}

export interface DentalScenePayload {
  id?: string | null
  patient_id: string
  generator: string
  persisted: boolean
  teeth: DentalToothView[]
  segmentation: DentalSceneSegmentation
  /** Real mesh references (server-derived; Phase 2: intraoral scans). */
  meshes?: DentalMeshPayload[] | null
  cbct_series?: Array<{
    study_instance_uid: string
    series_instance_uid: string
    frame_of_reference_uid?: string | null
    document_ids: string[]
    instance_count: number
  }> | null
  updated_at?: string | null
}

/** Pure: teeth the viewer should draw, in stable FDI order. */
export function toViewerTeeth(scene: DentalScenePayload | null): DentalToothView[] {
  if (!scene) return []
  return [...scene.teeth]
    .filter(t => t.present && t.visible)
    .sort((a, b) => a.tooth_number - b.tooth_number)
}

/** Pure: headline numbers for the card body. */
export function summarizeScene(scene: DentalScenePayload | null): {
  rendered: number
  flagged: number
} {
  const teeth = toViewerTeeth(scene)
  return {
    rendered: teeth.length,
    flagged: teeth.filter(t => t.condition !== 'healthy').length
  }
}

export function useDental3DScene(patientId: () => string) {
  const api = useApi()

  return useAsyncData(
    () => `dental3d:scene:${patientId()}`,
    async (): Promise<DentalScenePayload | null> => {
      try {
        // Ambient card load on the patient summary: the card owns the
        // degraded state, so the failure must not also raise a global
        // toast that reads as "this patient page is forbidden".
        const response = await api.get<ApiResponse<DentalScenePayload>>(
          `/api/v1/dental_3d/patients/${patientId()}/scene`,
          { silent: true }
        )
        return response.data
      } catch {
        // Card degrades to the error state; never breaks the summary grid.
        return null
      }
    },
    { watch: [() => patientId()], server: false }
  )
}

/**
 * Real-mesh transport for the viewer (download) and the card (upload).
 *
 * Stateless on purpose: loading/error *state* is owned by the callers
 * (the viewer's phase machine / the card's upload flag) so both stay
 * unit-testable against injected fakes.
 */
export function useDental3DMeshIO() {
  const config = useRuntimeConfig()

  const apiBaseUrl = computed(() =>
    import.meta.server ? config.apiBaseUrlServer : config.public.apiBaseUrl
  )

  // Binary downloads (meshes, DICOM) cannot go through useApi, but they must
  // still carry the clinic selection — see useApiHeaders.
  const authHeaders = useApiHeaders()

  /** Download mesh content through media's authorized download route. */
  async function fetchMeshContent(
    mesh: SceneMeshRef,
    signal?: AbortSignal
  ): Promise<ArrayBuffer | string> {
    return await $fetch<ArrayBuffer | string>(mesh.url, {
      baseURL: apiBaseUrl.value,
      headers: authHeaders(),
      responseType: mesh.format === 'obj' ? 'text' : 'arrayBuffer',
      signal
    })
  }

  async function fetchGeometryContent(
    url: string,
    format: 'stl' | 'ply' | 'obj',
    signal?: AbortSignal
  ): Promise<ArrayBuffer | string> {
    return await $fetch<ArrayBuffer | string>(url, {
      baseURL: apiBaseUrl.value,
      headers: authHeaders(),
      responseType: format === 'obj' ? 'text' : 'arrayBuffer',
      signal
    })
  }

  async function fetchDocumentBlob(url: string, signal?: AbortSignal): Promise<Blob> {
    const content = await $fetch<ArrayBuffer>(url, {
      baseURL: apiBaseUrl.value,
      headers: authHeaders(),
      responseType: 'arrayBuffer',
      signal
    })
    return new Blob([content], { type: 'application/dicom' })
  }

  /** Upload a mesh file; returns the new mesh descriptor or null. */
  async function uploadMesh(patientId: string, file: File): Promise<DentalMeshPayload | null> {
    const formData = new FormData()
    formData.append('file', file)
    try {
      const response = await $fetch<ApiResponse<DentalMeshPayload>>(
        `/api/v1/dental_3d/patients/${patientId}/meshes`,
        {
          baseURL: apiBaseUrl.value,
          method: 'POST',
          body: formData,
          headers: authHeaders()
        }
      )
      return response.data
    } catch (error) {
      console.error('Error uploading mesh:', error)
      return null
    }
  }

  return { fetchMeshContent, fetchGeometryContent, fetchDocumentBlob, uploadMesh }
}

/** Latest patient-specific alignment and dentist review. No client transform is computed. */
export function useDental3DAlignment(patientId: () => string) {
  const api = useApi()
  const alignment = ref<AlignmentPayload | null>(null)
  const reviewing = ref(false)

  function alignmentUrl(): string {
    return `/api/v1/dental_3d/patients/${patientId()}/alignment`
  }

  async function load(): Promise<void> {
    try {
      // Ambient load (mounted with the summary card) — see useDental3DScene.
      const response = await api.get<ApiResponse<AlignmentPayload>>(alignmentUrl(), { silent: true })
      alignment.value = response.data
    } catch {
      alignment.value = null
    }
  }

  async function review(decision: 'accepted' | 'rejected', note?: string): Promise<boolean> {
    if (!alignment.value?.id) return false
    reviewing.value = true
    try {
      const response = await api.post<ApiResponse<AlignmentPayload>>(
        `${alignmentUrl()}/${alignment.value.id}/review`,
        { decision, note: note ?? null }
      )
      alignment.value = response.data
      return true
    } catch (error) {
      console.error('Error reviewing patient alignment:', error)
      return false
    } finally {
      reviewing.value = false
    }
  }

  return { alignment, reviewing, load, review }
}

/**
 * Segmentation workflow state (Phase 3, ADR 0021): latest analysis,
 * run action and dentist review action. Imperative on purpose — the
 * workflow is user-driven (Run → review evidence → Accept/Reject),
 * and every result comes from the server; no client-side analysis
 * exists. Mirrors the scene composable's degradation contract: a
 * failed action flips a flag, never breaks the summary grid.
 */
export interface SegmentationToothPayload {
  tooth_number: number
  status: string
  confidence: number
  evidence?: {
    basis?: string | null
    arch_region?: string | null
    backing_documents?: string[] | null
    note?: string | null
  } | null
}

export interface SegmentationAnalysisPayload {
  id: string
  patient_id: string
  provider: string
  method: string
  is_clinical: boolean
  requires_review: boolean
  teeth: SegmentationToothPayload[]
  performed_at: string | null
  created_at: string | null
  review_status: 'pending' | 'accepted' | 'rejected'
  reviewed_at: string | null
  review_note: string | null
  segmented_count: number
  uncertain_count: number
  missing_count: number
  disclaimer: string
}

export function useDental3DSegmentation(patientId: () => string) {
  const api = useApi()

  const analysis = ref<SegmentationAnalysisPayload | null>(null)
  const running = ref(false)
  const runFailed = ref(false)
  const reviewing = ref(false)
  /**
   * The real reason the last action/load failed — the backend's own
   * explanation when it gave one (missing CBCT, provider unavailable,
   * review state conflict, permission). Rendered by the card instead of
   * a generic "run failed", so a blocked action says what is missing.
   */
  const error = ref<string | null>(null)

  function segmentUrl(): string {
    return `/api/v1/dental_3d/patients/${patientId()}/segmentation`
  }

  /** Load the latest analysis (404 = never run → no analysis). */
  async function load(): Promise<void> {
    try {
      // Ambient load (mounted with the summary card) — never a global toast.
      const response = await api.get<ApiResponse<SegmentationAnalysisPayload>>(
        segmentUrl(),
        { silent: true }
      )
      analysis.value = response.data
      error.value = null
    } catch (e: unknown) {
      analysis.value = null
      // 404 = "never run": a normal empty state, not a failure.
      error.value = errorStatus(e) === 404 ? null : errorMessage(e, SEGMENTATION_UNAVAILABLE)
    }
  }

  /** Run the segmentation analysis server-side (provider-driven). */
  async function run(): Promise<boolean> {
    running.value = true
    runFailed.value = false
    error.value = null
    try {
      const response = await api.post<ApiResponse<SegmentationAnalysisPayload>>(
        segmentUrl(),
        null,
        { silent: true }
      )
      analysis.value = response.data
      return true
    } catch (e: unknown) {
      console.error('Error running segmentation:', e)
      runFailed.value = true
      error.value = errorMessage(e, SEGMENTATION_RUN_FAILED)
      return false
    } finally {
      running.value = false
    }
  }

  /** Record the dentist's review decision (server enforces pending-only). */
  async function review(decision: 'accepted' | 'rejected', note?: string): Promise<boolean> {
    if (!analysis.value) return false
    reviewing.value = true
    error.value = null
    try {
      const response = await api.post<ApiResponse<SegmentationAnalysisPayload>>(
        `${segmentUrl()}/${analysis.value.id}/review`,
        { decision, note: note ?? null },
        { silent: true }
      )
      analysis.value = response.data
      return true
    } catch (e: unknown) {
      console.error('Error reviewing segmentation:', e)
      error.value = errorMessage(e, SEGMENTATION_REVIEW_FAILED)
      return false
    } finally {
      reviewing.value = false
    }
  }

  return { analysis, running, runFailed, reviewing, error, load, run, review }
}

/**
 * Nerve detection (Phase 4, ADR 0022): fetch / run / review the
 * mandibular nerve-detection analysis for the patient's scene. Same
 * pattern as ``useDental3DSegmentation`` — server-side analysis only,
 * review state enforced by the backend.
 */
export function useDental3DNerveDetection(patientId: () => string) {
  const api = useApi()

  const analysis = ref<NerveAnalysisPayload | null>(null)
  const running = ref(false)
  const runFailed = ref(false)
  const reviewing = ref(false)
  /** Real reason for the last failure — see useDental3DSegmentation. */
  const error = ref<string | null>(null)

  function nerveUrl(): string {
    return `/api/v1/dental_3d/patients/${patientId()}/nerve-detection`
  }

  /** Load the latest analysis (404 = never run → no analysis). */
  async function load(): Promise<void> {
    try {
      // Ambient load (mounted with the summary card) — never a global toast.
      const response = await api.get<ApiResponse<NerveAnalysisPayload>>(
        nerveUrl(),
        { silent: true }
      )
      analysis.value = response.data
      error.value = null
    } catch (e: unknown) {
      analysis.value = null
      error.value = errorStatus(e) === 404 ? null : errorMessage(e, NERVE_UNAVAILABLE)
    }
  }

  /** Run the nerve-detection analysis server-side (provider-driven). */
  async function run(): Promise<boolean> {
    running.value = true
    runFailed.value = false
    error.value = null
    try {
      const response = await api.post<ApiResponse<NerveAnalysisPayload>>(
        nerveUrl(),
        null,
        { silent: true }
      )
      analysis.value = response.data
      return true
    } catch (e: unknown) {
      console.error('Error running nerve detection:', e)
      runFailed.value = true
      error.value = errorMessage(e, NERVE_RUN_FAILED)
      return false
    } finally {
      running.value = false
    }
  }

  /** Record the dentist's review decision (server enforces pending-only). */
  async function review(decision: 'accepted' | 'rejected', note?: string): Promise<boolean> {
    if (!analysis.value) return false
    reviewing.value = true
    error.value = null
    try {
      const response = await api.post<ApiResponse<NerveAnalysisPayload>>(
        `${nerveUrl()}/${analysis.value.id}/review`,
        { decision, note: note ?? null },
        { silent: true }
      )
      analysis.value = response.data
      return true
    } catch (e: unknown) {
      console.error('Error reviewing nerve detection:', e)
      error.value = errorMessage(e, NERVE_REVIEW_FAILED)
      return false
    } finally {
      reviewing.value = false
    }
  }

  return { analysis, running, runFailed, reviewing, error, load, run, review }
}
