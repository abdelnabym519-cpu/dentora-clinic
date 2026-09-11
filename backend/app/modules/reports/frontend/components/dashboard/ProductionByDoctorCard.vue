<script setup lang="ts">
import SummaryCard from '~~/app/components/shared/SummaryCard.vue'
import BarRow from '~~/app/components/charts/BarRow.vue'
import type { PaymentsProfessionalBreakdown } from '../../composables/useReports'

interface Props {
  state: {
    loading: boolean
    error: boolean
    data: PaymentsProfessionalBreakdown[] | null
  }
}

const TOP_N = 8

const props = defineProps<Props>()
const { t } = useI18n()
const { format } = useCurrency()

interface Row {
  key: string
  label: string
  amount: number
  count: number
}

const rows = computed<Row[]>(() => {
  const data = props.state.data ?? []
  const sorted = [...data]
    .map(r => ({
      key: r.professional_id ?? '__unassigned__',
      label: r.professional_name ?? t('reports.dashboard.production.unassigned'),
      amount: parseFloat(r.total_earned || '0'),
      count: r.count || 0
    }))
    .sort((a, b) => b.amount - a.amount)
  if (sorted.length <= TOP_N) return sorted
  const top = sorted.slice(0, TOP_N - 1)
  const rest = sorted.slice(TOP_N - 1)
  const restAmount = rest.reduce((acc, r) => acc + r.amount, 0)
  const restCount = rest.reduce((acc, r) => acc + r.count, 0)
  return [
    ...top,
    {
      key: '__others__',
      label: t('reports.dashboard.production.others'),
      amount: restAmount,
      count: restCount
    }
  ]
})

const maxAmount = computed(() =>
  rows.value.reduce((acc, r) => Math.max(acc, r.amount), 0)
)

const isEmpty = computed(() =>
  !props.state.loading && (!props.state.data || rows.value.length === 0)
)
</script>

<template>
  <SummaryCard
    :title="t('reports.dashboard.charts.productionByDoctor')"
    icon="i-lucide-stethoscope"
    severity="info"
    :loading="state.loading"
    :empty="isEmpty"
    :error="state.error"
    :error-label="t('errors.loadFailed')"
  >
    <template #empty>
      {{ t('reports.dashboard.empty.noData') }}
    </template>
    <ul class="space-y-3">
      <li
        v-for="row in rows"
        :key="row.key"
      >
        <BarRow
          :value="row.amount"
          :max="maxAmount || 1"
          :label="row.label"
          :value-label="format(row.amount)"
          :hint="t('reports.dashboard.production.treatmentCount', { count: row.count })"
          tone="primary"
        />
      </li>
    </ul>
  </SummaryCard>
</template>
