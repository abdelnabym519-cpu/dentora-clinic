import type { Appointment, AppointmentCreate, AppointmentStatus, AppointmentUpdate, PaginatedResponse, ApiResponse } from '~~/app/types'
import { errorMessage, errorStatus } from '~~/app/utils/error'
import { useSharedLatestGuard } from '~~/app/utils/latestGuard'

export interface FetchAppointmentsOptions {
  /**
   * Suppress the shared error toast. Background refreshes (the kanban
   * polls every 30 s and on tab focus) must not stack one toast per tick
   * for a failure the user did not trigger; the board renders
   * ``error`` inline instead. Explicit loads keep the default.
   */
  silent?: boolean
}

export function useAppointments() {
  const api = useApi()
  const { t } = useI18n()

  // State
  const appointments = useState<Appointment[]>('appointments:list', () => [])
  const isLoading = useState<boolean>('appointments:loading', () => false)
  const error = useState<string | null>('appointments:error', () => null)

  // Whenever the loaded appointments change (initial fetch, navigation,
  // mutation), refresh the "has notes" indicator for the new id set.
  // Guarded by a single ``useState`` flag so the watcher is wired
  // exactly once across the whole app, regardless of how many
  // components call ``useAppointments``.
  if (import.meta.client) {
    const wired = useState<boolean>('appointments:notes-indicator-wired', () => false)
    if (!wired.value) {
      wired.value = true
      const notesIndicator = useAppointmentNotesIndicator()
      watch(
        appointments,
        (list) => {
          notesIndicator.fetchFor(list.map(a => a.id))
        },
        { immediate: true }
      )
    }
  }

  // The board re-reads the day on every date click, on the 30 s poll and on
  // tab focus. Those overlap: a slow answer for the day the user left must not
  // replace the day now on the board. The list lives in `useState`, so the
  // counter has to be shared by every component that reads it.
  const appointmentsGuard = useSharedLatestGuard('appointments:list')

  // Actions
  async function fetchAppointments(
    startDate: Date,
    endDate: Date,
    options: FetchAppointmentsOptions = {}
  ): Promise<Appointment[]> {
    const isLatest = appointmentsGuard.begin()
    isLoading.value = true
    error.value = null

    try {
      const params = new URLSearchParams({
        start_date: startDate.toISOString(),
        end_date: endDate.toISOString(),
        page_size: '500'
      })

      const response = await api.get<PaginatedResponse<Appointment>>(
        `/api/v1/agenda/appointments?${params.toString()}`,
        { silent: options.silent === true, operation: t('appointments.title') }
      )

      if (isLatest()) appointments.value = response.data ?? []
      return response.data ?? []
    } catch (e) {
      if (!isLatest()) return []
      // Was a hardcoded English string that also dropped the backend's
      // reason. `error` is rendered inline by the board, so it has to be
      // localized and specific: the server's own detail for an HTTP
      // failure, the localized network message when no response arrived.
      error.value = errorStatus(e) === undefined
        ? t('common.networkError')
        : errorMessage(e, t('appointments.loadFailed'))
      console.error('Failed to fetch appointments:', e)
      return []
    } finally {
      isLoading.value = false
    }
  }

  async function createAppointment(data: AppointmentCreate): Promise<Appointment> {
    const response = await api.post<ApiResponse<Appointment>>(
      '/api/v1/agenda/appointments',
      data
    )

    // Add to local state
    appointments.value = [...appointments.value, response.data]

    return response.data
  }

  async function updateAppointment(id: string, data: AppointmentUpdate): Promise<Appointment> {
    const response = await api.put<ApiResponse<Appointment>>(
      `/api/v1/agenda/appointments/${id}`,
      data
    )

    // Update local state
    appointments.value = appointments.value.map(apt =>
      apt.id === id ? response.data : apt
    )

    return response.data
  }

  async function cancelAppointment(id: string): Promise<void> {
    await api.del(`/api/v1/agenda/appointments/${id}`)

    // Update local state - mark as cancelled
    appointments.value = appointments.value.map(apt =>
      apt.id === id ? { ...apt, status: 'cancelled' as const } : apt
    )
  }

  async function updateAppointmentStatus(id: string, status: Appointment['status']): Promise<Appointment> {
    return await updateAppointment(id, { status })
  }

  /**
   * Assign, reassign or unassign (``cabinet_id=null``) a cabinet.
   * Optimistic local update + rollback on failure.
   */
  async function assignCabinet(
    id: string,
    cabinetId: string | null,
    note?: string
  ): Promise<Appointment> {
    const previous = appointments.value.find(apt => apt.id === id)
    const optimisticNow = new Date().toISOString()

    if (previous) {
      appointments.value = appointments.value.map(apt =>
        apt.id === id
          ? {
              ...apt,
              cabinet_id: cabinetId,
              cabinet: cabinetId === null ? null : apt.cabinet,
              cabinet_assigned_at: cabinetId === null ? null : optimisticNow
            }
          : apt
      )
    }

    try {
      const response = await api.patch<ApiResponse<Appointment>>(
        `/api/v1/agenda/appointments/${id}/cabinet`,
        { cabinet_id: cabinetId, note: note ?? null }
      )
      appointments.value = appointments.value.map(apt =>
        apt.id === id ? response.data : apt
      )
      return response.data
    } catch (err) {
      if (previous) {
        appointments.value = appointments.value.map(apt =>
          apt.id === id ? previous : apt
        )
      }
      throw err
    }
  }

  /**
   * Transition an appointment through the status lifecycle. Updates the
   * local list optimistically (``status`` + ``current_status_since``) and
   * rolls back on failure. Returns the server's authoritative response.
   */
  async function transition(
    id: string,
    to: AppointmentStatus,
    note?: string
  ): Promise<Appointment> {
    const previous = appointments.value.find(apt => apt.id === id)
    const optimisticSince = new Date().toISOString()

    if (previous) {
      appointments.value = appointments.value.map(apt =>
        apt.id === id
          ? { ...apt, status: to, current_status_since: optimisticSince }
          : apt
      )
    }

    try {
      const response = await api.post<ApiResponse<Appointment>>(
        `/api/v1/agenda/appointments/${id}/transitions`,
        { to_status: to, note: note ?? null }
      )
      appointments.value = appointments.value.map(apt =>
        apt.id === id ? response.data : apt
      )
      return response.data
    } catch (err) {
      if (previous) {
        appointments.value = appointments.value.map(apt =>
          apt.id === id ? previous : apt
        )
      }
      throw err
    }
  }

  return {
    appointments: readonly(appointments),
    isLoading: readonly(isLoading),
    error: readonly(error),
    fetchAppointments,
    createAppointment,
    updateAppointment,
    cancelAppointment,
    updateAppointmentStatus,
    transition,
    assignCabinet
  }
}
