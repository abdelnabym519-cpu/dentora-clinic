<script setup lang="ts">
/**
 * AITreatmentPlanningCard — generate the advisory, evidence-grounded
 * treatment-planning draft and record the dentist accept/reject decision.
 * Plans are never auto-approved (content.no_automatic_execution) and an
 * accepted option is what the deterministic Treatment Simulation consumes.
 */
import { computed, onMounted } from 'vue'
import { PERMISSIONS } from '~~/app/config/permissions'
import { useAITreatmentPlanning } from '../composables/useAITreatmentPlanning'

interface Ctx {
  patient: { id: string }
}

const props = defineProps<{ ctx: Ctx }>()
const { can } = usePermissions()
const planning = useAITreatmentPlanning(() => props.ctx.patient.id)

const canGenerate = computed(() => can(PERMISSIONS.aiTreatmentPlanning.generate))
const canReview = computed(() => can(PERMISSIONS.aiTreatmentPlanning.review))
const result = computed(() => planning.planning.value)

onMounted(() => {
  void planning.load()
})
</script>

<template>
  <SummaryCard
    title="AI Treatment Planning"
    icon="i-lucide-list-checks"
    :loading="planning.loading.value"
  >
    <div
      data-testid="ai-treatment-planning-card"
      class="space-y-3"
    >
      <p class="text-caption text-muted">
        Advisory draft options with per-step evidence. Nothing is executed automatically;
        dentist acceptance is required before the deterministic simulation can run.
      </p>

      <div class="flex flex-wrap items-center justify-between gap-2">
        <p
          v-if="result"
          data-testid="ai-treatment-planning-provenance"
          class="text-subtle text-caption"
        >
          v{{ result.planning_version }} · provider {{ result.provenance.provider }} /
          {{ result.provenance.model }} · review: {{ result.review_status }}
        </p>
        <button
          v-if="canGenerate"
          type="button"
          data-testid="ai-treatment-planning-generate"
          class="rounded border border-default px-2 py-1 text-caption text-muted disabled:opacity-60"
          :disabled="planning.mutating.value"
          @click="planning.generate()"
        >
          {{ planning.mutating.value ? 'Generating…' : result ? 'Regenerate' : 'Generate plan' }}
        </button>
      </div>

      <div
        v-if="planning.error.value"
        data-testid="ai-treatment-planning-error"
        class="rounded-md border border-default bg-elevated p-2 text-caption text-warning"
      >
        {{ planning.error.value }}
      </div>

      <div
        v-if="!result"
        data-testid="ai-treatment-planning-empty"
        class="rounded-md border border-default bg-elevated p-3 text-caption text-muted"
      >
        No AI treatment plan generated yet.
      </div>

      <template v-else>
        <div
          v-for="option in result.content.options"
          :key="option.option_id"
          :data-testid="`ai-plan-option-${option.option_id}`"
          class="rounded-md border border-default p-2 text-caption"
        >
          <p class="font-medium text-default">
            {{ option.title }}
          </p>
          <p class="mt-1 text-subtle">
            {{ option.clinical_intent }}
          </p>
          <p class="mt-1 text-subtle">
            {{ option.rationale }}
          </p>
          <p
            v-if="option.uncertainties.length"
            class="mt-1 text-warning"
          >
            Uncertainties: {{ option.uncertainties.join(' · ') }}
          </p>
          <ol class="mt-1 list-decimal space-y-0.5 pl-4 text-subtle">
            <li
              v-for="step in option.steps"
              :key="step.step_id"
            >
              {{ step.description }} — {{ step.purpose }}
              (evidence: {{ step.evidence_ids.join(', ') }})
            </li>
          </ol>
        </div>

        <div
          v-if="result.content.data_gaps.length"
          data-testid="ai-treatment-planning-gaps"
          class="rounded-md border border-default p-2 text-caption text-subtle"
        >
          Data gaps:
          <span
            v-for="gap in result.content.data_gaps"
            :key="gap.section"
          >{{ gap.section }} ({{ gap.status }}) </span>
        </div>

        <div
          v-if="canReview && result.review_status === 'pending_review'"
          class="flex gap-2"
        >
          <button
            type="button"
            data-testid="ai-treatment-planning-accept"
            class="rounded border border-default px-2 py-1 text-caption text-muted disabled:opacity-60"
            :disabled="planning.mutating.value"
            @click="planning.review('accepted')"
          >
            Dentist: accept
          </button>
          <button
            type="button"
            data-testid="ai-treatment-planning-reject"
            class="rounded border border-default px-2 py-1 text-caption text-muted disabled:opacity-60"
            :disabled="planning.mutating.value"
            @click="planning.review('rejected')"
          >
            Dentist: reject
          </button>
        </div>
        <p
          v-else
          data-testid="ai-treatment-planning-review-state"
          class="text-subtle text-caption"
        >
          Review state: {{ result.review_status }}
          <template v-if="result.review_status === 'accepted'">
            — an accepted option can be simulated in the Treatment Simulation card below.
          </template>
        </p>
      </template>
    </div>
  </SummaryCard>
</template>
