<script setup lang="ts">
defineProps<{ ctx?: unknown }>()

const { t } = useI18n()
const { todayAppointments, todayLoaded, todayError, fetchToday } = useHomeAgenda()

const pending = computed(() => !todayLoaded.value)
const failed = computed(() => !pending.value && todayError.value)

function retry(): void {
  void fetchToday()
}
let intervalId: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  if (!todayLoaded.value) fetchToday()
  intervalId = setInterval(fetchToday, 60_000)
})
onBeforeUnmount(() => {
  if (intervalId) clearInterval(intervalId)
})

const counts = computed(() => {
  let inTreatment = 0
  let waiting = 0
  for (const a of todayAppointments.value) {
    if (a.status === 'in_treatment') inTreatment += 1
    else if (a.status === 'checked_in') waiting += 1
  }
  return { inTreatment, waiting, total: inTreatment + waiting }
})

const isEmpty = computed(() => !pending.value && !failed.value && counts.value.total === 0)
// Neutral surface for both "nobody in clinic" and "could not load" — the
// blue alert treatment is reserved for a real in-clinic population.
const plain = computed(() => isEmpty.value || failed.value)
</script>

<template>
  <div
    class="rounded-token-lg px-4 py-3"
    :class="plain
      ? 'bg-surface ring-1 ring-[var(--color-border)] shadow-[var(--shadow-sm)]'
      : 'alert-surface-info'"
  >
    <div class="flex items-center justify-between mb-1">
      <p
        class="text-caption"
        :class="plain ? 'text-subtle' : 'opacity-75'"
      >
        {{ t('dashboard.inClinic.title') }}
      </p>
      <UIcon
        name="i-lucide-activity"
        class="w-4 h-4"
        :class="plain ? 'text-subtle' : 'opacity-75'"
      />
    </div>

    <USkeleton
      v-if="pending"
      class="h-8 w-16 mb-2"
    />
    <div
      v-else-if="failed"
      class="flex flex-wrap items-center gap-2"
      data-testid="in-clinic-error"
    >
      <p class="text-caption text-[var(--color-danger-accent)]">
        {{ t('dashboard.loadError') }}
      </p>
      <UButton
        variant="ghost"
        size="xs"
        icon="i-lucide-refresh-cw"
        @click="retry"
      >
        {{ t('common.retry') }}
      </UButton>
    </div>
    <p
      v-else
      class="text-display tnum"
      :class="isEmpty ? 'text-default' : ''"
      data-testid="in-clinic-total"
    >
      {{ counts.total }}
    </p>

    <div
      v-if="!pending && !failed && !isEmpty"
      class="flex flex-wrap items-center gap-x-3 text-caption mt-1 opacity-75"
    >
      <span v-if="counts.inTreatment">
        {{ t('dashboard.inClinic.inTreatment', { n: counts.inTreatment }) }}
      </span>
      <span v-if="counts.waiting">
        {{ t('dashboard.inClinic.waiting', { n: counts.waiting }) }}
      </span>
    </div>
    <p
      v-else-if="!pending && !failed"
      class="text-caption text-subtle mt-1"
      data-testid="in-clinic-empty"
    >
      {{ t('dashboard.inClinic.empty') }}
    </p>
  </div>
</template>
