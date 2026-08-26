<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { PERMISSIONS } from '~~/app/config/permissions'
import {
  useDental3DAlignment,
  useDental3DNerveDetection,
  useDental3DScene
} from '../composables/useDental3DScene'
import { useDental3DImplantPlanning } from '../composables/useDental3DImplantPlanning'
import { useRiskEngine } from '../composables/useRiskEngine'
import { buildClinicalScene } from '../lib/clinicalScene'
import { withImplantPlanning } from '../lib/implantScene'
import { withRiskMap } from '../lib/riskMap'

interface Ctx {
  patient: { id: string }
}

const props = defineProps<{ ctx: Ctx }>()
const { can } = usePermissions()
const { data: scene } = useDental3DScene(() => props.ctx.patient.id)
const { alignment, load: loadAlignment } = useDental3DAlignment(() => props.ctx.patient.id)
const { analysis: nerve, load: loadNerve } = useDental3DNerveDetection(() => props.ctx.patient.id)
const planning = useDental3DImplantPlanning(() => props.ctx.patient.id)
const risk = useRiskEngine(() => props.ctx.patient.id)

const canGenerate = computed(() => can(PERMISSIONS.riskEngine.generate))
const canReview = computed(() => can(PERMISSIONS.riskEngine.review))
const result = computed(() => risk.result.value)
const factors = computed(() => result.value?.factors ?? [])
const clinicalScene = computed(() => withRiskMap(
  withImplantPlanning(
    buildClinicalScene(scene.value ?? null, alignment.value, nerve.value),
    planning.snapshot.value
  ),
  result.value
))

onMounted(() => {
  void Promise.all([
    loadAlignment(),
    loadNerve(),
    planning.load(),
    risk.load()
  ])
})

function stateLabel(state: string): string {
  return state.replaceAll('_', ' ')
}
</script>

<template>
  <SummaryCard
    title="Risk Engine + 3D Risk Map"
    icon="i-lucide-shield-alert"
    :loading="risk.loading.value"
  >
    <div
      data-testid="risk-engine-card"
      class="space-y-3"
    >
      <div class="flex flex-wrap items-start justify-between gap-2">
        <div class="space-y-1">
          <p class="text-caption text-muted">
            Deterministic observed-fact decision support. No diagnosis, score, clinical threshold,
            HU assumption, or automatic treatment decision.
          </p>
          <p
            v-if="result"
            data-testid="risk-engine-provenance"
            class="text-subtle text-caption"
          >
            Snapshot v{{ result.provenance.case_snapshot_version }} · engine
            {{ result.provenance.engine_version }} · policy {{ result.provenance.policy_version }} ·
            review {{ result.review_status }}
          </p>
        </div>
        <button
          v-if="canGenerate"
          type="button"
          data-testid="risk-engine-generate"
          class="rounded border border-default px-2 py-1 text-caption text-muted disabled:opacity-60"
          :disabled="risk.mutating.value"
          @click="risk.generate()"
        >
          {{ result ? 'Re-evaluate' : 'Generate' }}
        </button>
      </div>

      <div
        v-if="risk.error.value"
        data-testid="risk-engine-error"
        class="rounded-md border border-default bg-elevated p-2 text-caption text-warning"
      >
        {{ risk.error.value }}
      </div>

      <div
        v-if="!result"
        data-testid="risk-engine-empty"
        class="rounded-md border border-default bg-elevated p-3 text-caption text-muted"
      >
        No Risk Engine result has been materialized for the current CaseSnapshot.
      </div>

      <template v-else>
        <div class="grid gap-2 md:grid-cols-2">
          <div
            v-for="factor in factors"
            :key="factor.factor_id"
            :data-testid="`risk-factor-${factor.factor_id}`"
            class="rounded-md border border-default p-2 text-caption"
          >
            <div class="flex items-start justify-between gap-2">
              <span class="font-medium text-default">{{ factor.label }}</span>
              <span class="rounded border border-default px-1.5 py-0.5 text-subtle">
                {{ stateLabel(factor.state) }}
              </span>
            </div>
            <p class="mt-1 text-subtle">
              {{ factor.semantics }}
            </p>
            <p class="mt-1 text-subtle">
              Evidence: {{ factor.evidence_ids.length ? factor.evidence_ids.join(', ') : 'data gap' }}
            </p>
          </div>
        </div>

        <div
          data-testid="risk-map-status"
          class="rounded-md border border-default p-2 text-caption"
        >
          <span class="font-medium text-default">3D Risk Map: {{ result.risk_map.status }}</span>
          <p class="mt-1 text-subtle">
            Advisory evidence-state visualization only. Display bands are not clinical risk bands.
          </p>
          <p
            v-if="result.risk_map.status === 'unavailable'"
            class="mt-1 text-warning"
          >
            {{ result.risk_map.reason ?? 'Required validated patient-space evidence is unavailable.' }}
            No synthetic geometry is shown.
          </p>
        </div>

        <Dental3DViewer
          :clinical-scene="clinicalScene"
          :height="360"
        />

        <div
          v-if="result.review_status === 'pending_review'"
          class="flex flex-wrap items-center gap-2 border-t border-default pt-2"
        >
          <span class="text-caption text-muted">Dentist review required before accepted use.</span>
          <template v-if="canReview">
            <button
              type="button"
              data-testid="risk-engine-accept"
              class="rounded border border-default px-2 py-1 text-caption text-muted disabled:opacity-60"
              :disabled="risk.mutating.value"
              @click="risk.review('accepted')"
            >
              Accept
            </button>
            <button
              type="button"
              data-testid="risk-engine-reject"
              class="rounded border border-default px-2 py-1 text-caption text-muted disabled:opacity-60"
              :disabled="risk.mutating.value"
              @click="risk.review('rejected')"
            >
              Reject
            </button>
          </template>
        </div>
      </template>
    </div>

    <template #footer>
      <span class="text-subtle">
        Advisory only · requires dentist review · is_clinical=false · no canonical record mutation.
      </span>
    </template>
  </SummaryCard>
</template>
