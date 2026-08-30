<script setup lang="ts">
import { PERMISSIONS } from '~/config/permissions'

const { t } = useI18n()
const { can } = usePermissions()
const api = useApi()
const toast = useToast()

if (!can(PERMISSIONS.copilot.chat)) {
  throw createError({ statusCode: 403, statusMessage: 'Forbidden' })
}

interface PatientOption {
  id: string
  full_name?: string
  legal_name?: string
}

const patientId = ref<string>('')
const patients = ref<PatientOption[]>([])
const loadingPatients = ref(true)
const route = useRoute()

const { statuses, results, errors, run, runAll } = useClinicalAI()

const features: { key: keyof typeof statuses, title: string, icon: string }[] = [
  { key: 'case-summary', title: t('copilot.clinical.features.summary'), icon: 'i-lucide-file-text' },
  { key: 'report', title: t('copilot.clinical.features.report'), icon: 'i-lucide-clipboard-list' },
  { key: 'second-review', title: t('copilot.clinical.features.review'), icon: 'i-lucide-search-check' },
  { key: 'treatment-suggestions', title: t('copilot.clinical.features.plan'), icon: 'i-lucide-list-checks' },
  { key: 'case-intelligence', title: t('copilot.clinical.features.intel'), icon: 'i-lucide-activity' }
]

onMounted(async () => {
  try {
    const res = await api.$api<{ data: PatientOption[] }>('/api/v1/patients?limit=200', {
      method: 'GET'
    })
    patients.value = res.data || []
    const fromQuery = route.query.patient as string | undefined
    if (fromQuery && patients.value.some(p => p.id === fromQuery)) {
      patientId.value = fromQuery
    } else if (patients.value.length) {
      patientId.value = patients.value[0].id
    }
  } catch {
    toast.add({ title: t('copilot.clinical.loadPatientsError'), color: 'error' })
  } finally {
    loadingPatients.value = false
  }
})

watch(patientId, () => {
  // Clear any previous feature state when switching patient.
  for (const f of features) {
    statuses[f.key] = 'idle'
    results[f.key] = null
    errors[f.key] = null
  }
})

function patientName(p: PatientOption): string {
  return p.full_name || p.legal_name || p.id
}

const anyLoading = computed(() => features.some(f => statuses[f.key] === 'loading'))
</script>

<template>
  <div class="mx-auto max-w-4xl space-y-4">
    <div>
      <h1 class="text-xl font-semibold">
        {{ t('copilot.clinical.title') }}
      </h1>
      <p class="text-sm text-muted">
        {{ t('copilot.clinical.subtitle') }}
      </p>
    </div>

    <UCard :ui="{ body: 'space-y-3' }">
      <div class="flex flex-col gap-3 sm:flex-row sm:items-end">
        <div class="flex-1">
          <label class="mb-1 block text-sm font-medium">
            {{ t('copilot.clinical.patient') }}
          </label>
          <USelect
            v-model="patientId"
            :loading="loadingPatients"
            :items="patients.map(p => ({ label: patientName(p), value: p.id }))"
            class="w-full"
          />
        </div>
        <UButton
          icon="i-lucide-sparkles"
          :loading="anyLoading"
          :disabled="!patientId || anyLoading"
          @click="runAll(patientId)"
        >
          {{ t('copilot.clinical.generateAll') }}
        </UButton>
      </div>
      <p class="flex items-start gap-1.5 text-xs text-warning">
        <UIcon
          name="i-lucide-shield-alert"
          class="mt-0.5 shrink-0"
        />
        {{ t('copilot.clinical.auditNote') }}
      </p>
    </UCard>

    <div
      v-for="f in features"
      :key="f.key"
    >
      <UCard>
        <template #header>
          <div class="flex items-center justify-between gap-2">
            <div class="flex items-center gap-2 font-medium">
              <UIcon :name="f.icon" />
              {{ f.title }}
            </div>
            <UButton
              size="xs"
              variant="outline"
              color="neutral"
              :loading="statuses[f.key] === 'loading'"
              :disabled="!patientId || statuses[f.key] === 'loading'"
              @click="run(f.key, patientId)"
            >
              {{ statuses[f.key] === 'success' ? t('copilot.clinical.regenerate') : t('copilot.clinical.generate') }}
            </UButton>
          </div>
        </template>

        <!-- Idle -->
        <div
          v-if="statuses[f.key] === 'idle'"
          class="py-6 text-center text-sm text-muted"
        >
          {{ t('copilot.clinical.idle') }}
        </div>

        <!-- Loading: honest placeholder, no fake content -->
        <div
          v-else-if="statuses[f.key] === 'loading'"
          class="space-y-2 py-2"
        >
          <USkeleton class="h-4 w-3/4" />
          <USkeleton class="h-4 w-full" />
          <USkeleton class="h-4 w-5/6" />
          <p class="text-xs text-muted">
            {{ t('copilot.clinical.generating') }}
          </p>
        </div>

        <!-- Error / AI unavailable -->
        <UAlert
          v-else-if="statuses[f.key] === 'error'"
          icon="i-lucide-cloud-off"
          color="error"
          variant="soft"
          :title="t('copilot.clinical.errorTitle')"
          :description="errors[f.key] || t('copilot.clinical.errorGeneric')"
        >
          <template #actions>
            <UButton
              size="xs"
              variant="solid"
              color="error"
              @click="run(f.key, patientId)"
            >
              {{ t('copilot.clinical.retry') }}
            </UButton>
          </template>
        </UAlert>

        <!-- Success -->
        <template v-else-if="statuses[f.key] === 'success' && results[f.key]">
          <UAlert
            v-if="results[f.key]?.insufficient_information"
            icon="i-lucide-info"
            color="neutral"
            variant="soft"
            class="mb-3"
            :title="t('copilot.clinical.insufficientTitle')"
            :description="t('copilot.clinical.insufficient')"
          />
          <pre class="overflow-x-auto whitespace-pre-wrap break-words rounded bg-muted/40 p-3 text-xs">{{ JSON.stringify(results[f.key], null, 2) }}</pre>
          <div class="mt-3 space-y-1 text-xs text-muted">
            <p class="flex items-center gap-1.5">
              <UIcon
                name="i-lucide-badge-check"
                class="text-success"
              />
              {{ t('copilot.clinical.disclaimer') }}: {{ results[f.key]?.disclaimer }}
            </p>
            <p v-if="results[f.key]?.model">
              {{ t('copilot.clinical.model') }}: {{ results[f.key]?.model }}
            </p>
          </div>
        </template>
      </UCard>
    </div>
  </div>
</template>
