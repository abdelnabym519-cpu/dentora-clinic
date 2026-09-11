<script setup lang="ts">
import KpiTile from './KpiTile.vue'
import type { FirstVisitsSummary } from '../../composables/useReports'

interface Props {
  state: {
    loading: boolean
    error: boolean
    data: FirstVisitsSummary | null
    delta: number | null
  }
}

const props = defineProps<Props>()
const { t } = useI18n()

const value = computed(() => {
  const d = props.state.data
  if (!d) return '—'
  return String(d.new_patients)
})

const hint = computed(() => {
  const d = props.state.data
  if (!d) return undefined
  // Backend returns first_visit_rate as a percentage in 0..100, not 0..1.
  return t('reports.dashboard.kpi.newPatientsHint', { rate: d.first_visit_rate.toFixed(1) })
})

const isEmpty = computed(() => !props.state.loading && !props.state.data)
</script>

<template>
  <KpiTile
    :title="t('reports.dashboard.kpi.newPatients')"
    icon="i-lucide-user-plus"
    severity="success"
    to="/reports/scheduling"
    :loading="state.loading"
    :empty="isEmpty"
    :error="state.error"
    :error-label="t('errors.loadFailed')"
    :value="value"
    :hint="hint"
    :delta="state.delta"
    :delta-label="t('reports.dashboard.vsPrev')"
  >
    <template #empty>
      {{ t('reports.dashboard.empty.noData') }}
    </template>
  </KpiTile>
</template>
