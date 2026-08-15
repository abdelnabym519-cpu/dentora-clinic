<script setup lang="ts">
import { formatTrialRemaining, getTrialStatus } from '~/utils/trial'

const config = useRuntimeConfig()
const { locale } = useI18n()
const now = ref(new Date())
let timer: ReturnType<typeof setInterval> | undefined

const trial = computed(() => getTrialStatus(config.public, now.value))
const isArabic = computed(() => locale.value === 'ar')
const remaining = computed(() => {
  if (trial.value.remainingMs === null) return ''
  return formatTrialRemaining(trial.value.remainingMs, isArabic.value)
})

onMounted(() => {
  timer = setInterval(() => {
    now.value = new Date()
  }, 60_000)
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <div
    v-if="trial.enabled && !trial.expired"
    class="border-b border-amber-300 bg-amber-50 px-4 py-2 text-center text-sm font-medium text-amber-950 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-100"
    role="status"
  >
    <template v-if="isArabic">
      نسخة تجريبية لمدة 3 أيام — الوقت المتبقي: {{ remaining }}
    </template>
    <template v-else>
      3-day trial — time remaining: {{ remaining }}
    </template>
  </div>
</template>
