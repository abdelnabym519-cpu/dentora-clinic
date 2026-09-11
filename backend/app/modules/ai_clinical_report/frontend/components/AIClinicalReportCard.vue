<script setup lang="ts">
/**
 * AIClinicalReportCard — compiles the advisory clinical-AI pipeline
 * (context → risk → planning → second review) into one report view.
 * Explicitly displays readiness gates, limitations, provenance and the
 * no-autonomous-decision flags on every render.
 */
import { computed, onMounted } from 'vue'
import { PERMISSIONS } from '~~/app/config/permissions'
import { useAIClinicalReport } from '../composables/useAIClinicalReport'

interface Ctx {
  patient: { id: string }
}

const props = defineProps<{ ctx: Ctx }>()
const { can } = usePermissions()
const report = useAIClinicalReport(() => props.ctx.patient.id)

const canGenerate = computed(() => can(PERMISSIONS.aiClinicalReport.generate))
const ready = computed(() => report.readiness.value?.ready_for_report ?? false)

onMounted(() => {
  void report.loadReadiness()
})
</script>

<template>
  <SummaryCard
    title="AI Clinical Report"
    icon="i-lucide-file-text"
    :loading="report.loading.value"
  >
    <div
      data-testid="ai-clinical-report-card"
      class="space-y-3"
    >
      <p class="text-caption text-muted">
        Advisory compilation of the clinical-AI pipeline. No autonomous diagnosis and no
        autonomous treatment decision — dentist review is required.
      </p>

      <div
        v-if="report.readiness.value"
        data-testid="ai-clinical-report-readiness"
        class="rounded-md border border-default p-2 text-caption"
      >
        <span class="font-medium text-default">
          Readiness: {{ ready ? 'ready' : 'not ready' }}
        </span>
        <p
          v-if="report.readiness.value.missing_or_stale.length"
          class="mt-1 text-subtle"
        >
          Missing or stale: {{ report.readiness.value.missing_or_stale.join(', ') }}
        </p>
        <ul class="mt-1 space-y-0.5 text-subtle">
          <li
            v-for="stage in report.readiness.value.stages"
            :key="stage.stage"
          >
            {{ stage.stage }}: {{ stage.state }}
          </li>
        </ul>
      </div>

      <button
        v-if="canGenerate"
        type="button"
        data-testid="ai-clinical-report-generate"
        class="rounded border border-default px-2 py-1 text-caption text-muted disabled:opacity-60"
        :disabled="report.mutating.value"
        @click="report.generate()"
      >
        {{ report.mutating.value ? 'Generating…' : 'Generate report' }}
      </button>

      <div
        v-if="report.error.value"
        data-testid="ai-clinical-report-error"
        class="rounded-md border border-default bg-elevated p-2 text-caption text-warning"
      >
        {{ report.error.value }}
      </div>

      <div
        v-if="!report.report.value"
        data-testid="ai-clinical-report-empty"
        class="rounded-md border border-default bg-elevated p-3 text-caption text-muted"
      >
        No AI clinical report generated in this session.
      </div>

      <template v-else>
        <div
          v-for="section in report.report.value.sections"
          :key="section.section"
          :data-testid="`ai-clinical-report-section-${section.section}`"
          class="rounded-md border border-default p-2 text-caption"
        >
          <p class="font-medium text-default">
            {{ section.section.replaceAll('_', ' ') }}
          </p>
          <ul class="mt-1 space-y-1 text-subtle">
            <li
              v-for="(claim, i) in section.claims"
              :key="i"
            >
              {{ claim.text }}
              <span v-if="claim.evidence_ids.length"> (evidence: {{ claim.evidence_ids.join(', ') }})</span>
            </li>
          </ul>
        </div>
        <div
          v-if="report.report.value.limitations.length"
          data-testid="ai-clinical-report-limitations"
          class="rounded-md border border-default p-2 text-caption text-warning"
        >
          Limitations: {{ report.report.value.limitations.join(' · ') }}
        </div>
        <p
          data-testid="ai-clinical-report-provenance"
          class="text-subtle text-caption"
        >
          provider {{ report.report.value.provenance.provider }} /
          {{ report.report.value.provenance.model }} · status
          {{ report.report.value.status }} · advisory only, dentist review required
        </p>
      </template>
    </div>
  </SummaryCard>
</template>
