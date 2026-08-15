import { describe, expect, it } from 'vitest'
import { formatTrialRemaining, getTrialStatus } from '~/utils/trial'

describe('getTrialStatus', () => {
  it('keeps paid/offline installations unlimited', () => {
    const trial = getTrialStatus(
      { trialMode: false, trialStartedAt: '', trialDays: 3 },
      new Date('2026-08-15T12:00:00Z')
    )

    expect(trial.enabled).toBe(false)
    expect(trial.expired).toBe(false)
    expect(trial.expiresAt).toBeNull()
  })

  it('expires exactly three days after the pinned start timestamp', () => {
    const active = getTrialStatus(
      { trialMode: true, trialStartedAt: '2026-08-15T12:00:00Z', trialDays: 3 },
      new Date('2026-08-18T11:59:00Z')
    )
    const expired = getTrialStatus(
      { trialMode: true, trialStartedAt: '2026-08-15T12:00:00Z', trialDays: 3 },
      new Date('2026-08-18T12:00:00Z')
    )

    expect(active.expired).toBe(false)
    expect(active.remainingMs).toBe(60_000)
    expect(expired.expired).toBe(true)
    expect(expired.remainingMs).toBe(0)
  })
})

describe('formatTrialRemaining', () => {
  it('formats Arabic and default countdowns', () => {
    const remaining = (26 * 60 + 5) * 60_000

    expect(formatTrialRemaining(remaining)).toBe('1d 2h')
    expect(formatTrialRemaining(remaining, true)).toBe('1 يوم و2 ساعة')
  })
})
