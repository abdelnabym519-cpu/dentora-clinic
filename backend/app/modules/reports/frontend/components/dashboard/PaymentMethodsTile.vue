<script setup lang="ts">
import SummaryCard from '~~/app/components/shared/SummaryCard.vue'
import DonutChart from '~~/app/components/charts/DonutChart.vue'
import { paymentMethodLabel } from '~~/app/utils/paymentMethod'
import type { PaymentsMethodBreakdown } from '../../composables/useReports'

type Tone = 'primary' | 'success' | 'danger' | 'info' | 'warning' | 'neutral'

const METHOD_TONES: Record<string, Tone> = {
  cash: 'success',
  card: 'primary',
  bank_transfer: 'info',
  instapay: 'primary',
  vodafone_cash: 'success',
  fawry: 'warning',
  direct_debit: 'neutral',
  insurance: 'warning',
  other: 'neutral'
}

interface Props {
  state: {
    loading: boolean
    error: boolean
    data: PaymentsMethodBreakdown[] | null
  }
}

const props = defineProps<Props>()
const { t } = useI18n()
const { format } = useCurrency()

const slices = computed(() => {
  const rows = props.state.data ?? []
  return rows.map(r => ({
    key: r.method,
    label: paymentMethodLabel(t, r.method),
    value: parseFloat(r.total || '0'),
    hint: t('reports.dashboard.kpi.methodCount', { count: r.count }),
    tone: METHOD_TONES[r.method] ?? 'neutral'
  }))
})

const isEmpty = computed(() =>
  !props.state.loading && (!props.state.data || slices.value.every(s => s.value === 0))
)

function onSlice(key: string) {
  navigateTo({ path: '/reports/billing', query: { method: key } })
}
</script>

<template>
  <SummaryCard
    :title="t('reports.dashboard.kpi.byMethod')"
    icon="i-lucide-credit-card"
    severity="neutral"
    :loading="state.loading"
    :empty="isEmpty"
  >
    <template #empty>
      {{ t('reports.dashboard.empty.noData') }}
    </template>

    <DonutChart
      :slices="slices"
      :size="148"
      :thickness="16"
      :format-value="format"
      :center-label="t('reports.dashboard.kpi.total')"
      clickable
      @slice-click="onSlice"
    />
  </SummaryCard>
</template>
