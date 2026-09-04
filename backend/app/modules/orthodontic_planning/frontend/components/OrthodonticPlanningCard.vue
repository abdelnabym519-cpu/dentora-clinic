<script setup lang="ts">
/**
 * OrthodonticPlanningCard — smart-card for the patient Resumen grid.
 *
 * Registered into `patient.summary.cards` by the orthodontic_planning
 * module. Read-only decision-support status: shows whether the case is
 * sufficiently documented for planning, and the state of the latest
 * plan proposal (score/confidence/stages). Proposal generation and
 * review happen in the clinical flow (API-first in v0.1).
 */
import type { PatientExtended } from '~~/app/types'

interface Ctx {
  patient: PatientExtended
}

const props = defineProps<{ ctx: Ctx }>()

const { t } = useI18n()

const patientId = computed(() => props.ctx.patient.id)

const patientIdGetter = (): string => props.ctx.patient.id

const {
  latestAssessment,
  latestProposal,
  hasProposals,
  isLoading,
  fetchCase
} = useOrthodonticPlanning(patientIdGetter)

await useAsyncData(
  () => `orthodontic_planning:summary-card:${patientId.value}`,
  async () => {
    await fetchCase()
    return true
  },
  { watch: [patientId], server: false }
)

const severity = computed<'neutral' | 'info' | 'warning'>(() => {
  const proposal = latestProposal.value
  if (proposal?.status === 'approved') return 'info'
  if (proposal && proposal.soft_finding_count > 0) return 'warning'
  if (proposal) return 'info'
  return 'neutral'
})

const statusLabel = computed(() => {
  const proposal = latestProposal.value
  if (!proposal) {
    return latestAssessment.value?.is_plannable
      ? t('orthodontic_planning.card.ready', 'Ready to plan')
      : t('orthodontic_planning.card.needsData', 'Needs case data')
  }
  return t(`orthodontic_planning.status.${proposal.status}`, proposal.status)
})
</script>

<template>
  <SummaryCard
    :title="t('orthodontic_planning.card.title', 'Orthodontic planning')"
    icon="i-lucide-braces"
    :severity="severity"
    :loading="isLoading"
    :empty="!latestAssessment && !hasProposals"
    :to="`/patients/${patientId}?tab=clinical&clinicalMode=diagnosis`"
  >
    <template #empty>
      {{ t('orthodontic_planning.card.empty', 'No orthodontic assessment recorded.') }}
    </template>

    <div class="space-y-1.5">
      <div class="flex items-baseline gap-1">
        <span class="text-h2 text-default">{{ statusLabel }}</span>
      </div>
      <ul
        v-if="latestProposal"
        class="space-y-0.5 text-caption text-muted"
      >
        <li class="tnum">
          · {{ t('orthodontic_planning.card.stages', 'Stages') }}:
          {{ latestProposal.stage_count }}
          (~{{ latestProposal.planned_months }}
          {{ t('orthodontic_planning.card.months', 'months') }})
        </li>
        <li class="tnum">
          · {{ t('orthodontic_planning.card.score', 'Score') }}:
          {{ latestProposal.score.toFixed(2) }}
          · {{ t('orthodontic_planning.card.confidence', 'Confidence') }}:
          {{ (latestProposal.confidence * 100).toFixed(0) }}%
        </li>
        <li
          v-if="latestProposal.soft_finding_count > 0"
          class="text-warning"
        >
          · {{ latestProposal.soft_finding_count }}
          {{ t('orthodontic_planning.card.findings', 'clinical finding(s) to review') }}
        </li>
      </ul>
      <p
        v-else-if="latestAssessment && !latestAssessment.is_plannable"
        class="text-caption text-muted"
      >
        {{ t('orthodontic_planning.card.incomplete', 'Assessment incomplete — chart the odontogram and measurements to enable planning.') }}
      </p>
    </div>

    <template #footer>
      <span>{{ t('orthodontic_planning.card.open', 'Open clinical tab') }}</span>
    </template>
  </SummaryCard>
</template>
