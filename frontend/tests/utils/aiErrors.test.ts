import { describe, expect, it } from 'vitest'
import { aiActionableError } from '../../app/utils/aiErrors'

// The activation mission requires meaningful AI failure states: provider
// misconfiguration, clinical readiness gates and dentist-control enforcement
// must surface actionable text instead of a generic failure.

function httpError(status: number, detail: unknown) {
  return { statusCode: status, data: { detail } }
}

describe('aiActionableError', () => {
  it('surfaces the provider-unavailable 503 state with the factory message', () => {
    const msg = aiActionableError(
      httpError(503, {
        code: 'ai_case_summary_provider_unavailable',
        message: 'OpenAI provider selected but OPENAI_API_KEY is not configured'
      }),
      'fallback'
    )
    expect(msg).toBe(
      'AI provider unavailable: OpenAI provider selected but OPENAI_API_KEY is not configured'
    )
  })

  it('names the missing clinical readiness inputs on 409', () => {
    const msg = aiActionableError(
      httpError(409, {
        code: 'clinical_context_insufficient',
        missing_or_stale: ['risk_engine', 'planning']
      }),
      'fallback'
    )
    expect(msg).toBe(
      'Clinical readiness gate not satisfied. Missing or stale: risk_engine, planning.'
    )
  })

  it('explains dentist-control enforcement instead of printing a code', () => {
    const msg = aiActionableError(httpError(403, { code: 'dentist_control_required' }), 'fallback')
    expect(msg).toContain('restricted to dentist accounts')
  })

  it('distinguishes provider output validation failures (502)', () => {
    const msg = aiActionableError(httpError(502, 'AI summary provider failed validation'), 'fallback')
    expect(msg).toContain('failed contract validation')
    expect(msg).toContain('No result was stored')
  })

  it('falls back to the shared error chain for plain string details', () => {
    const msg = aiActionableError(httpError(409, 'summary_already_reviewed'), 'fallback')
    expect(msg).toBe('summary_already_reviewed')
  })

  it('uses the shared error chain when nothing structured is present', () => {
    const msg = aiActionableError(new Error('network down'), 'AI request failed.')
    expect(msg).toBe('network down')
  })
})
