<script setup lang="ts">
/**
 * ClinicalCopilotCard — the guarded advisory surface for the clinical
 * workflow (distinct from the generic Copilot chat). Readiness gates are
 * displayed up-front; dentist control is enforced server-side and restated
 * in the UI. Provider unavailability is surfaced explicitly.
 */
import { computed, onMounted, ref } from 'vue'
import { PERMISSIONS } from '~~/app/config/permissions'
import { useClinicalCopilot, type CopilotFocus } from '../composables/useClinicalCopilot'

interface Ctx {
  patient: { id: string }
}

const props = defineProps<{ ctx: Ctx }>()
const { can } = usePermissions()
const copilot = useClinicalCopilot(() => props.ctx.patient.id)

const canUse = computed(() => can(PERMISSIONS.clinicalCopilot.use))
const context = computed(() => copilot.context.value)
const ready = computed(() => context.value?.ready_for_advice ?? false)

const FOCUS_OPTIONS: Array<{ value: CopilotFocus, label: string }> = [
  { value: 'case_review', label: 'Case review' },
  { value: 'risk_context', label: 'Risk context' },
  { value: 'treatment_options', label: 'Treatment options' },
  { value: 'simulation_context', label: 'Simulation context' },
  { value: 'second_review', label: 'Second review' }
]
const focus = ref<CopilotFocus>('case_review')

onMounted(() => {
  void copilot.loadContext()
})
</script>

<template>
  <SummaryCard
    title="Clinical Copilot (Guarded Advisory)"
    icon="i-lucide-stethoscope"
    :loading="copilot.loading.value"
  >
    <div
      data-testid="clinical-copilot-card"
      class="space-y-3"
    >
      <p class="text-caption text-muted">
        Evidence-grounded second-opinion advisory with readiness gates. Never a diagnosis and
        never a treatment approval — dentist control is required at all times.
      </p>

      <div
        v-if="context"
        data-testid="clinical-copilot-context"
        class="rounded-md border border-default p-2 text-caption"
      >
        <span class="font-medium text-default">
          Readiness: {{ ready ? 'ready' : 'not ready' }}
        </span>
        <ul class="mt-1 space-y-0.5 text-subtle">
          <li
            v-for="stage in context.stages"
            :key="stage.stage"
          >
            {{ stage.stage }}: {{ stage.state }}
          </li>
        </ul>
        <p
          v-if="context.missing_or_stale.length"
          class="mt-1 text-warning"
        >
          Missing or stale: {{ context.missing_or_stale.join(', ') }}
        </p>
      </div>

      <div
        v-if="canUse"
        class="flex flex-wrap items-center gap-2"
      >
        <select
          v-model="focus"
          data-testid="clinical-copilot-focus"
          class="rounded border border-default bg-default px-2 py-1 text-caption text-default"
        >
          <option
            v-for="option in FOCUS_OPTIONS"
            :key="option.value"
            :value="option.value"
          >
            {{ option.label }}
          </option>
        </select>
        <button
          type="button"
          data-testid="clinical-copilot-advise"
          class="rounded border border-default px-2 py-1 text-caption text-muted disabled:opacity-60"
          :disabled="copilot.mutating.value"
          @click="copilot.advise(focus)"
        >
          {{ copilot.mutating.value ? 'Advising…' : 'Request advisory' }}
        </button>
      </div>

      <div
        v-if="copilot.error.value"
        data-testid="clinical-copilot-error"
        class="rounded-md border border-default bg-elevated p-2 text-caption text-warning"
      >
        {{ copilot.error.value }}
      </div>

      <div
        v-if="!copilot.advisory.value"
        data-testid="clinical-copilot-empty"
        class="rounded-md border border-default bg-elevated p-3 text-caption text-muted"
      >
        No advisory requested in this session.
      </div>

      <template v-else>
        <ul class="space-y-2">
          <li
            v-for="(claim, i) in copilot.advisory.value.claims"
            :key="i"
            :data-testid="`clinical-copilot-claim-${i}`"
            class="rounded-md border border-default p-2 text-caption"
          >
            <p class="text-default">
              {{ claim.text }}
            </p>
            <p class="mt-1 text-subtle">
              Evidence: {{ claim.evidence_ids.length ? claim.evidence_ids.join(', ') : 'none' }}
            </p>
          </li>
        </ul>
        <div
          v-if="copilot.advisory.value.limitations.length"
          data-testid="clinical-copilot-limitations"
          class="rounded-md border border-default p-2 text-caption text-warning"
        >
          Limitations: {{ copilot.advisory.value.limitations.join(' · ') }}
        </div>
        <p
          data-testid="clinical-copilot-provenance"
          class="text-subtle text-caption"
        >
          provider {{ copilot.advisory.value.provenance.provider }} /
          {{ copilot.advisory.value.provenance.model }} · advisory only · dentist review
          required · no autonomous diagnosis or treatment decision
        </p>
      </template>
    </div>
  </SummaryCard>
</template>
