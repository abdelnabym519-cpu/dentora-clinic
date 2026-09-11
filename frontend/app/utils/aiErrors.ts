/**
 * Map a failed clinical-AI API call to an actionable user-facing message.
 *
 * The clinical-AI modules surface distinct, meaningful failure modes and
 * the UI must not collapse them into "something went wrong":
 *
 * - 503 with `detail = { code: '<module>_provider_unavailable', message }`
 *   → the LLM provider itself is not configured/reachable; `message` comes
 *   straight from the provider factory (e.g. "OpenAI provider selected but
 *   OPENAI_API_KEY is not configured").
 * - 409 with `detail = { code: 'clinical_context_insufficient', missing_or_stale }`
 *   → a clinical readiness gate rejected the request.
 * - 409 (string detail) → e.g. dentist-review state conflicts.
 * - 403 → dentist-control enforcement (role not allowed to trigger AI).
 * - 502 → the provider answered but its output failed contract validation.
 * - anything else → the shared `errorMessage` fallback chain.
 */
import { errorMessage } from './error'

export function aiActionableError(e: unknown, fallback: string): string {
  if (typeof e === 'object' && e !== null) {
    const err = e as {
      statusCode?: number
      status?: number
      data?: { detail?: unknown, message?: unknown, errors?: unknown }
    }
    const status = err.statusCode ?? err.status
    const detail = err.data?.detail

    if (typeof detail === 'object' && detail !== null) {
      const d = detail as { code?: unknown, message?: unknown, missing_or_stale?: unknown }
      const code = typeof d.code === 'string' ? d.code : ''
      if (status === 503 && code.endsWith('_provider_unavailable')) {
        return typeof d.message === 'string' && d.message
          ? `AI provider unavailable: ${d.message}`
          : 'AI provider unavailable. Configure a provider in Settings → Copilot.'
      }
      if (status === 409 && code === 'clinical_context_insufficient') {
        const missing = Array.isArray(d.missing_or_stale) ? d.missing_or_stale.join(', ') : ''
        return missing
          ? `Clinical readiness gate not satisfied. Missing or stale: ${missing}.`
          : 'Clinical readiness gate not satisfied.'
      }
      if (code === 'dentist_control_required') {
        return 'Clinical Copilot advisories are restricted to dentist accounts (dentist control is enforced by the safety architecture).'
      }
      if (typeof d.message === 'string' && d.message) return d.message
      if (code) return code.replaceAll('_', ' ')
    }

    if (status === 502) {
      return 'The AI provider response failed contract validation and was discarded. No result was stored.'
    }
    if (status === 403) {
      return typeof detail === 'string' && detail ? detail : 'Dentist review/control is required for this action.'
    }
    if (status === 409 && typeof detail === 'string' && detail) return detail

    return errorMessage(e, fallback)
  }
  return fallback
}
