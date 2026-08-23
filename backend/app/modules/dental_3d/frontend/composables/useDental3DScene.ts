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
 */
import type { ApiResponse } from '~~/app/types'
import type { DentalToothView } from '../lib/dentalArch'
import type { DentalMeshPayload, SceneMeshRef } from '../lib/sceneMeshes'

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
        const response = await api.get<ApiResponse<DentalScenePayload>>(
          `/api/v1/dental_3d/patients/${patientId()}/scene`
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
  const auth = useAuth()

  const apiBaseUrl = computed(() =>
    import.meta.server ? config.apiBaseUrlServer : config.public.apiBaseUrl
  )

  function authHeaders(): Record<string, string> {
    return auth.accessToken.value
      ? { Authorization: `Bearer ${auth.accessToken.value}` }
      : {}
  }

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

  return { fetchMeshContent, uploadMesh }
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

  function segmentUrl(): string {
    return `/api/v1/dental_3d/patients/${patientId()}/segmentation`
  }

  /** Load the latest analysis (404 = never run → no analysis). */
  async function load(): Promise<void> {
    try {
      const response = await api.get<ApiResponse<SegmentationAnalysisPayload>>(segmentUrl())
      analysis.value = response.data
    } catch {
      analysis.value = null
    }
  }

  /** Run the segmentation analysis server-side (provider-driven). */
  async function run(): Promise<boolean> {
    running.value = true
    runFailed.value = false
    try {
      const response = await api.post<ApiResponse<SegmentationAnalysisPayload>>(segmentUrl())
      analysis.value = response.data
      return true
    } catch (error) {
      console.error('Error running segmentation:', error)
      runFailed.value = true
      return false
    } finally {
      running.value = false
    }
  }

  /** Record the dentist's review decision (server enforces pending-only). */
  async function review(decision: 'accepted' | 'rejected', note?: string): Promise<boolean> {
    if (!analysis.value) return false
    reviewing.value = true
    try {
      const response = await api.post<ApiResponse<SegmentationAnalysisPayload>>(
        `${segmentUrl()}/${analysis.value.id}/review`,
        { decision, note: note ?? null }
      )
      analysis.value = response.data
      return true
    } catch (error) {
      console.error('Error reviewing segmentation:', error)
      return false
    } finally {
      reviewing.value = false
    }
  }

  return { analysis, running, runFailed, reviewing, load, run, review }
}
