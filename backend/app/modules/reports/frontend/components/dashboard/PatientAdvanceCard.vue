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

// patient_credit_total comes from PaymentsSummary as an aggregate over the
// full clinic — even though the endpoint accepts a date range, the credit
// total it returns is a point-in-time figure. We surface that with the
// "snapshot" badge so the user doesn't read it as filterable.
const value = computed(() => {
  const d = props.state.data
  if (!d) return '—'
  return format(parseFloat(d.patient_credit_total))
})

const isEmpty = computed(() => !props.state.loading && !props.state.data)
</script>

<template>
  <KpiTile
    :title="t('reports.dashboard.kpi.patientAdvance')"
    icon="i-lucide-piggy-bank"
    severity="info"
    :loading="state.loading"
    :empty="isEmpty"
    :error="state.error"
    :error-label="t('errors.loadFailed')"
    :value="value"
    :hint="t('reports.dashboard.kpi.patientAdvanceHint')"
    snapshot
    :snapshot-label="t('reports.dashboard.snapshotBadge')"
  >
    <template #empty>
      {{ t('reports.dashboard.empty.noData') }}
    </template>
  </KpiTile>
</template>
