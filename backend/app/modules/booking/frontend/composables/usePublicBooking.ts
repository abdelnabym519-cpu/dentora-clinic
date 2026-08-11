export interface PublicBookingClinic {
  clinic_name: string
  clinic_phone: string | null
  clinic_email: string | null
  timezone: string
  currency: string
  slot_minutes: number
  days_ahead: number
}

export interface PublicProfessional {
  id: string
  first_name: string
  last_name: string
}

export interface PublicBookableSlot {
  start: string
  end: string
}

export interface PublicBookingPayload {
  professional_id: string
  start_time: string
  first_name: string
  last_name: string
  phone: string
  date_of_birth: string
  email?: string
  reason?: string
}

export interface PublicBookingConfirmation {
  appointment_id: string
  start_time: string
  end_time: string
  professional_name: string
  status: string
}

export type PublicBookingError
  = 'not_found'
    | 'slot_unavailable'
    | 'rate_limited'
    | 'validation'
    | 'unknown'

function apiBase(): string {
  const config = useRuntimeConfig()

  return (
    (config.public.apiBaseUrl as string)
    || (config.public.apiBase as string)
    || ''
  )
}

export function usePublicBooking(slug: string) {
  const clinic = ref<PublicBookingClinic | null>(null)
  const professionals = ref<PublicProfessional[]>([])
  const slots = ref<PublicBookableSlot[]>([])
  const confirmation = ref<PublicBookingConfirmation | null>(null)

  const loadingClinic = ref(false)
  const loadingProfessionals = ref(false)
  const loadingSlots = ref(false)
  const submitting = ref(false)

  const lastError = ref<PublicBookingError | null>(null)
  const lastErrorDetail = ref<string | null>(null)

  const baseUrl = computed(
    () => `${apiBase()}/api/v1/booking/public/${encodeURIComponent(slug)}`
  )

  function resetError() {
    lastError.value = null
    lastErrorDetail.value = null
  }

  function captureError(err: unknown) {
    const error = err as {
      statusCode?: number
      status?: number
      data?: {
        detail?: string | Array<{ msg?: string }>
      }
    }

    const status = error.statusCode ?? error.status
    const detail = error.data?.detail

    if (typeof detail === 'string') {
      lastErrorDetail.value = detail
    } else if (Array.isArray(detail)) {
      lastErrorDetail.value = detail
        .map(item => item.msg)
        .filter(Boolean)
        .join(', ')
    }

    if (status === 404) {
      lastError.value = 'not_found'
    } else if (status === 409) {
      lastError.value = 'slot_unavailable'
    } else if (status === 422) {
      lastError.value = 'validation'
    } else if (status === 429) {
      lastError.value = 'rate_limited'
    } else {
      lastError.value = 'unknown'
    }
  }

  async function fetchClinic(): Promise<boolean> {
    loadingClinic.value = true
    resetError()

    try {
      const response = await $fetch<{ data: PublicBookingClinic }>(
        baseUrl.value
      )

      clinic.value = response.data
      return true
    } catch (err) {
      captureError(err)
      return false
    } finally {
      loadingClinic.value = false
    }
  }

  async function fetchProfessionals(): Promise<boolean> {
    loadingProfessionals.value = true
    resetError()

    try {
      const response = await $fetch<{ data: PublicProfessional[] }>(
        `${baseUrl.value}/professionals`
      )

      professionals.value = response.data
      return true
    } catch (err) {
      captureError(err)
      professionals.value = []
      return false
    } finally {
      loadingProfessionals.value = false
    }
  }

  async function fetchSlots(
    professionalId: string,
    day: string
  ): Promise<boolean> {
    loadingSlots.value = true
    resetError()
    slots.value = []

    try {
      const response = await $fetch<{ data: PublicBookableSlot[] }>(
        `${baseUrl.value}/slots`,
        {
          query: {
            professional_id: professionalId,
            day
          }
        }
      )

      slots.value = response.data
      return true
    } catch (err) {
      captureError(err)
      return false
    } finally {
      loadingSlots.value = false
    }
  }

  async function book(
    payload: PublicBookingPayload
  ): Promise<PublicBookingConfirmation | null> {
    submitting.value = true
    resetError()
    confirmation.value = null

    try {
      const response = await $fetch<{ data: PublicBookingConfirmation }>(
        baseUrl.value,
        {
          method: 'POST',
          body: payload
        }
      )

      confirmation.value = response.data
      return response.data
    } catch (err) {
      captureError(err)
      return null
    } finally {
      submitting.value = false
    }
  }

  function clearSlots() {
    slots.value = []
  }

  return {
    clinic,
    professionals,
    slots,
    confirmation,
    loadingClinic,
    loadingProfessionals,
    loadingSlots,
    submitting,
    lastError,
    lastErrorDetail,
    fetchClinic,
    fetchProfessionals,
    fetchSlots,
    book,
    clearSlots,
    resetError
  }
}
