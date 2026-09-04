/**
 * State + API client for patient pathology analyses.
 *
 * Mirrors `usePeriodontogram`: a thin wrapper over `useApi()` so the
 * view component stays declarative. All backend error mapping stays on
 * the server (404/422/503); the composable surfaces message strings.
 */

import { computed, ref } from 'vue'
import type {
  PathologyAnalysisDetail,
  PathologyAnalysisSummary,
  PathologyCapabilities
} from '../types'

interface ApiResponse<T> {
  data: T
  message?: string | null
}

interface PaginatedApiResponse<T> {
  data: T[]
  total: number
  page: number
  page_size: number
}

export interface MediaDocument {
  id: string
  patient_id: string
  title: string
  original_filename: string
  mime_type: string
  file_size: number
  media_kind: string
  media_category: string | null
  media_subtype: string | null
  captured_at: string | null
  thumb_url: string | null
  medium_url: string | null
  full_url: string | null
  created_at: string
}

export function usePathologyDetection(patientId: () => string) {
  const api = useApi()

  const capabilities = ref<PathologyCapabilities | null>(null)
  const documents = ref<MediaDocument[]>([])
  const analyses = ref<PathologyAnalysisSummary[]>([])
  const current = ref<PathologyAnalysisDetail | null>(null)
  const isLoading = ref(false)
  const isRunning = ref(false)
  const error = ref<string | null>(null)

  const hasAnalyses = computed(() => analyses.value.length > 0)

  async function fetchCapabilities(): Promise<void> {
    try {
      const response = await api.get<ApiResponse<PathologyCapabilities>>(
        '/api/v1/pathology_detection/capabilities'
      )
      capabilities.value = response.data
    } catch {
      capabilities.value = null
    }
  }

  async function fetchDocuments(): Promise<void> {
    const gathered: MediaDocument[] = []
    for (const mediaKind of ['xray', 'photo']) {
      const response = await api.get<PaginatedApiResponse<MediaDocument>>(
        `/api/v1/media/patients/${patientId()}/documents?media_kind=${mediaKind}&page_size=100`
      )
      gathered.push(...response.data)
    }
    documents.value = gathered.sort(
      (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    )
  }

  async function fetchAnalyses(): Promise<void> {
    isLoading.value = true
    error.value = null
    try {
      const response = await api.get<ApiResponse<PathologyAnalysisSummary[]>>(
        `/api/v1/pathology_detection/patients/${patientId()}/analyses`
      )
      analyses.value = response.data
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'pathology.load_failed'
    } finally {
      isLoading.value = false
    }
  }

  async function fetchAnalysis(analysisId: string): Promise<void> {
    const response = await api.get<ApiResponse<PathologyAnalysisDetail>>(
      `/api/v1/pathology_detection/analyses/${analysisId}`
    )
    current.value = response.data
  }

  async function runAnalysis(documentId: string, notes?: string): Promise<PathologyAnalysisDetail> {
    isRunning.value = true
    error.value = null
    try {
      const response = await api.post<ApiResponse<PathologyAnalysisDetail>>(
        `/api/v1/pathology_detection/patients/${patientId()}/analyses`,
        { document_id: documentId, notes: notes || null }
      )
      current.value = response.data
      await fetchAnalyses()
      return response.data
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'pathology.run_failed'
      throw e
    } finally {
      isRunning.value = false
    }
  }

  async function removeAnalysis(analysisId: string): Promise<void> {
    await api.del(`/api/v1/pathology_detection/analyses/${analysisId}`)
    if (current.value?.id === analysisId) {
      current.value = null
    }
    await fetchAnalyses()
  }

  return {
    capabilities,
    documents,
    analyses,
    current,
    isLoading,
    isRunning,
    error,
    hasAnalyses,
    fetchCapabilities,
    fetchDocuments,
    fetchAnalyses,
    fetchAnalysis,
    runAnalysis,
    removeAnalysis
  }
}
