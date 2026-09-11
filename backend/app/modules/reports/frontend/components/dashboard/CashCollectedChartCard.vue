<script setup lang="ts">
import SummaryCard from '~~/app/components/shared/SummaryCard.vue'
import TrendAreaChart from '~~/app/components/charts/TrendAreaChart.vue'
import type { PaymentsTrends } from '../../composables/useReports'

interface Props {
  state: {
    loading: boolean
    error: boolean
    data: PaymentsTrends | null
  }
}

const props = defineProps<Props>()
const { t, locale } = useI18n()
const { format } = useCurrency()

const series = computed(() =>
  (props.state.data?.points ?? []).map(p => ({
    x: p.bucket_start,
    y: parseFloat(p.collected || '0')
  }))
)

const refunds = computed(() =>
  (props.state.data?.points ?? []).map(p => ({
    x: p.bucket_start,
    y: parseFloat(p.refunded || '0')
  }))
)

const isEmpty = computed(() =>
  !props.state.loading && series.value.length < 2
)

function formatX(x: string): string {
  try {
    const d = new Date(`${x}T00:00:00`)
    return new Intl.DateTimeFormat(locale.value, {
      day: '2-digit',
      month: 'short'
    }).format(d)
  } catch {
    return x
  }
}

function onPoint(x: string) {
  navigateTo({ path: '/reports/billing', query: { date: x } })
}
</script>

<template>
  <SummaryCard
    :title="t('reports.dashboard.charts.cashOverTime')"
    icon="i-lucide-line-chart"
    severity="success"
    :loading="state.loading"
    :empty="isEmpty"
    :error="state.error"
    :error-label="t('errors.loadFailed')"
  >
    <template #empty>
      {{ t('reports.dashboard.empty.noData') }}
    </template>
    <TrendAreaChart
      :series="series"
      :comparison="refunds"
      tone="success"
      comparison-tone="danger"
      :format-y="format"
      :format-x="formatX"
      :series-label="t('reports.dashboard.kpi.cashCollected')"
      :comparison-label="t('reports.dashboard.charts.refunded')"
      @point-click="onPoint"
    />
  </SummaryCard>
</template>
