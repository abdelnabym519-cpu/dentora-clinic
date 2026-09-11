/**
 * Narrow `unknown` thrown by `useApi` / `$fetch` to a user-facing message.
 * Reads, in order: `.data.detail`, `.data.message`, `.message`. Falls back
 * to the provided default.
 *
 * `errorDetail` decides which shapes are usable; a FastAPI 422 validation
 * *list* is not, so callers keep their own field-level fallback there.
 */
export function errorMessage(e: unknown, fallback: string): string {
  if (typeof e === 'object' && e !== null) {
    return errorDetail(e) ?? (e as { message?: string }).message ?? fallback
  }
  return fallback
}

/**
 * The server's own explanation, or `undefined` when the failure carries
 * none (network drop, thrown `Error`). Use it as a toast `description`
 * under an already-localized `title`: passing `undefined` leaves the
 * toast exactly as it was before, so a generic title never gains an
 * empty second line.
 *
 * Two backend shapes are understood:
 * - ``detail: "Dentist review is required"`` — FastAPI's default and what
 *   the clinical modules raise for readiness gates and conflicts;
 * - ``detail: { code, message, missing_or_stale }`` — the structured
 *   contract the clinical-AI modules use for provider/readiness failures.
 *   The ``message`` is the actionable part, and ``missing_or_stale`` names
 *   the exact prerequisites, so both are surfaced.
 *
 * A *list* detail is FastAPI's 422 validation payload: rendering it yields
 * "[object Object]", so it stays `undefined` and callers fall back to
 * their own field-level messages.
 */
export function errorDetail(e: unknown): string | undefined {
  if (typeof e !== 'object' || e === null) return undefined
  const obj = e as { data?: { detail?: unknown, message?: unknown } }
  const detail = obj.data?.detail

  if (typeof detail === 'string') return detail

  if (typeof detail === 'object' && detail !== null && !Array.isArray(detail)) {
    const structured = detail as {
      message?: unknown
      code?: unknown
      missing_or_stale?: unknown
    }
    if (typeof structured.message === 'string' && structured.message) {
      const missing = Array.isArray(structured.missing_or_stale)
        ? structured.missing_or_stale.filter(Boolean).join(', ')
        : ''
      return missing ? `${structured.message} (${missing})` : structured.message
    }
    if (typeof structured.code === 'string' && structured.code) {
      return structured.code.replaceAll('_', ' ')
    }
  }

  if (typeof obj.data?.message === 'string') return obj.data.message
  return undefined
}

export function errorStatus(e: unknown): number | undefined {
  if (typeof e === 'object' && e !== null) {
    const err = e as { statusCode?: number, status?: number }
    return err.statusCode ?? err.status
  }
  return undefined
}

/** True when the backend rejected the request for lack of authorization. */
export function isPermissionDenied(e: unknown): boolean {
  return errorStatus(e) === 403
}

/**
 * The permission an authorization failure names, when the backend
 * supplied one. ``require_permission`` answers 403 with
 * ``detail: "Permission denied: verifactu.settings.read"`` — surfacing
 * that grant lets the UI state exactly what is missing instead of a
 * generic "Access denied" that reads as if the whole screen were
 * forbidden.
 */
export function errorPermission(e: unknown): string | undefined {
  const detail = errorDetail(e)
  if (!detail) return undefined
  const match = /^Permission denied:\s*(.+)$/i.exec(detail.trim())
  return match?.[1]?.trim() || undefined
}
