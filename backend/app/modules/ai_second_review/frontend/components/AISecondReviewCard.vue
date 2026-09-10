<script setup lang="ts">
/**
 * AISecondReviewCard — run the advisory AI second review over an existing
 * treatment simulation and record the explicit dentist review. The UI
 * makes it impossible to confuse this with an autonomous decision:
 * advisory_only / no_treatment_approval / approves_treatment=false are
 * displayed with the result.
 */
import { computed, onMounted } from 'vue'
import { PERMISSIONS } from '~~/app/config/permissions'
import { useAISecondReview } from '../composables/useAISecondReview'

interface Ctx {
  patient: { id: string }
}

const props = defineProps<{ ctx: Ctx }>()
const { can } = usePermissions()
const second = useAISecondReview(() => props.ctx.patient.id)

const canGenerate = computed(() => can(PERMISSIONS.aiSecondReview.generate))
const canReview = computed(() => can(PERMISSIONS.aiSecondReview.review))
const result = computed(() => second.review.value)
const selectedSimulationId = ref('')

onMounted(() => {
  void Promise.all([second.load(), second.loadSimulations()])
})

async function generate(): Promise<void> {
  if (!selectedSimulationId.value) return
  await second.generate(selectedSimulationId.value)
}
</script>

<template>
  <SummaryCard
    title="AI Second Review"
    icon="i-lucide-scan-search"
    :loading="second.loading.value"
  >
    <div
      data-testid="ai-second-review-card"
      class="space-y-3"
    >
      <p class="text-caption text-muted">
        Advisory re-check of the AI planning → simulation chain. It approves nothing and
        mutates no canonical record — a dentist must review the findings.
      </p>

      <div
        v-if="second.error.value"
        data-testid="ai-second-review-error"
        class="rounded-md border border-default bg-elevated p-2 text-caption text-warning"
      >
        {{ second.error.value }}
      </div>

      <div
        v-if="canGenerate && second.simulations.value.length"
        class="flex flex-wrap items-center gap-2"
      >
        <select
          v-model="selectedSimulationId"
          data-testid="ai-second-review-simulation"
          class="rounded border border-default bg-default px-2 py-1 text-caption text-default"
        >
          <option
            value=""
            disabled
          >
            Select simulation…
          </option>
          <option
            v-for="sim in second.simulations.value"
            :key="sim.id"
            :value="sim.id"
          >
            Simulation v{{ sim.simulation_version }}
          </option>
        </select>
        <button
          type="button"
          data-testid="ai-second-review-generate"
          class="rounded border border-default px-2 py-1 text-caption text-muted disabled:opacity-60"
          :disabled="second.mutating.value || !selectedSimulationId"
          @click="generate()"
        >
          {{ second.mutating.value ? 'Reviewing…' : 'Run second review' }}
        </button>
      </div>
      <p
        v-else-if="canGenerate"
        data-testid="ai-second-review-no-simulation"
        class="rounded-md border border-default bg-elevated p-3 text-caption text-muted"
      >
        A treatment simulation of an accepted plan is required before a second review can run.
      </p>

      <div
        v-if="!result"
        data-testid="ai-second-review-empty"
        class="rounded-md border border-default bg-elevated p-3 text-caption text-muted"
      >
        No AI second review generated yet.
      </div>

      <template v-else>
        <p
          data-testid="ai-second-review-banner"
          class="rounded-md border border-default p-2 text-caption text-subtle"
        >
          advisory only · approves treatment: {{ result.approves_treatment }} · no canonical
          record mutation · snapshot v{{ result.chain_reference.case_snapshot_version }}
        </p>
        <ul class="space-y-2">
          <li
            v-for="finding in result.content.findings"
            :key="finding.finding_id"
            :data-testid="`ai-second-review-finding-${finding.finding_id}`"
            class="rounded-md border border-default p-2 text-caption"
          >
            <div class="flex items-center justify-between gap-2">
              <span class="font-medium text-default">{{ finding.category.replaceAll('_', ' ') }}</span>
              <span class="rounded border border-default px-1.5 py-0.5 text-subtle">{{ finding.finding_id }}</span>
            </div>
            <p class="mt-1 text-subtle">
              {{ finding.statement }}
            </p>
            <p class="mt-1 text-subtle">
              Evidence: {{ finding.evidence_ids.length ? finding.evidence_ids.join(', ') : 'none' }}
            </p>
          </li>
        </ul>

        <div
          v-if="result.content.data_gaps.length"
          data-testid="ai-second-review-gaps"
          class="rounded-md border border-default p-2 text-caption text-subtle"
        >
          Data gaps:
          <span
            v-for="gap in result.content.data_gaps"
            :key="gap.section"
          >{{ gap.section }} ({{ gap.status }}) </span>
        </div>

        <div
          v-if="canReview && !result.review_status.includes('reviewed')"
          class="flex gap-2"
        >
          <button
            type="button"
            data-testid="ai-second-review-mark-reviewed"
            class="rounded border border-default px-2 py-1 text-caption text-muted disabled:opacity-60"
            :disabled="second.mutating.value"
            @click="second.markReviewed()"
          >
            Dentist: mark reviewed
          </button>
        </div>
        <p
          v-else
          data-testid="ai-second-review-state"
          class="text-subtle text-caption"
        >
          Review state: {{ result.review_status }} · provider
          {{ result.provenance.provider }} / {{ result.provenance.model }}
        </p>
      </template>
    </div>
  </SummaryCard>
</template>
