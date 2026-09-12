<script setup lang="ts">
import type { ClinicHours, ClinicOverride, ClinicOverridePayload, WeekdayShifts } from '../../composables/useClinicHours'
import { PERMISSIONS } from '~~/app/config/permissions'
import { errorDetail, errorMessage } from '~~/app/utils/error'

const { t } = useI18n()
const { confirmDialog } = useConfirmDialog()
const toast = useToast()
const { can } = usePermissions()
const {
  fetchHours,
  updateHours,
  fetchOverrides,
  createOverride,
  updateOverride,
  deleteOverride
} = useClinicHours()

const canWrite = computed(() => can(PERMISSIONS.schedules.clinicHoursWrite))

const hours = ref<ClinicHours | null>(null)
const overrides = ref<ClinicOverride[]>([])
const days = ref<WeekdayShifts[]>([])
const isLoading = ref(true)
/** Set when the hours could not be read: the grid must not render without them. */
const loadError = ref<string | null>(null)
const isSaving = ref(false)

const showOverrideModal = ref(false)
const editingOverride = ref<ClinicOverride | null>(null)
type ClinicOverrideForm = Omit<ClinicOverridePayload, 'reason'> & { reason: string }
const overrideForm = ref<ClinicOverrideForm>({
  start_date: new Date().toISOString().slice(0, 10),
  end_date: new Date().toISOString().slice(0, 10),
  kind: 'closed',
  reason: '',
  shifts: []
})

const kindLabels = computed(() => ({
  closed: t('schedules.overrides.closed'),
  custom_hours: t('schedules.overrides.customHours')
}))

async function load() {
  isLoading.value = true
  loadError.value = null
  try {
    const data = await fetchHours()
    hours.value = data
    days.value = data.days
    overrides.value = await fetchOverrides()
  } catch (e) {
    // Was try/finally with no catch: the rejection escaped onMounted and the
    // page rendered the weekly grid from empty `days` with a live Save — one
    // click from overwriting the clinic's real opening hours with nothing.
    console.error('Error loading clinic hours:', e)
    loadError.value = errorMessage(e, t('errors.loadFailed'))
  } finally {
    isLoading.value = false
  }
}

async function save() {
  isSaving.value = true
  try {
    const cleanDays = days.value.map(d => ({
      weekday: d.weekday,
      shifts: d.shifts.map(s => ({ start_time: s.start_time, end_time: s.end_time }))
    }))
    const updated = await updateHours({ days: cleanDays })
    hours.value = updated
    days.value = updated.days
    toast.add({ title: t('schedules.clinicHours.saved'), color: 'success' })
  } catch (e) {
    toast.add({ title: t('schedules.clinicHours.savedError'), description: errorDetail(e), color: 'error' })
  } finally {
    isSaving.value = false
  }
}

function openAddOverride() {
  editingOverride.value = null
  const today = new Date().toISOString().slice(0, 10)
  overrideForm.value = {
    start_date: today,
    end_date: today,
    kind: 'closed',
    reason: '',
    shifts: []
  }
  showOverrideModal.value = true
}

function openEditOverride(o: ClinicOverride) {
  editingOverride.value = o
  overrideForm.value = {
    start_date: o.start_date,
    end_date: o.end_date,
    kind: o.kind,
    reason: o.reason ?? '',
    shifts: o.shifts.map(s => ({ start_time: s.start_time, end_time: s.end_time }))
  }
  showOverrideModal.value = true
}

function addShiftToOverride() {
  overrideForm.value.shifts.push({ start_time: '09:00:00', end_time: '14:00:00' })
}

function removeShiftFromOverride(idx: number) {
  overrideForm.value.shifts.splice(idx, 1)
}

// Without this, a second click on Save before the first response lands creates
// a *second* override for the same dates: the clinic ends up with duplicate
// closed-day entries that contradict each other.
const isSavingOverride = ref(false)

async function saveOverride() {
  if (isSavingOverride.value) return
  isSavingOverride.value = true
  const payload: ClinicOverridePayload = {
    start_date: overrideForm.value.start_date,
    end_date: overrideForm.value.end_date,
    kind: overrideForm.value.kind,
    reason: overrideForm.value.reason || null,
    shifts: overrideForm.value.kind === 'closed' ? [] : overrideForm.value.shifts
  }
  try {
    if (editingOverride.value) {
      await updateOverride(editingOverride.value.id, payload)
    } else {
      await createOverride(payload)
    }
    overrides.value = await fetchOverrides()
    showOverrideModal.value = false
  } catch (err: unknown) {
    toast.add({
      title: t('common.error'),
      description: errorDetail(err),
      color: 'error'
    })
  } finally {
    isSavingOverride.value = false
  }
}

async function confirmDelete(o: ClinicOverride) {
  if (!await confirmDialog({ title: t('schedules.overrides.confirmDelete'), danger: true })) return
  try {
    await deleteOverride(o.id)
  } catch (e) {
    // The composable is silent, so this is the only report: a 404 or a 409
    // used to leave the override on screen with no message at all.
    toast.add({ title: t('errors.deleteFailed'), description: errorDetail(e), color: 'error' })
    return
  }
  try {
    overrides.value = await fetchOverrides()
  } catch (e) {
    toast.add({ title: t('errors.loadFailed'), description: errorDetail(e), color: 'error' })
  }
}

function timeForInput(value: string): string {
  return value.length >= 5 ? value.substring(0, 5) : value
}

function padTime(value: string): string {
  return value.length === 5 ? `${value}:00` : value
}

onMounted(load)
</script>

<template>
  <div>
    <USkeleton
      v-if="isLoading"
      class="h-40 w-full"
    />

    <!-- A failed load must not render the weekly grid from empty defaults:
         its Save button would overwrite the clinic's real opening hours. -->
    <div
      v-else-if="loadError"
      class="space-y-3"
      data-testid="clinic-hours-load-error"
    >
      <UAlert
        color="error"
        variant="soft"
        icon="i-lucide-alert-triangle"
        :title="t('errors.loadFailed')"
        :description="loadError"
      />
      <UButton
        variant="ghost"
        size="sm"
        icon="i-lucide-refresh-cw"
        data-testid="clinic-hours-retry"
        @click="load()"
      >
        {{ t('common.retry') }}
      </UButton>
    </div>

    <div
      v-else
      class="space-y-6"
    >
      <UCard>
        <template #header>
          <h2 class="text-lg font-semibold">
            {{ t('schedules.clinicHours.weeklyTemplate') }}
          </h2>
        </template>

        <WeeklyShiftGrid
          v-model="days"
          :disabled="!canWrite"
        />

        <template #footer>
          <div class="flex justify-end">
            <UButton
              v-if="canWrite"
              :loading="isSaving"
              icon="i-lucide-save"
              @click="save"
            >
              {{ t('schedules.clinicHours.save') }}
            </UButton>
          </div>
        </template>
      </UCard>

      <UCard>
        <OverrideCalendar
          :overrides="overrides"
          :can-write="canWrite"
          :kind-labels="kindLabels"
          @add="openAddOverride"
          @edit="openEditOverride"
          @delete="confirmDelete"
        />
      </UCard>
    </div>

    <UModal v-model:open="showOverrideModal">
      <template #content>
        <div class="p-6 space-y-4">
          <h3 class="text-lg font-semibold">
            {{ editingOverride ? t('schedules.clinicHours.editOverride') : t('schedules.clinicHours.addOverride') }}
          </h3>

          <UFormField :label="t('schedules.overrides.kind')">
            <USelect
              v-model="overrideForm.kind"
              :items="[
                { label: t('schedules.overrides.closed'), value: 'closed' },
                { label: t('schedules.overrides.customHours'), value: 'custom_hours' }
              ]"
            />
          </UFormField>

          <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <UFormField :label="t('schedules.overrides.startDate')">
              <UInput
                v-model="overrideForm.start_date"
                type="date"
              />
            </UFormField>
            <UFormField :label="t('schedules.overrides.endDate')">
              <UInput
                v-model="overrideForm.end_date"
                type="date"
              />
            </UFormField>
          </div>

          <UFormField :label="t('schedules.overrides.reason')">
            <UInput
              v-model="overrideForm.reason"
              :placeholder="t('schedules.overrides.reasonPlaceholder')"
            />
          </UFormField>

          <div
            v-if="overrideForm.kind === 'custom_hours'"
            class="space-y-2"
          >
            <label class="text-sm font-medium">{{ t('schedules.weekday.addShift') }}</label>
            <div
              v-for="(s, idx) in overrideForm.shifts"
              :key="idx"
              class="flex items-center gap-2"
            >
              <UInput
                type="time"
                :model-value="timeForInput(s.start_time)"
                size="sm"
                class="w-28"
                @update:model-value="(v) => (overrideForm.shifts[idx]!.start_time = padTime(String(v)))"
              />
              <span class="text-gray-400">—</span>
              <UInput
                type="time"
                :model-value="timeForInput(s.end_time)"
                size="sm"
                class="w-28"
                @update:model-value="(v) => (overrideForm.shifts[idx]!.end_time = padTime(String(v)))"
              />
              <UButton
                color="neutral"
                variant="ghost"
                icon="i-lucide-x"
                size="xs"
                @click="removeShiftFromOverride(idx)"
              />
            </div>
            <UButton
              size="xs"
              variant="soft"
              icon="i-lucide-plus"
              @click="addShiftToOverride"
            >
              {{ t('schedules.weekday.addShift') }}
            </UButton>
          </div>

          <div class="flex justify-end gap-2 pt-2">
            <UButton
              variant="ghost"
              @click="showOverrideModal = false"
            >
              {{ t('schedules.overrides.cancel') }}
            </UButton>
            <UButton
              :loading="isSavingOverride"
              data-testid="clinic-hours-override-save"
              @click="saveOverride"
            >
              {{ t('schedules.overrides.save') }}
            </UButton>
          </div>
        </div>
      </template>
    </UModal>
  </div>
</template>
