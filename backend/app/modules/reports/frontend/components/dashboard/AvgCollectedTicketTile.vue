<script setup lang="ts">
import KpiTile from './KpiTile.vue'
import type { PaymentsSummaryReport } from '../../composables/useReports'

interface Props {
  state: {
    loading: boolean
    error: boolean
    data: PaymentsSummaryReport | null
  }
}

const props = defineProps<Props>()
const { t } = useI18n()
const { format } = useCurrency()

const avg = computed(() => {
  const d = props.state.data
  if (!d || !d.payment_count) return null
  return parseFloat(d.net_collected) / d.payment_count
})

const value = computed(() => (avg.value == null ? '—' : format(avg.value)))

const hint = computed(() => {
  const c = props.state.data?.payment_count ?? 0
  return t('reports.dashboard.kpi.avgTicketHint', { count: c })
})

const isEmpty = computed(() =>
  !props.state.loading && (avg.value == null)
)
</script>

<template>
  <KpiTile
    :title="t('reports.dashboard.kpi.avgCollectedTicket')"
    icon="i-lucide-receipt"
    severity="neutral"
    :loading="state.loading"
    :empty="isEmpty"
    :error="state.error"
    :error-label="t('errors.loadFailed')"
    :value="value"
    :hint="hint"
  >
    <template #empty>
      {{ t('reports.dashboard.empty.noData') }}
    </template>
  </KpiTile>
</template>
