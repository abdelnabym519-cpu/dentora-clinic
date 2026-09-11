import { describe, expect, it, vi } from 'vitest'

// usePermissions derives its grant list from useAuth(). Mock the auth
// store per-case so each scenario controls the granted permission list.
const grants = { value: [] as string[] }

vi.mock('~/composables/useAuth', () => ({
  useAuth: () => ({
    permissions: grants
  })
}))

describe('usePermissions wildcard handling (mirrors backend permission_matches)', () => {
  it('expands module wildcards granted to the admin role', async () => {
    grants.value = ['case_intelligence.*', 'dental_3d.*', 'copilot.*', 'ai_case_summary.read']
    const { usePermissions } = await import('~/composables/usePermissions')
    const { can } = usePermissions()
    expect(can('case_intelligence.read')).toBe(true)
    expect(can('dental_3d.write')).toBe(true)
    expect(can('copilot.chat')).toBe(true)
    expect(can('ai_case_summary.read')).toBe(true)
    // no cross-module wildcard leakage
    expect(can('risk_engine.review')).toBe(false)
  })

  it('honours exact grants and the global wildcard', async () => {
    grants.value = ['risk_engine.read', '*']
    const { usePermissions } = await import('~/composables/usePermissions')
    const { can, canAny, canAll } = usePermissions()
    expect(can('risk_engine.read')).toBe(true)
    expect(can('anything.at.all')).toBe(true)
    expect(canAny(['nope.never', 'risk_engine.read'])).toBe(true)
    // the global "*" grant covers everything, matching the backend
    expect(canAny(['nope.never'])).toBe(true)
    expect(canAll(['risk_engine.read', 'anything.at.all'])).toBe(true)
  })

  it('keeps dentist action gates exact (no accidental grants)', async () => {
    grants.value = [
      'ai_case_summary.read',
      'ai_case_summary.generate',
      'risk_engine.review'
    ]
    const { usePermissions } = await import('~/composables/usePermissions')
    const { can } = usePermissions()
    expect(can('ai_case_summary.generate')).toBe(true)
    expect(can('ai_case_summary.review')).toBe(false)
    expect(can('risk_engine.review')).toBe(true)
    expect(can('clinical_copilot.use')).toBe(false)
  })
})
