import type { Appointment, PaginatedResponse } from '~~/app/types'
import { useSharedLatestGuard } from '~~/app/utils/latestGuard'

/**
 * Shared state for agenda widgets on the home dashboard. Today's and
 * tomorrow's appointments are fetched once per range and reused across
 * the KPI tiles, timeline strip and unconfirmed panel.
 *
 * ERROR CONTRACT — these are ambient widgets, not user operations:
 *   - the requests are ``silent``, so a failure never becomes a global
 *     toast attributed to whatever the user is doing elsewhere (the
 *     "In clinic now" tile re-polls every 60 s and would otherwise stack
 *     one toast per tick);
 *   - a failure sets ``todayError`` / ``tomorrowError`` instead of being
 *     flattened into an empty list, because "0 appointments" and "we
 *     could not load" are different statements and the tiles must not
 *     render the first one when the second is true.
 */
export function useHomeAgenda() {
  const api = useApi()

  const todayAppointments = useState<Appointment[]>('agenda.home:today', () => [])
  const tomorrowUnconfirmed = useState<Appointment[]>('agenda.home:tomorrow-unconfirmed', () => [])
  const todayLoaded = useState<boolean>('agenda.home:today-loaded', () => false)
  const tomorrowLoaded = useState<boolean>('agenda.home:tomorrow-loaded', () => false)
  const todayError = useState<boolean>('agenda.home:today-error', () => false)
  const tomorrowError = useState<boolean>('agenda.home:tomorrow-error', () => false)

  function rangeFor(offsetDays: number): { start: string, end: string } {
    const now = new Date()
    const base = new Date(now.getFullYear(), now.getMonth(), now.getDate() + offsetDays)
    const start = base.toISOString()
    const end = new Date(base.getFullYear(), base.getMonth(), base.getDate(), 23, 59, 59).toISOString()
    return { start, end }
  }

  // The home tiles re-read on a 30 s poll and on tab focus. Overlapping polls
  // are the norm, and a stale failure would otherwise raise the error flag on
  // top of a newer success (or stale rows on top of newer ones). The tiles are
  // `useState`, so the counters are shared with every component reading them.
  const todayGuard = useSharedLatestGuard('agenda.home:today')
  const tomorrowGuard = useSharedLatestGuard('agenda.home:tomorrow')

  async function fetchToday(): Promise<Appointment[]> {
    const { start, end } = rangeFor(0)
    const isLatest = todayGuard.begin()
    try {
      const res = await api.get<PaginatedResponse<Appointment>>(
        `/api/v1/agenda/appointments?start_date=${start}&end_date=${end}&page_size=500`,
        { silent: true }
      )
      if (!isLatest()) return todayAppointments.value
      todayAppointments.value = res.data ?? []
      todayError.value = false
    } catch {
      if (!isLatest()) return todayAppointments.value
      todayAppointments.value = []
      todayError.value = true
    } finally {
      if (isLatest()) todayLoaded.value = true
    }
    return todayAppointments.value
  }

  async function fetchTomorrowUnconfirmed(): Promise<Appointment[]> {
    const { start, end } = rangeFor(1)
    const isLatest = tomorrowGuard.begin()
    try {
      const res = await api.get<PaginatedResponse<Appointment>>(
        `/api/v1/agenda/appointments?start_date=${start}&end_date=${end}&status=scheduled&page_size=500`,
        { silent: true }
      )
      if (!isLatest()) return tomorrowUnconfirmed.value
      tomorrowUnconfirmed.value = res.data ?? []
      tomorrowError.value = false
    } catch {
      if (!isLatest()) return tomorrowUnconfirmed.value
      tomorrowUnconfirmed.value = []
      tomorrowError.value = true
    } finally {
      if (isLatest()) tomorrowLoaded.value = true
    }
    return tomorrowUnconfirmed.value
  }

  function replaceTodayAppointment(updated: Appointment): void {
    todayAppointments.value = todayAppointments.value.map(a =>
      a.id === updated.id ? updated : a
    )
  }

  function removeTomorrowUnconfirmed(id: string): void {
    tomorrowUnconfirmed.value = tomorrowUnconfirmed.value.filter(a => a.id !== id)
  }

  return {
    todayAppointments: readonly(todayAppointments),
    tomorrowUnconfirmed: readonly(tomorrowUnconfirmed),
    todayLoaded: readonly(todayLoaded),
    tomorrowLoaded: readonly(tomorrowLoaded),
    todayError: readonly(todayError),
    tomorrowError: readonly(tomorrowError),
    fetchToday,
    fetchTomorrowUnconfirmed,
    replaceTodayAppointment,
    removeTomorrowUnconfirmed
  }
}
