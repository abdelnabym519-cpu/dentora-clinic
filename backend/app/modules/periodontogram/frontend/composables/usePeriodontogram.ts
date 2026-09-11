/**
 * State + API client for a single patient's periodontogram.
 *
 * Lightweight wrapper around `useApi()`. PR-4 only needs timeline
 * loading and draft creation — full snapshot editing flows wire up in
 * PR-5 / PR-6 once the chart components exist.
 */

import { computed, ref } from 'vue'
import { errorMessage } from '~~/app/utils/error'
import type {
  PerioSite,
  PerioSnapshotDetail,
  PerioTimelineResponse,
  SiteCode
} from '../types'

interface ApiResponse<T> {
  data: T
  message?: string | null
}

export function usePeriodontogram(patientId: () => string) {
  const api = useApi()

  const timeline = ref<PerioTimelineResponse | null>(null)
  const currentSnapshot = ref<PerioSnapshotDetail | null>(null)
  const viewingDate = ref<string | null>(null)
  const isLoading = ref(false)
  const error = ref<string | null>(null)

  const hasDraft = computed(() => Boolean(timeline.value?.draft))
  const closedCount = computed(() => timeline.value?.dates.length ?? 0)
  const isEmpty = computed(() => !hasDraft.value && closedCount.value === 0)

  async function fetchTimeline(): Promise<void> {
    isLoading.value = true
    error.value = null
    try {
      const response = await api.get<ApiResponse<PerioTimelineResponse>>(
        `/api/v1/periodontogram/patients/${patientId()}/timeline`,
        { silent: true }
      )
      timeline.value = response.data
    } catch (e) {
      // `e.message` on a FetchError is just "403 Forbidden"; the view renders
      // this string as the alert's description, so it has to carry the reason.
      error.value = errorMessage(e, 'load_failed')
    } finally {
      isLoading.value = false
    }
  }

  async function fetchDraft(): Promise<void> {
    try {
      const response = await api.get<ApiResponse<PerioSnapshotDetail | null>>(
        `/api/v1/periodontogram/patients/${patientId()}/draft`,
        { silent: true }
      )
      currentSnapshot.value = response.data
      viewingDate.value = null
    } catch (e) {
      // No catch here meant the rejection escaped `refreshAll` — which runs
      // from onMounted and from the patientId watcher — and the view fell
      // through to "start a session" as though nothing had ever been recorded.
      console.error('Error loading periodontogram draft:', e)
      error.value = errorMessage(e, 'load_failed')
    }
  }

  async function fetchSnapshot(snapshotId: string): Promise<void> {
    try {
      const response = await api.get<ApiResponse<PerioSnapshotDetail>>(
        `/api/v1/periodontogram/snapshots/${snapshotId}`,
        { silent: true }
      )
      currentSnapshot.value = response.data
    } catch (e) {
      // Picking a past date used to leave the previous snapshot on screen with
      // no message when this failed: a chart labelled with the wrong date.
      console.error('Error loading periodontogram snapshot:', e)
      error.value = errorMessage(e, 'load_failed')
    }
  }

  // Optimistic mutators — apply a per-tooth or per-site patch directly
  // onto `currentSnapshot.value` so the UI updates on the next frame,
  // before the debounced PATCH lands. Caller (the chart) is responsible
  // for queueing the network write separately.
  function applySitePatch(
    toothNumber: number,
    siteCode: SiteCode,
    patch: Record<string, unknown>
  ): void {
    const snap = currentSnapshot.value
    if (!snap) return
    const tooth = snap.teeth.find(t => t.tooth_number === toothNumber)
    if (!tooth) return
    let site = tooth.sites.find(s => s.site_code === siteCode)
    if (!site) {
      // Backend creates the PeriodontogramSite row lazily on the first
      // PATCH (see service.py: `update_site`). Mirror that here so the
      // optimistic update has a target to mutate — otherwise the very
      // first edit of a site would no-op locally and the marker would
      // only repaint after a refetch.
      site = {
        site_code: siteCode,
        probing_depth_mm: null,
        gingival_margin_mm: null,
        bleeding_on_probing: false,
        plaque: false,
        suppuration: false
      } satisfies PerioSite
      tooth.sites.push(site)
    }
    for (const [key, value] of Object.entries(patch)) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (site as any)[key] = value
    }
  }

  function applyToothPatch(toothNumber: number, patch: Record<string, unknown>): void {
    const snap = currentSnapshot.value
    if (!snap) return
    const tooth = snap.teeth.find(t => t.tooth_number === toothNumber)
    if (!tooth) return
    for (const [key, value] of Object.entries(patch)) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (tooth as any)[key] = value
    }
  }

  async function startDraft(): Promise<PerioSnapshotDetail> {
    error.value = null
    try {
      const response = await api.post<ApiResponse<PerioSnapshotDetail>>(
        `/api/v1/periodontogram/patients/${patientId()}/draft`,
        {},
        { silent: true }
      )
      currentSnapshot.value = response.data
      await fetchTimeline()
      return response.data
    } catch (e) {
      // A 409 ("a draft already exists") used to stop the button's spinner and
      // say nothing at all. Rethrown so the caller does not go on to load a
      // draft that was never created.
      console.error('Error starting periodontogram draft:', e)
      error.value = errorMessage(e, 'start_failed')
      throw e
    }
  }

  return {
    timeline,
    currentSnapshot,
    viewingDate,
    isLoading,
    error,
    hasDraft,
    closedCount,
    isEmpty,
    fetchTimeline,
    fetchDraft,
    fetchSnapshot,
    startDraft,
    applySitePatch,
    applyToothPatch
  }
}
