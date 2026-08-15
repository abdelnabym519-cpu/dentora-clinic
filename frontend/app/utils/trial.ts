export interface TrialStatus {
  enabled: boolean
  startedAt: Date | null
  expiresAt: Date | null
  expired: boolean
  remainingMs: number | null
}

interface TrialRuntimeConfig {
  trialMode?: boolean
  trialStartedAt?: string
  trialDays?: number | string
}

export function getTrialStatus(
  config: TrialRuntimeConfig,
  now = new Date()
): TrialStatus {
  const startedRaw = String(config.trialStartedAt || '').trim()
  if (!config.trialMode || !startedRaw) {
    return {
      enabled: false,
      startedAt: null,
      expiresAt: null,
      expired: false,
      remainingMs: null
    }
  }

  const startedAt = new Date(startedRaw)
  if (Number.isNaN(startedAt.getTime())) {
    return {
      enabled: false,
      startedAt: null,
      expiresAt: null,
      expired: false,
      remainingMs: null
    }
  }

  const parsedDays = Number(config.trialDays ?? 3)
  const days = Number.isFinite(parsedDays) && parsedDays > 0 ? parsedDays : 3
  const expiresAt = new Date(startedAt.getTime() + days * 24 * 60 * 60 * 1000)
  const remainingMs = Math.max(0, expiresAt.getTime() - now.getTime())

  return {
    enabled: true,
    startedAt,
    expiresAt,
    expired: now.getTime() >= expiresAt.getTime(),
    remainingMs
  }
}

export function formatTrialRemaining(remainingMs: number, arabic = false): string {
  const totalMinutes = Math.max(0, Math.ceil(remainingMs / 60_000))
  const days = Math.floor(totalMinutes / (24 * 60))
  const hours = Math.floor((totalMinutes % (24 * 60)) / 60)
  const minutes = totalMinutes % 60

  if (arabic) {
    if (days > 0) return `${days} يوم و${hours} ساعة`
    if (hours > 0) return `${hours} ساعة و${minutes} دقيقة`
    return `${minutes} دقيقة`
  }

  if (days > 0) return `${days}d ${hours}h`
  if (hours > 0) return `${hours}h ${minutes}m`
  return `${minutes}m`
}
