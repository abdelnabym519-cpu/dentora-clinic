/**
 * Session-edit composable for a single periodontogram snapshot.
 *
 * Wraps the PATCH / close / discard endpoints with a tiny debouncer
 * so per-cell edits coalesce into one network call per ~600ms.
 * `dirty` and `saving` flags drive the UI's autosave indicator.
 */

import { ref } from 'vue'
import { errorMessage } from '~~/app/utils/error'
import type { PerioSite, PerioSnapshotDetail, PerioTooth, SiteCode } from '../types'

interface ApiResponse<T> {
  data: T
}

type ToothPatch = Partial<
  Pick<
    PerioTooth,
    | 'is_present'
    | 'is_implant'
    | 'mobility'
    | 'prognosis'
    | 'furcation_buccal'
    | 'furcation_lingual'
    | 'keratinized_gingiva_mm'
  >
>

type SitePatch = Partial<
  Pick<
    PerioSite,
    | 'probing_depth_mm'
    | 'gingival_margin_mm'
    | 'bleeding_on_probing'
    | 'plaque'
    | 'suppuration'
  >
>

const DEBOUNCE_MS = 600

export function usePeriodontogramSession() {
  const api = useApi()
  const saving = ref(false)
  const dirty = ref(false)
  const lastError = ref<string | null>(null)
  const pendingTimers = new Map<string, ReturnType<typeof setTimeout>>()
  const pendingPayloads = new Map<string, Record<string, unknown>>()

  function _flushKey(key: string, exec: (payload: Record<string, unknown>) => Promise<void>) {
    return async () => {
      const payload = pendingPayloads.get(key)
      if (!payload) return
      pendingPayloads.delete(key)
      pendingTimers.delete(key)
      saving.value = true
      try {
        await exec(payload)
        lastError.value = null
        dirty.value = false
      } catch (e) {
        // `e.message` on a FetchError is just "409 Conflict"; the shared
        // helper returns the server's own reason (or the fallback sentinel,
        // which the chart maps to the generic connectivity hint).
        lastError.value = errorMessage(e, 'save_failed')
      } finally {
        saving.value = false
      }
    }
  }

  function _schedule(
    key: string,
    patch: Record<string, unknown>,
    exec: (payload: Record<string, unknown>) => Promise<void>
  ) {
    dirty.value = true
    const merged = { ...(pendingPayloads.get(key) ?? {}), ...patch }
    pendingPayloads.set(key, merged)
    const prev = pendingTimers.get(key)
    if (prev) clearTimeout(prev)
    pendingTimers.set(key, setTimeout(_flushKey(key, exec), DEBOUNCE_MS))
  }

  function patchTooth(snapshotId: string, toothNumber: number, patch: ToothPatch) {
    _schedule(`tooth:${toothNumber}`, patch as Record<string, unknown>, async (payload) => {
      await api.patch<ApiResponse<PerioTooth>>(
        `/api/v1/periodontogram/snapshots/${snapshotId}/teeth/${toothNumber}`,
        payload,
        // Silent: a failed autosave is reported exactly once, via `lastError`.
        { silent: true }
      )
    })
  }

  function patchSite(
    snapshotId: string,
    toothNumber: number,
    siteCode: SiteCode,
    patch: SitePatch
  ) {
    _schedule(
      `site:${toothNumber}:${siteCode}`,
      patch as Record<string, unknown>,
      async (payload) => {
        await api.patch<ApiResponse<PerioSite>>(
          `/api/v1/periodontogram/snapshots/${snapshotId}/teeth/${toothNumber}/sites/${siteCode}`,
          payload,
          // Silent: a failed autosave is reported exactly once, via `lastError`.
          { silent: true }
        )
      }
    )
  }

  async function flushPending(snapshotId: string): Promise<void> {
    const timers = Array.from(pendingTimers.entries())
    for (const [key, timer] of timers) {
      clearTimeout(timer)
      pendingTimers.delete(key)
      const payload = pendingPayloads.get(key)
      if (!payload) continue
      pendingPayloads.delete(key)
      saving.value = true
      try {
        if (key.startsWith('tooth:')) {
          const toothNumber = Number(key.slice('tooth:'.length))
          await api.patch(
            `/api/v1/periodontogram/snapshots/${snapshotId}/teeth/${toothNumber}`,
            payload,
            { silent: true }
          )
        } else if (key.startsWith('site:')) {
          const [, toothStr, siteCode] = key.split(':')
          await api.patch(
            `/api/v1/periodontogram/snapshots/${snapshotId}/teeth/${toothStr}/sites/${siteCode}`,
            payload,
            { silent: true }
          )
        }
      } catch (e) {
        // `e.message` on a FetchError is just "409 Conflict"; the shared
        // helper returns the server's own reason (or the fallback sentinel,
        // which the chart maps to the generic connectivity hint).
        lastError.value = errorMessage(e, 'save_failed')
      } finally {
        saving.value = false
      }
    }
    dirty.value = false
  }

  async function closeSession(snapshotId: string, notes?: string): Promise<PerioSnapshotDetail> {
    saving.value = true
    lastError.value = null
    try {
      const response = await api.post<ApiResponse<PerioSnapshotDetail>>(
        `/api/v1/periodontogram/snapshots/${snapshotId}/close`,
        { notes: notes ?? null },
        { silent: true }
      )
      dirty.value = false
      return response.data
    } catch (e) {
      // Was try/finally with no catch: a 409 (snapshot already closed) or a
      // 422 dismissed the dialog, left the session a draft and told the
      // clinician nothing at all. `lastError` drives the one save-failed
      // toast; the rejection is rethrown so the caller cannot mistake this
      // for a successful close and emit `closed`.
      lastError.value = errorMessage(e, 'save_failed')
      throw e
    } finally {
      saving.value = false
    }
  }

  async function discardDraft(snapshotId: string): Promise<void> {
    saving.value = true
    lastError.value = null
    try {
      await api.del(`/api/v1/periodontogram/snapshots/${snapshotId}`, { silent: true })
      dirty.value = false
    } catch (e) {
      // Same as closeSession: a conflict or a vanished draft must be visible,
      // and the caller must not emit `discarded`.
      lastError.value = errorMessage(e, 'save_failed')
      throw e
    } finally {
      saving.value = false
    }
  }

  return {
    saving,
    dirty,
    lastError,
    patchTooth,
    patchSite,
    flushPending,
    closeSession,
    discardDraft
  }
}
