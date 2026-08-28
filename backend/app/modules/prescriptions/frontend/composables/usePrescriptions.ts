export type PrescriptionStatus = 'draft' | 'issued' | 'cancelled' | 'voided'

export interface PrescriptionItem {
  id?: string | null
  medication_name: string
  strength?: string | null
  dose: string
  frequency: string
  duration: string
  route: string
  instructions?: string | null
  quantity: number
  quantity_unit?: string | null
}

export interface Prescription {
  id: string
  tenant_id: string
  clinic_id: string
  patient_id: string
  doctor_id: string
  identifier: string
  status: PrescriptionStatus
  items: PrescriptionItem[]
  created_at: string
  updated_at: string
  issued_at?: string | null
  cancelled_at?: string | null
  voided_at?: string | null
  cancel_reason?: string | null
  void_reason?: string | null
}

export interface PrescriptionDelivery {
  id: string
  channel: string
  status: string
  to_address: string
  attempts: number
  max_attempts: number
  provider?: string | null
  provider_message_id?: string | null
  error_message?: string | null
  created_at: string
  sent_at?: string | null
  delivered_at?: string | null
  read_at?: string | null
}

interface ApiOk<T> { data: T }

export function usePrescriptions() {
  const api = useApi()

  const list = async (patientId?: string): Promise<ApiOk<Prescription[]>> => {
    const suffix = patientId ? `?patient_id=${encodeURIComponent(patientId)}` : ''
    return await api.get<ApiOk<Prescription[]>>(`/api/v1/prescriptions${suffix}`)
  }

  const create = async (patientId: string, items: PrescriptionItem[]): Promise<ApiOk<Prescription>> =>
    await api.post<ApiOk<Prescription>>('/api/v1/prescriptions', { patient_id: patientId, items })

  const update = async (id: string, patientId: string, items: PrescriptionItem[]): Promise<ApiOk<Prescription>> =>
    await api.patch<ApiOk<Prescription>>(`/api/v1/prescriptions/${id}`, { patient_id: patientId, items })

  const issue = async (id: string): Promise<ApiOk<Prescription>> =>
    await api.post<ApiOk<Prescription>>(`/api/v1/prescriptions/${id}/issue`, {})

  const retryWhatsApp = async (id: string): Promise<ApiOk<PrescriptionDelivery>> =>
    await api.post<ApiOk<PrescriptionDelivery>>(`/api/v1/prescriptions/${id}/whatsapp-delivery`, {})

  const deliveries = async (id: string): Promise<ApiOk<PrescriptionDelivery[]>> =>
    await api.get<ApiOk<PrescriptionDelivery[]>>(`/api/v1/prescriptions/${id}/deliveries`)

  const cancel = async (id: string, reason: string): Promise<ApiOk<Prescription>> =>
    await api.post<ApiOk<Prescription>>(`/api/v1/prescriptions/${id}/cancel`, { reason })

  const voidPrescription = async (id: string, reason: string): Promise<ApiOk<Prescription>> =>
    await api.post<ApiOk<Prescription>>(`/api/v1/prescriptions/${id}/void`, { reason })

  const audit = async (id: string) =>
    await api.get<ApiOk<Array<Record<string, unknown>>>>(`/api/v1/prescriptions/${id}/audit`)

  return { list, create, update, issue, retryWhatsApp, deliveries, cancel, voidPrescription, audit }
}
