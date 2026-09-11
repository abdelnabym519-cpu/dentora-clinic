<script setup lang="ts">
import type { Prescription, PrescriptionDelivery, PrescriptionItem } from '../../composables/usePrescriptions'
import { errorMessage } from '~~/app/utils/error'

interface PatientBrief { id: string, first_name: string, last_name: string, record_number?: string | null }
interface PatientPage { data: PatientBrief[] }

const { t } = useI18n()
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
// Loading the history and searching patients are reads with their own
// surface: a failure must be visible *as* a failed load, not as an empty
// list ("no prescriptions" / "no patient found") and not as an unhandled
// rejection escaping a click handler.
const listError = ref('')
const searchError = ref('')
const searching = ref(false)
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

function statusLabel(status: string): string {
  return t(`prescriptions.status.${status}`, status)
}

function deliveryStatusLabel(status?: string): string {
  return status ? t(`prescriptions.deliveryStatus.${status}`, status) : ''
}

async function loadDeliveryHistory(rx: Prescription) {
  if (rx.status !== 'issued' && rx.status !== 'voided') return
  try {
    const response = await prescriptionsApi.deliveries(rx.id, { silent: true })
    deliveriesByPrescription.value[rx.id] = response.data
  } catch {
    // Audit-only enrichment fetched for every issued prescription in
    // parallel: one failed history must not reject the whole refresh
    // (Promise.all) nor be announced as a prescriptions error.
    deliveriesByPrescription.value[rx.id] = []
  }
}

async function loadPrescriptions() {
  listError.value = ''
  try {
    const response = await prescriptionsApi.list(selectedPatient.value?.id, { silent: true })
    prescriptions.value = response.data ?? []
  } catch (e: unknown) {
    prescriptions.value = []
    listError.value = errorMessage(e, t('prescriptions.errors.load'))
    return
  }
  if (can('prescriptions.audit')) {
    await Promise.all(prescriptions.value.map(loadDeliveryHistory))
  }
}

async function searchPatients() {
  const term = patientSearch.value.trim()
  if (term.length < 2) {
    patients.value = []
    searchError.value = ''
    return
  }
  searching.value = true
  searchError.value = ''
  try {
    const response = await api.get<PatientPage>(
      `/api/v1/patients?search=${encodeURIComponent(term)}&page_size=10`,
      { silent: true }
    )
    patients.value = response.data ?? []
  } catch (e: unknown) {
    // Was an unguarded await inside an @input handler: the rejection
    // escaped and the dropdown silently kept the previous results.
    patients.value = []
    searchError.value = errorMessage(e, t('prescriptions.errors.search'))
  } finally {
    searching.value = false
  }
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
  } catch {
    error.value = t('prescriptions.errors.create')
    return
  } finally {
    busy.value = false
  }
  // Separate step: a failed *refresh* must not be reported as "could not
  // create" when the draft was in fact created.
  await loadPrescriptions()
}

async function issue(rx: Prescription) {
  busy.value = true
  error.value = ''
  try {
    await prescriptionsApi.issue(rx.id)
  } catch {
    error.value = t('prescriptions.errors.issue')
    return
  } finally {
    busy.value = false
  }
  await loadPrescriptions()
}

async function retryWhatsApp(rx: Prescription) {
  busy.value = true
  error.value = ''
  try {
    await prescriptionsApi.retryWhatsApp(rx.id)
    if (can('prescriptions.audit')) await loadDeliveryHistory(rx)
  } catch {
    error.value = t('prescriptions.errors.whatsapp')
  } finally {
    busy.value = false
  }
}

async function cancel(rx: Prescription) {
  if (!transitionReason.value.trim()) return
  busy.value = true
  error.value = ''
  try {
    await prescriptionsApi.cancel(rx.id, transitionReason.value)
    transitionReason.value = ''
  } catch {
    error.value = t('prescriptions.errors.cancel')
    return
  } finally {
    busy.value = false
  }
  await loadPrescriptions()
}

async function voidRx(rx: Prescription) {
  if (!transitionReason.value.trim()) return
  busy.value = true
  error.value = ''
  try {
    await prescriptionsApi.voidPrescription(rx.id, transitionReason.value)
    transitionReason.value = ''
  } catch {
    error.value = t('prescriptions.errors.void')
    return
  } finally {
    busy.value = false
  }
  await loadPrescriptions()
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
        {{ t('prescriptions.title') }}
      </h1>
      <p class="text-sm text-gray-500">
        {{ t('prescriptions.subtitle') }}
      </p>
    </header>

    <section
      class="rounded-xl border p-4 space-y-4"
      data-testid="prescription-create"
    >
      <h2 class="font-semibold">
        {{ t('prescriptions.new') }}
      </h2>
      <div class="relative">
        <label class="block text-sm font-medium">
          {{ t('prescriptions.patient') }}
        </label>
        <input
          v-model="patientSearch"
          data-testid="prescription-patient-search"
          class="mt-1 w-full rounded border px-3 py-2"
          :placeholder="t('prescriptions.searchPatient')"
          @input="searchPatients"
        >
        <p
          v-if="searchError"
          class="mt-1 text-sm text-red-600"
          role="alert"
          data-testid="prescription-patient-search-error"
        >
          {{ searchError }}
        </p>
        <div
          v-if="patients.length"
          class="absolute z-10 mt-1 w-full rounded border bg-white shadow"
        >
          <button
            v-for="patient in patients"
            :key="patient.id"
            type="button"
            class="block w-full px-3 py-2 text-start hover:bg-gray-50"
            :data-testid="`prescription-patient-${patient.id}`"
            @click="selectPatient(patient)"
          >
            {{ patient.first_name }} {{ patient.last_name }}
          </button>
        </div>
      </div>

      <div
        v-for="(item, index) in items"
        :key="index"
        class="grid gap-3 rounded border p-3 md:grid-cols-3"
      >
        <input v-model="item.medication_name" :data-testid="`medication-name-${index}`" class="rounded border px-3 py-2" :placeholder="t('prescriptions.fields.medication')">
        <input v-model="item.strength" class="rounded border px-3 py-2" :placeholder="t('prescriptions.fields.strength')">
        <input v-model="item.dose" :data-testid="`dose-${index}`" class="rounded border px-3 py-2" :placeholder="t('prescriptions.fields.dose')">
        <input v-model="item.frequency" :data-testid="`frequency-${index}`" class="rounded border px-3 py-2" :placeholder="t('prescriptions.fields.frequency')">
        <input v-model="item.duration" :data-testid="`duration-${index}`" class="rounded border px-3 py-2" :placeholder="t('prescriptions.fields.duration')">
        <input v-model="item.route" :data-testid="`route-${index}`" class="rounded border px-3 py-2" :placeholder="t('prescriptions.fields.route')">
        <input v-model.number="item.quantity" :data-testid="`quantity-${index}`" type="number" min="1" class="rounded border px-3 py-2" :placeholder="t('prescriptions.fields.quantity')">
        <input v-model="item.quantity_unit" class="rounded border px-3 py-2" :placeholder="t('prescriptions.fields.quantityUnit')">
        <input v-model="item.instructions" class="rounded border px-3 py-2" :placeholder="t('prescriptions.fields.instructions')">
        <button
          type="button"
          class="text-sm text-red-600"
          @click="removeItem(index)"
        >
          {{ t('prescriptions.remove') }}
        </button>
      </div>

      <div class="flex flex-wrap gap-3">
        <button
          type="button"
          class="rounded border px-3 py-2"
          @click="addItem"
        >
          {{ t('prescriptions.addMedication') }}
        </button>
        <button
          type="button"
          data-testid="create-prescription"
          class="rounded bg-blue-600 px-4 py-2 text-white disabled:opacity-50"
          :disabled="busy || !selectedPatient"
          @click="createDraft"
        >
          {{ t('prescriptions.createDraft') }}
        </button>
      </div>
      <p
        v-if="error"
        class="text-sm text-red-600"
        role="alert"
      >
        {{ error }}
      </p>
    </section>

    <section class="space-y-3">
      <h2 class="font-semibold">
        {{ t('prescriptions.history') }}
      </h2>
      <input
        v-model="transitionReason"
        data-testid="prescription-transition-reason"
        class="w-full rounded border px-3 py-2"
        :placeholder="t('prescriptions.transitionReason')"
      >
      <div
        v-if="listError"
        class="flex flex-wrap items-center gap-2 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700"
        role="alert"
        data-testid="prescriptions-list-error"
      >
        <span class="flex-1 min-w-0">{{ listError }}</span>
        <button
          type="button"
          class="rounded border px-3 py-1"
          data-testid="prescriptions-list-retry"
          @click="loadPrescriptions"
        >
          {{ t('common.retry') }}
        </button>
      </div>
      <p
        v-else-if="!prescriptions.length"
        class="rounded-xl border border-dashed p-4 text-sm text-gray-500"
      >
        {{ t('prescriptions.empty') }}
      </p>
      <div
        v-for="rx in prescriptions"
        :key="rx.id"
        class="rounded-xl border p-4"
        :data-testid="`prescription-${rx.id}`"
      >
        <div class="flex flex-wrap items-center justify-between gap-2">
          <div>
            <strong dir="ltr" class="inline-block">
              {{ rx.identifier }}
            </strong>
            <span class="ms-2 rounded bg-gray-100 px-2 py-1 text-xs" :data-testid="`prescription-status-${rx.id}`">
              {{ statusLabel(rx.status) }}
            </span>
          </div>
          <div class="flex flex-wrap gap-2">
            <button v-if="rx.status === 'draft'" :data-testid="`issue-${rx.id}`" type="button" class="rounded bg-green-600 px-3 py-1 text-white" :disabled="busy" @click="issue(rx)">
              {{ t('prescriptions.issue') }}
            </button>
            <button v-if="rx.status === 'draft'" type="button" class="rounded border px-3 py-1" :disabled="busy" @click="cancel(rx)">
              {{ t('prescriptions.cancel') }}
            </button>
            <button v-if="rx.status === 'issued' && can('prescriptions.issue')" :data-testid="`whatsapp-retry-${rx.id}`" type="button" class="rounded border px-3 py-1" :disabled="busy" @click="retryWhatsApp(rx)">
              {{ t('prescriptions.sendWhatsApp') }}
            </button>
            <button v-if="rx.status === 'issued'" type="button" class="rounded border px-3 py-1" :disabled="busy" @click="voidRx(rx)">
              {{ t('prescriptions.void') }}
            </button>
          </div>
        </div>
        <ul class="mt-3 list-disc ps-5 text-sm">
          <li v-for="item in rx.items" :key="item.id || `${item.medication_name}-${item.dose}`" dir="auto">
            {{ item.medication_name }} — {{ item.dose }}, {{ item.frequency }}, {{ item.duration }}, {{ item.route }} × {{ item.quantity }}
          </li>
        </ul>
        <div v-if="can('prescriptions.audit') && (rx.status === 'issued' || rx.status === 'voided')" class="mt-3 rounded bg-gray-50 p-3 text-xs" :data-testid="`whatsapp-delivery-${rx.id}`">
          <template v-if="latestDelivery(rx.id)">
            <strong>{{ t('prescriptions.whatsapp') }}:</strong>
            {{ deliveryStatusLabel(latestDelivery(rx.id)?.status) }}
            <span v-if="latestDelivery(rx.id)?.attempts">
              · {{ t('prescriptions.attempts', { attempts: latestDelivery(rx.id)?.attempts, max: latestDelivery(rx.id)?.max_attempts }) }}
            </span>
            <span v-if="latestDelivery(rx.id)?.delivered_at">
              · {{ t('prescriptions.delivered') }} <bdi dir="ltr">{{ latestDelivery(rx.id)?.delivered_at }}</bdi>
            </span>
            <span v-if="latestDelivery(rx.id)?.read_at">
              · {{ t('prescriptions.read') }} <bdi dir="ltr">{{ latestDelivery(rx.id)?.read_at }}</bdi>
            </span>
            <p v-if="latestDelivery(rx.id)?.error_message" class="mt-1 text-red-600" role="alert" dir="auto">
              {{ latestDelivery(rx.id)?.error_message }}
            </p>
          </template>
          <span v-else>{{ t('prescriptions.noDeliveryAttempt') }}</span>
        </div>
        <p v-if="rx.status !== 'draft'" class="mt-2 text-xs text-gray-500">
          {{ t('prescriptions.immutable') }}
        </p>
      </div>
    </section>
  </div>
</template>
