<script setup lang="ts">
import KpiTile from './KpiTile.vue'
import type { PaymentsSummaryReport } from '../../composables/useReports'

interface Props {
  state: {
    loading: boolean
    error: boolean
    data: PaymentsSummaryReport | null
    delta: number | null
    spark: number[]
  }
}

const props = defineProps<Props>()
const { t } = useI18n()
const { format } = useCurrency()

const value = computed(() => {
  const d = props.state.data
  if (!d) return '—'
  return format(parseFloat(d.net_collected))
})

const hint = computed(() => {
  const d = props.state.data
  if (!d) return undefined
  return t('reports.dashboard.kpi.cashCollectedHint', { count: d.payment_count })
})

const isEmpty = computed(() => !props.state.loading && !props.state.data)
</script>

<template>
  <KpiTile
    :title="t('reports.dashboard.kpi.cashCollected')"
    icon="i-lucide-banknote"
    severity="success"
    to="/reports/billing"
    :loading="state.loading"
    :empty="isEmpty"
    :error="state.error"
    :error-label="t('errors.loadFailed')"
    :value="value"
    :hint="hint"
    :sparkline-points="state.spark"
    sparkline-tone="success"
    :delta="state.delta"
    :delta-label="t('reports.dashboard.vsPrev')"
  >
    <template #empty>
      {{ t('reports.dashboard.empty.noData') }}
    </template>
  </KpiTile>
</template>
