import { describe, expect, it } from 'vitest'
import { isGranted, permissionMatches } from '~/utils/permissions'

/**
 * The frontend must resolve grants exactly like the backend's
 * ``permission_matches`` — otherwise the UI hides actions the API would
 * accept (dead buttons) or offers actions that can only answer 403.
 */
describe('permissionMatches', () => {
  it('matches exact grants', () => {
    expect(permissionMatches('verifactu.settings.read', 'verifactu.settings.read')).toBe(true)
    expect(permissionMatches('verifactu.settings.read', 'verifactu.settings.configure')).toBe(false)
  })

  it('honours the global wildcard', () => {
    expect(permissionMatches('anything.at.all', '*')).toBe(true)
  })

  it('honours module wildcards without leaking across modules', () => {
    expect(permissionMatches('dental_3d.write', 'dental_3d.*')).toBe(true)
    expect(permissionMatches('dental_3d.read', 'risk_engine.*')).toBe(false)
    // Prefix matching must respect the dot boundary.
    expect(permissionMatches('verifactu2.settings.read', 'verifactu.*')).toBe(false)
    expect(permissionMatches('verifactu.settings.read', 'verifactu.settings.*')).toBe(true)
    expect(permissionMatches('verifactu.queue.manage', 'verifactu.settings.*')).toBe(false)
  })

  it('does not treat a required wildcard as satisfied by a narrower grant', () => {
    expect(permissionMatches('verifactu.*', 'verifactu.settings.read')).toBe(false)
  })
})

describe('isGranted', () => {
  it('scans the whole grant list', () => {
    const grants = ['patients.read', 'agenda.*', 'verifactu.records.read']
    expect(isGranted('patients.read', grants)).toBe(true)
    expect(isGranted('agenda.appointments.write', grants)).toBe(true)
    expect(isGranted('verifactu.records.read', grants)).toBe(true)
    expect(isGranted('verifactu.settings.read', grants)).toBe(false)
  })

  it('denies everything for an empty grant list', () => {
    expect(isGranted('patients.read', [])).toBe(false)
  })
})
