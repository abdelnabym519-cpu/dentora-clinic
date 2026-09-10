<script setup lang="ts">
/**
 * TreatmentSimulationCard — deterministic simulation of ONE explicitly
 * selected option from a dentist-ACCEPTED AI treatment plan. The backend
 * rejects anything else (requires_accepted_plan). The scene is explicitly
 * non-synthetic and never mutates source geometry.
 */
import { computed, onMounted } from 'vue'
import { PERMISSIONS } from '~~/app/config/permissions'
import { useTreatmentSimulation } from '../composables/useTreatmentSimulation'

interface Ctx {
  patient: { id: string }
}

const props = defineProps<{ ctx: Ctx }>()
const { can } = usePermissions()
const simulation = useTreatmentSimulation(() => props.ctx.patient.id)

const canGenerate = computed(() => can(PERMISSIONS.treatmentSimulation.generate))
const plan = computed(() => simulation.acceptedPlan.value)
const accepted = computed(() => plan.value !== null)
const result = computed(() => simulation.simulation.value)
const selectedOptionId = ref('')

onMounted(() => {
  void Promise.all([simulation.loadLatest(), simulation.loadAcceptedPlan()])
})

async function runSimulation(): Promise<void> {
  if (!plan.value || !selectedOptionId.value) return
  await simulation.simulate(plan.value.id, selectedOptionId.value)
}
</script>

<template>
  <SummaryCard
    title="Treatment Simulation (Deterministic)"
    icon="i-lucide-timeline"
    :loading="simulation.loading.value"
  >
    <div
      data-testid="treatment-simulation-card"
      class="space-y-3"
    >
      <p class="text-caption text-muted">
        Deterministic, non-predictive timeline for one option of a dentist-ACCEPTED AI plan.
        No autonomous treatment execution.
      </p>

      <div
        v-if="simulation.error.value"
        data-testid="treatment-simulation-error"
        class="rounded-md border border-default bg-elevated p-2 text-caption text-warning"
      >
        {{ simulation.error.value }}
      </div>

      <div
        v-if="!accepted"
        data-testid="treatment-simulation-no-plan"
        class="rounded-md border border-default bg-elevated p-3 text-caption text-muted"
      >
        No dentist-accepted AI treatment plan available. Generate and accept a plan in the
        AI Treatment Planning card above to unlock simulation.
      </div>

      <template v-else-if="canGenerate">
        <div class="flex flex-wrap items-center gap-2">
          <select
            v-model="selectedOptionId"
            data-testid="treatment-simulation-option"
            class="rounded border border-default bg-default px-2 py-1 text-caption text-default"
          >
            <option
              value=""
              disabled
            >
              Select accepted option…
            </option>
            <option
              v-for="option in plan!.content.options"
              :key="option.option_id"
              :value="option.option_id"
            >
              {{ option.title }}
            </option>
          </select>
          <button
            type="button"
            data-testid="treatment-simulation-run"
            class="rounded border border-default px-2 py-1 text-caption text-muted disabled:opacity-60"
            :disabled="simulation.mutating.value || !selectedOptionId"
            @click="runSimulation()"
          >
            {{ simulation.mutating.value ? 'Simulating…' : 'Simulate option' }}
          </button>
        </div>
      </template>

      <div
        v-if="!result"
        data-testid="treatment-simulation-empty"
        class="rounded-md border border-default bg-elevated p-3 text-caption text-muted"
      >
        No simulation has been generated yet.
      </div>

      <template v-else>
        <p
          data-testid="treatment-simulation-meta"
          class="text-subtle text-caption"
        >
          Simulation v{{ result.simulation_version }} · renderer
          {{ result.scene.renderer }} · frame {{ result.scene.coordinate_space }} ·
          risk map: {{ result.scene.risk_map.status }}
        </p>
        <ol class="list-decimal space-y-1 pl-4 text-caption text-subtle">
          <li
            v-for="checkpoint in result.scene.checkpoints"
            :key="checkpoint.checkpoint_id"
            :data-testid="`treatment-simulation-checkpoint-${checkpoint.checkpoint_id}`"
            :class="{ 'font-medium text-default': checkpoint.checkpoint_id === result.scene.selected_checkpoint_id }"
          >
            {{ checkpoint.label || checkpoint.checkpoint_id }}
            <template v-if="checkpoint.description">
              — {{ checkpoint.description }}
            </template>
          </li>
        </ol>
        <p class="text-subtle text-caption">
          Advisory visualization only — the plan itself is only executed through the normal
          canonical treatment-plan workflow by the clinic.
        </p>
      </template>
    </div>
  </SummaryCard>
</template>
