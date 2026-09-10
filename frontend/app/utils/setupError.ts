/**
 * Map a failed `/api/v1/auth/setup` request to a user-facing message.
 *
 * The backend can fail the setup POST in several shapes, and the browser
 * can fail it before any response arrives (CORS / network). This mapper
 * keeps the setup page honest about WHICH failure happened instead of
 * always showing the generic fallback:
 *
 * - FastAPI/pydantic 422 → `data.detail` is an ARRAY of validation objects
 *   → surface the first `msg` (with its field) as plain text.
 * - HTTPException (weak password, …) → the app's `ErrorResponse` envelope
 *   `{ data, message, errors }` → surface `message` / `errors[0]`.
 * - 409 → the system is already initialized (localized key).
 * - No `statusCode` at all → the request never completed (offline,
 *   CORS-blocked, backend down) → localized key with remediation hints.
 * - Anything else → the localized generic fallback.
 */
export type SetupErrorShape = {
  statusCode?: number
  data?: {
    detail?: unknown
    message?: unknown
    errors?: unknown
  }
}

export type MappedSetupError = { key: string } | { text: string }

function firstDetailText(detail: unknown): string | undefined {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: unknown, loc?: unknown }
    if (typeof first?.msg === 'string') {
      const loc = Array.isArray(first.loc) ? (first.loc as unknown[]) : []
      const field = loc.length > 0 ? String(loc[loc.length - 1]!) : undefined
      // Skip the leading "Value error, " / "Assertion failed, " wrapper
      // pydantic adds for custom validators; keep the human part.
      const msg = first.msg.replace(/^(Value error, |Assertion failed, )/, '')
      return field && field !== 'body' ? `${field}: ${msg}` : msg
    }
  }
  return undefined
}

function envelopeText(data: SetupErrorShape['data']): string | undefined {
  if (typeof data?.message === 'string' && data.message.trim() !== '') {
    return data.message
  }
  if (Array.isArray(data?.errors) && typeof data.errors[0] === 'string') {
    return data.errors[0]
  }
  return undefined
}

export function mapSetupError(error: SetupErrorShape): MappedSetupError {
  const { statusCode } = error

  if (statusCode === undefined) {
    // ofetch only omits statusCode when the request never completed:
    // backend down, wrong API_BASE_URL, or a CORS-blocked response.
    return { key: 'setup.networkError' }
  }

  if (statusCode === 409) {
    return { key: 'setup.alreadyInitialized' }
  }

  const detailText = firstDetailText(error.data?.detail)
  if (detailText !== undefined) {
    return { text: detailText }
  }

  const envelope = envelopeText(error.data)
  if (envelope !== undefined) {
    return { text: envelope }
  }

  return { key: 'setup.error' }
}
