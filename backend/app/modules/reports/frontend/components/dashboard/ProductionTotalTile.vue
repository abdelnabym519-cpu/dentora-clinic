<script setup lang="ts">
import KpiTile from './KpiTile.vue'
import type { PaymentsProfessionalBreakdown } from '../../composables/useReports'

interface Props {
  state: {
    loading: boolean
    error: boolean
    data: PaymentsProfessionalBreakdown[] | null
  }
}

const props = defineProps<Props>()
const { t } = useI18n()
const { format } = useCurrency()

const totals = computed(() => {
  const rows = props.state.data ?? []
  const amount = rows.reduce((acc, r) => acc + parseFloat(r.total_earned || '0'), 0)
  const count = rows.reduce((acc, r) => acc + (r.count || 0), 0)
  return { amount, count }
})

const value = computed(() => format(totals.value.amount))
const hint = computed(() =>
  t('reports.dashboard.kpi.productionHint', { count: totals.value.count })
)

const isEmpty = computed(() =>
  !props.state.loading && (!props.state.data || props.state.data.length === 0)
)
</script>

<template>
  <KpiTile
    :title="t('reports.dashboard.kpi.production')"
    icon="i-lucide-activity"
    severity="info"
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
