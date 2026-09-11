<script setup lang="ts">
import KpiTile from './KpiTile.vue'
import type { AppointmentFunnel } from '../../composables/useReports'

interface Props {
  state: {
    loading: boolean
    error: boolean
    data: AppointmentFunnel | null
    delta: number | null
  }
}

const props = defineProps<Props>()
const { t } = useI18n()

// AppointmentFunnel returns rates as percentages in 0..100, not 0..1.
const value = computed(() => {
  const d = props.state.data
  if (!d || d.no_show_rate == null) return '—'
  return `${d.no_show_rate.toFixed(1)}%`
})

const hint = computed(() => {
  const d = props.state.data
  if (!d || d.completion_rate == null) return undefined
  return t('reports.dashboard.kpi.funnelHint', { completed: d.completion_rate.toFixed(1) })
})

const severity = computed(() => {
  const r = props.state.data?.no_show_rate ?? null
  if (r == null) return 'neutral'
  if (r > 10) return 'danger'
  if (r > 5) return 'warning'
  return 'success'
})

const isEmpty = computed(() => !props.state.loading && !props.state.data)
</script>

<template>
  <KpiTile
    :title="t('reports.dashboard.kpi.appointmentFunnel')"
    icon="i-lucide-calendar-x"
    :severity="severity"
    to="/reports/scheduling"
    :loading="state.loading"
    :empty="isEmpty"
    :error="state.error"
    :error-label="t('errors.loadFailed')"
    :value="value"
    :hint="hint"
    :delta="state.delta"
    delta-inverted
    :delta-label="t('reports.dashboard.vsPrev')"
  >
    <template #empty>
      {{ t('reports.dashboard.empty.noData') }}
    </template>
  </KpiTile>
</template>
