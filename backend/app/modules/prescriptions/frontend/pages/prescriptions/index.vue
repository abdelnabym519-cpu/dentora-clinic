<script setup lang="ts">
import type { Prescription, PrescriptionDelivery, PrescriptionItem } from '../../composables/usePrescriptions'

interface PatientBrief { id: string, first_name: string, last_name: string, record_number?: string | null }
interface PatientPage { data: PatientBrief[] }

const api = useApi()
const prescriptionsApi = usePrescriptions()
const { can } = usePermissions()
const prescriptions = ref<Prescription[]>([])
const deliveriesByPrescription = ref<Record<string, PrescriptionDelivery[]>>({})
const patientSearch = ref('')
const patients = ref<PatientBrief[]>([])
const selectedPatient = ref<PatientBrief | null>(null)
const busy = ref(false)
const error = ref('')
const transitionReason = ref('')
const hydrated = ref(false)

const emptyItem = (): PrescriptionItem => ({
  medication_name: '',
  strength: '',
  dose: '',
  frequency: '',
  duration: '',
  route: 'oral',
  instructions: '',
  quantity: 1,
  quantity_unit: 'unit'
})

const items = ref<PrescriptionItem[]>([emptyItem()])

function latestDelivery(id: string): PrescriptionDelivery | undefined {
  return deliveriesByPrescription.value[id]?.[0]
}

async function loadDeliveryHistory(rx: Prescription) {
  if (rx.status !== 'issued' && rx.status !== 'voided') return
  const response = await prescriptionsApi.deliveries(rx.id)
  deliveriesByPrescription.value[rx.id] = response.data
}

async function loadPrescriptions() {
  const response = await prescriptionsApi.list(selectedPatient.value?.id)
  prescriptions.value = response.data
  if (can('prescriptions.audit')) {
    await Promise.all(prescriptions.value.map(loadDeliveryHistory))
  }
}

async function searchPatients() {
  if (patientSearch.value.trim().length < 2) {
    patients.value = []
    return
  }
  const response = await api.get<PatientPage>(`/api/v1/patients?search=${encodeURIComponent(patientSearch.value.trim())}&page_size=10`)
  patients.value = response.data
}

async function selectPatient(patient: PatientBrief) {
  selectedPatient.value = patient
  patientSearch.value = `${patient.first_name} ${patient.last_name}`
  patients.value = []
  await loadPrescriptions()
}

function addItem() {
  items.value.push(emptyItem())
}

function removeItem(index: number) {
  if (items.value.length > 1) items.value.splice(index, 1)
}

async function createDraft() {
  if (!selectedPatient.value) return
  busy.value = true
  error.value = ''
  try {
    await prescriptionsApi.create(selectedPatient.value.id, items.value)
    items.value = [emptyItem()]
    await loadPrescriptions()
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Could not create prescription'
  } finally {
    busy.value = false
  }
}

async function issue(rx: Prescription) {
  busy.value = true
  error.value = ''
  try {
    await prescriptionsApi.issue(rx.id)
    await loadPrescriptions()
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Could not issue prescription'
  } finally {
    busy.value = false
  }
}

async function retryWhatsApp(rx: Prescription) {
  busy.value = true
  error.value = ''
  try {
    await prescriptionsApi.retryWhatsApp(rx.id)
    if (can('prescriptions.audit')) await loadDeliveryHistory(rx)
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Could not queue WhatsApp delivery'
  } finally {
    busy.value = false
  }
}

async function cancel(rx: Prescription) {
  if (!transitionReason.value.trim()) return
  busy.value = true
  try {
    await prescriptionsApi.cancel(rx.id, transitionReason.value)
    transitionReason.value = ''
    await loadPrescriptions()
  } finally {
    busy.value = false
  }
}

async function voidRx(rx: Prescription) {
  if (!transitionReason.value.trim()) return
  busy.value = true
  try {
    await prescriptionsApi.voidPrescription(rx.id, transitionReason.value)
    transitionReason.value = ''
    await loadPrescriptions()
  } finally {
    busy.value = false
  }
}

onMounted(() => {
  // SSR can make the form visible before Vue has attached its input handlers.
  // Expose an explicit client-readiness signal so browser automation (and any
  // future client integration) never races hydration and loses user input.
  hydrated.value = true
  void loadPrescriptions()
})
</script>

<template>
  <div
    class="mx-auto max-w-7xl space-y-6 p-6"
    data-testid="prescriptions-page"
    :data-hydrated="hydrated ? 'true' : 'false'"
  >
    <header>
      <h1 class="text-2xl font-semibold">
        Electronic Prescriptions
      </h1>
      <p class="text-sm text-gray-500">
        Create, issue, deliver by WhatsApp and audit prescriptions for the selected clinic.
      </p>
    </header>

    <section class="rounded-xl border p-4 space-y-4" data-testid="prescription-create">
      <h2 class="font-semibold">
        New prescription
      </h2>
      <div class="relative">
        <label class="block text-sm font-medium">
          Patient
        </label>
        <input
          v-model="patientSearch"
          data-testid="prescription-patient-search"
          class="mt-1 w-full rounded border px-3 py-2"
          placeholder="Search patient"
          @input="searchPatients"
        >
        <div v-if="patients.length" class="absolute z-10 mt-1 w-full rounded border bg-white shadow">
          <button
            v-for="patient in patients"
            :key="patient.id"
            type="button"
            class="block w-full px-3 py-2 text-left hover:bg-gray-50"
            :data-testid="`prescription-patient-${patient.id}`"
            @click="selectPatient(patient)"
          >
            {{ patient.first_name }} {{ patient.last_name }}
          </button>
        </div>
      </div>

      <div v-for="(item, index) in items" :key="index" class="grid gap-3 rounded border p-3 md:grid-cols-3">
        <input v-model="item.medication_name" :data-testid="`medication-name-${index}`" class="rounded border px-3 py-2" placeholder="Medication">
        <input v-model="item.strength" class="rounded border px-3 py-2" placeholder="Strength">
        <input v-model="item.dose" :data-testid="`dose-${index}`" class="rounded border px-3 py-2" placeholder="Dose">
        <input v-model="item.frequency" :data-testid="`frequency-${index}`" class="rounded border px-3 py-2" placeholder="Frequency">
        <input v-model="item.duration" :data-testid="`duration-${index}`" class="rounded border px-3 py-2" placeholder="Duration">
        <input v-model="item.route" :data-testid="`route-${index}`" class="rounded border px-3 py-2" placeholder="Route">
        <input v-model.number="item.quantity" :data-testid="`quantity-${index}`" type="number" min="1" class="rounded border px-3 py-2" placeholder="Quantity">
        <input v-model="item.quantity_unit" class="rounded border px-3 py-2" placeholder="Quantity unit">
        <input v-model="item.instructions" class="rounded border px-3 py-2" placeholder="Instructions">
        <button type="button" class="text-sm text-red-600" @click="removeItem(index)">
          Remove
        </button>
      </div>

      <div class="flex gap-3">
        <button type="button" class="rounded border px-3 py-2" @click="addItem">
          Add medication
        </button>
        <button
          type="button"
          data-testid="create-prescription"
          class="rounded bg-blue-600 px-4 py-2 text-white disabled:opacity-50"
          :disabled="busy || !selectedPatient"
          @click="createDraft"
        >
          Create draft
        </button>
      </div>
      <p v-if="error" class="text-sm text-red-600">
        {{ error }}
      </p>
    </section>

    <section class="space-y-3">
      <h2 class="font-semibold">
        Prescriptions
      </h2>
      <input v-model="transitionReason" data-testid="prescription-transition-reason" class="w-full rounded border px-3 py-2" placeholder="Reason for cancel / void">
      <div v-for="rx in prescriptions" :key="rx.id" class="rounded-xl border p-4" :data-testid="`prescription-${rx.id}`">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <div>
            <strong>
              {{ rx.identifier }}
            </strong>
            <span class="ml-2 rounded bg-gray-100 px-2 py-1 text-xs" :data-testid="`prescription-status-${rx.id}`">
              {{ rx.status }}
            </span>
          </div>
          <div class="flex gap-2">
            <button v-if="rx.status === 'draft'" :data-testid="`issue-${rx.id}`" type="button" class="rounded bg-green-600 px-3 py-1 text-white" :disabled="busy" @click="issue(rx)">
              Issue
            </button>
            <button v-if="rx.status === 'draft'" type="button" class="rounded border px-3 py-1" :disabled="busy" @click="cancel(rx)">
              Cancel
            </button>
            <button v-if="rx.status === 'issued' && can('prescriptions.issue')" :data-testid="`whatsapp-retry-${rx.id}`" type="button" class="rounded border px-3 py-1" :disabled="busy" @click="retryWhatsApp(rx)">
              Send / retry WhatsApp
            </button>
            <button v-if="rx.status === 'issued'" type="button" class="rounded border px-3 py-1" :disabled="busy" @click="voidRx(rx)">
              Void
            </button>
          </div>
        </div>
        <ul class="mt-3 list-disc pl-5 text-sm">
          <li v-for="item in rx.items" :key="item.id || `${item.medication_name}-${item.dose}`">
            {{ item.medication_name }} — {{ item.dose }}, {{ item.frequency }}, {{ item.duration }}, {{ item.route }} × {{ item.quantity }}
          </li>
        </ul>
        <div v-if="can('prescriptions.audit') && (rx.status === 'issued' || rx.status === 'voided')" class="mt-3 rounded bg-gray-50 p-3 text-xs" :data-testid="`whatsapp-delivery-${rx.id}`">
          <template v-if="latestDelivery(rx.id)">
            <strong>WhatsApp:</strong>
            {{ latestDelivery(rx.id)?.status }}
            <span v-if="latestDelivery(rx.id)?.attempts">
              · attempts {{ latestDelivery(rx.id)?.attempts }}/{{ latestDelivery(rx.id)?.max_attempts }}
            </span>
            <span v-if="latestDelivery(rx.id)?.delivered_at">
              · delivered {{ latestDelivery(rx.id)?.delivered_at }}
            </span>
            <span v-if="latestDelivery(rx.id)?.read_at">
              · read {{ latestDelivery(rx.id)?.read_at }}
            </span>
            <p v-if="latestDelivery(rx.id)?.error_message" class="mt-1 text-red-600">
              {{ latestDelivery(rx.id)?.error_message }}
            </p>
          </template>
          <span v-else>WhatsApp: no delivery attempt recorded.</span>
        </div>
        <p v-if="rx.status !== 'draft'" class="mt-2 text-xs text-gray-500">
          Issued/terminal prescription content is immutable.
        </p>
      </div>
    </section>
  </div>
</template>
