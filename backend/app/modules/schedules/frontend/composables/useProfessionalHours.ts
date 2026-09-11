import type { ApiResponse } from '~~/app/types'
import type { Shift, WeekdayShifts } from './useClinicHours'

export interface ProfessionalHours {
  id: string
  clinic_id: string
  user_id: string
  is_active: boolean
  days: WeekdayShifts[]
}

export interface ProfessionalOverride {
  id: string
  clinic_id: string
  user_id: string
  start_date: string
  end_date: string
  kind: 'unavailable' | 'custom_hours'
  reason: string | null
  shifts: Shift[]
}

export interface ProfessionalOverridePayload {
  start_date: string
  end_date: string
  kind: 'unavailable' | 'custom_hours'
  reason?: string | null
  shifts: { start_time: string, end_time: string }[]
}

export function useProfessionalHours() {
  const api = useApi()

  async function fetchHours(userId: string): Promise<ProfessionalHours> {
    const res = await api.get<ApiResponse<ProfessionalHours>>(`/api/v1/schedules/professionals/${userId}/hours`, { silent: true })
    return res.data
  }

  async function updateHours(userId: string, days: WeekdayShifts[]): Promise<ProfessionalHours> {
    const res = await api.put<ApiResponse<ProfessionalHours>>(`/api/v1/schedules/professionals/${userId}/hours`, { days }, { silent: true })
    return res.data
  }

  async function fetchOverrides(userId: string, params?: { start?: string, end?: string }): Promise<ProfessionalOverride[]> {
    const query = new URLSearchParams()
    if (params?.start) query.set('start', params.start)
    if (params?.end) query.set('end', params.end)
    const url = query.toString()
      ? `/api/v1/schedules/professionals/${userId}/overrides?${query.toString()}`
      : `/api/v1/schedules/professionals/${userId}/overrides`
    const res = await api.get<ApiResponse<ProfessionalOverride[]>>(url, { silent: true })
    return res.data
  }

  async function createOverride(userId: string, payload: ProfessionalOverridePayload): Promise<ProfessionalOverride> {
    const res = await api.post<ApiResponse<ProfessionalOverride>>(`/api/v1/schedules/professionals/${userId}/overrides`, payload, { silent: true })
    return res.data
  }

  async function updateOverride(userId: string, id: string, payload: ProfessionalOverridePayload): Promise<ProfessionalOverride> {
    const res = await api.put<ApiResponse<ProfessionalOverride>>(`/api/v1/schedules/professionals/${userId}/overrides/${id}`, payload, { silent: true })
    return res.data
  }

  async function deleteOverride(userId: string, id: string): Promise<void> {
    await api.del(`/api/v1/schedules/professionals/${userId}/overrides/${id}`, { silent: true })
  }

  return {
    fetchHours,
    updateHours,
    fetchOverrides,
    createOverride,
    updateOverride,
    deleteOverride
  }
}
