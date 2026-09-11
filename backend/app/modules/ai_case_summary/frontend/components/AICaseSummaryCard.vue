<script setup lang="ts">
/**
 * AICaseSummaryCard — generate and review the advisory, evidence-traceable
 * AI case summary inside the patient workflow. Every result stays advisory
 * (content.advisory_only) and requires an explicit dentist review decision
 * (accepted/rejected) which the backend enforces.
 */
import { computed, onMounted } from 'vue'
import { PERMISSIONS } from '~~/app/config/permissions'
import { useAICaseSummary } from '../composables/useAICaseSummary'

interface Ctx {
  patient: { id: string }
}

const props = defineProps<{ ctx: Ctx }>()
const { can } = usePermissions()
const summary = useAICaseSummary(() => props.ctx.patient.id)

const canGenerate = computed(() => can(PERMISSIONS.aiCaseSummary.generate))
const canReview = computed(() => can(PERMISSIONS.aiCaseSummary.review))
const result = computed(() => summary.summary.value)

onMounted(() => {
  void summary.load()
})
</script>

<template>
  <SummaryCard
    title="AI Case Summary"
    icon="i-lucide-sparkles"
    :loading="summary.loading.value"
  >
    <div
      data-testid="ai-case-summary-card"
      class="space-y-3"
    >
      <p class="text-caption text-muted">
        Advisory, evidence-traceable summary generated from the redacted CaseSnapshot.
        Not a diagnosis. Dentist review is mandatory.
      </p>

      <div class="flex flex-wrap items-center justify-between gap-2">
        <p
          v-if="result"
          data-testid="ai-case-summary-provenance"
          class="text-subtle text-caption"
        >
          v{{ result.summary_version }} · provider {{ result.provenance.provider }} /
          {{ result.provenance.model }} · review: {{ result.review_status }}
        </p>
        <button
          v-if="canGenerate"
          type="button"
          data-testid="ai-case-summary-generate"
          class="rounded border border-default px-2 py-1 text-caption text-muted disabled:opacity-60"
          :disabled="summary.mutating.value"
          @click="summary.generate()"
        >
          {{ summary.mutating.value ? 'Generating…' : result ? 'Regenerate' : 'Generate summary' }}
        </button>
      </div>

      <div
        v-if="summary.error.value"
        data-testid="ai-case-summary-error"
        class="rounded-md border border-default bg-elevated p-2 text-caption text-warning"
      >
        {{ summary.error.value }}
      </div>

      <div
        v-if="!result"
        data-testid="ai-case-summary-empty"
        class="rounded-md border border-default bg-elevated p-3 text-caption text-muted"
      >
        No AI case summary generated yet.
      </div>

      <template v-else>
        <ul class="space-y-2">
          <li
            v-for="claim in result.content.claims"
            :key="claim.claim_id"
            :data-testid="`ai-case-summary-claim-${claim.claim_id}`"
            class="rounded-md border border-default p-2 text-caption"
          >
            <p class="text-default">
              {{ claim.text }}
            </p>
            <p class="mt-1 text-subtle">
              Evidence: {{ claim.evidence_ids.length ? claim.evidence_ids.join(', ') : 'none' }}
            </p>
            <p
              v-if="claim.uncertainty"
              class="mt-1 text-warning"
            >
              Uncertainty: {{ claim.uncertainty }}
            </p>
          </li>
        </ul>

        <div
          v-if="result.content.data_gaps.length"
          data-testid="ai-case-summary-gaps"
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
            data-testid="ai-case-summary-accept"
            class="rounded border border-default px-2 py-1 text-caption text-muted disabled:opacity-60"
            :disabled="summary.mutating.value"
            @click="summary.review('accepted')"
          >
            Dentist: accept
          </button>
          <button
            type="button"
            data-testid="ai-case-summary-reject"
            class="rounded border border-default px-2 py-1 text-caption text-muted disabled:opacity-60"
            :disabled="summary.mutating.value"
            @click="summary.review('rejected')"
          >
            Dentist: reject
          </button>
        </div>
        <p
          v-else
          data-testid="ai-case-summary-review-state"
          class="text-subtle text-caption"
        >
          Review state: {{ result.review_status }}
        </p>
      </template>
    </div>
  </SummaryCard>
</template>
