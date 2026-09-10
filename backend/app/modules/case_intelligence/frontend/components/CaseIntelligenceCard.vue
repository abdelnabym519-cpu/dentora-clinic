<script setup lang="ts">
/**
 * CaseIntelligenceCard — the deterministic evidence foundation surfaced
 * in the patient Summary workflow. Shows the server-built CaseSnapshot
 * (per-section availability + evidence counts). Case Intelligence
 * performs NO AI reasoning by design (ADR 0027); it is the input the
 * advisory AI modules consume.
 */
import { onMounted } from 'vue'
import { useCaseIntelligence } from '../composables/useCaseIntelligence'

interface Ctx {
  patient: { id: string }
}

const props = defineProps<{ ctx: Ctx }>()
const ci = useCaseIntelligence(() => props.ctx.patient.id)

onMounted(() => {
  void ci.load()
})
</script>

<template>
  <SummaryCard
    title="Case Intelligence (Evidence Snapshot)"
    icon="i-lucide-folder-search"
    :loading="ci.loading.value"
  >
    <div
      data-testid="case-intelligence-card"
      class="space-y-3"
    >
      <p class="text-caption text-muted">
        Deterministic aggregation of existing clinical evidence. No AI reasoning, no diagnosis.
        Advisory AI modules consume this snapshot.
      </p>

      <div
        v-if="ci.error.value"
        data-testid="case-intelligence-error"
        class="rounded-md border border-default bg-elevated p-2 text-caption text-warning"
      >
        {{ ci.error.value }}
      </div>

      <div
        v-if="!ci.snapshot.value"
        data-testid="case-intelligence-empty"
        class="rounded-md border border-default bg-elevated p-3 text-caption text-muted"
      >
        No case snapshot available yet.
      </div>

      <template v-else>
        <p
          data-testid="case-intelligence-version"
          class="text-subtle text-caption"
        >
          Snapshot v{{ ci.snapshot.value.case_snapshot_version }} ·
          {{ Object.keys(ci.snapshot.value.availability).length }} tracked sections
        </p>
        <div class="grid gap-2 md:grid-cols-2">
          <div
            v-for="section in ci.sectionSummary.value"
            :key="section.name"
            :data-testid="`case-section-${section.name}`"
            class="rounded-md border border-default p-2 text-caption"
          >
            <div class="flex items-center justify-between gap-2">
              <span class="font-medium text-default">{{ section.name.replaceAll('_', ' ') }}</span>
              <span class="rounded border border-default px-1.5 py-0.5 text-subtle">{{ section.status }}</span>
            </div>
            <p class="mt-1 text-subtle">
              Evidence: {{ section.evidenceCount }}
              <template v-if="section.reason">
                · {{ section.reason }}
              </template>
            </p>
          </div>
        </div>
      </template>
    </div>
  </SummaryCard>
</template>
