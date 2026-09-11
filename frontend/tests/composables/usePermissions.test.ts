import { describe, expect, it, beforeEach } from 'vitest'
import { useState } from '#app'
import { PERMISSIONS } from '~/config/permissions'

/**
 * ``usePermissions`` reads the grant list ``useAuth`` stores in
 * ``auth:permissions`` — the same state the app runs on, so no mocking is
 * needed to exercise the real gating path.
 */
function setGrants(grants: string[]): void {
  const state = useState<string[]>('auth:permissions', () => [])
  state.value = grants
}

describe('usePermissions', () => {
  beforeEach(() => setGrants([]))

  it('gates an exact grant and denies everything else', async () => {
    setGrants([PERMISSIONS.patients.read, PERMISSIONS.verifactu.recordsRead])
    const { usePermissions } = await import('~/composables/usePermissions')
    const { can } = usePermissions()

    expect(can(PERMISSIONS.patients.read)).toBe(true)
    expect(can(PERMISSIONS.patients.write)).toBe(false)
    // The exact mismatch behind the reported bug: holding a Veri*Factu
    // records grant says nothing about the settings-scope health probe.
    expect(can(PERMISSIONS.verifactu.recordsRead)).toBe(true)
    expect(can(PERMISSIONS.verifactu.settingsRead)).toBe(false)
  })

  it('expands the wildcards the backend can hand out', async () => {
    setGrants(['dental_3d.*', '*'])
    const { usePermissions } = await import('~/composables/usePermissions')
    const { can, canAny, canAll } = usePermissions()

    expect(can(PERMISSIONS.dental3d.read)).toBe(true)
    expect(can(PERMISSIONS.dental3d.write)).toBe(true)
    expect(can('some.future.permission')).toBe(true)
    expect(canAny(['nope.never'])).toBe(true)
    expect(canAll([PERMISSIONS.dental3d.read, 'anything.at.all'])).toBe(true)
  })

  it('keeps module wildcards from leaking into other modules', async () => {
    setGrants(['risk_engine.*'])
    const { usePermissions } = await import('~/composables/usePermissions')
    const { can, canAll } = usePermissions()

    expect(can(PERMISSIONS.riskEngine.review)).toBe(true)
    expect(can(PERMISSIONS.dental3d.read)).toBe(false)
    expect(can(PERMISSIONS.verifactu.settingsRead)).toBe(false)
    expect(canAll([PERMISSIONS.riskEngine.read, PERMISSIONS.verifactu.settingsRead])).toBe(false)
  })

  it('derives isAdmin from the users.write grant only', async () => {
    const { usePermissions } = await import('~/composables/usePermissions')

    setGrants([PERMISSIONS.patients.write])
    expect(usePermissions().isAdmin.value).toBe(false)

    setGrants([PERMISSIONS.users.write])
    expect(usePermissions().isAdmin.value).toBe(true)
  })
})
