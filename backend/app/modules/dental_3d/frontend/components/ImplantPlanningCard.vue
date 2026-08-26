<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { PERMISSIONS } from '~~/app/config/permissions'
import {
  useDental3DAlignment,
  useDental3DNerveDetection,
  useDental3DScene
} from '../composables/useDental3DScene'
import {
  useDental3DImplantPlanning,
  type ImplantCandidatePayload,
  type PlanningCheckPayload
} from '../composables/useDental3DImplantPlanning'
import { buildClinicalScene } from '../lib/clinicalScene'
import { withImplantPlanning } from '../lib/implantScene'

interface Ctx {
  patient: { id: string }
}

const props = defineProps<{ ctx: Ctx }>()
const { can } = usePermissions()

const { data: scene } = useDental3DScene(() => props.ctx.patient.id)
const {
  alignment,
  load: loadAlignment
} = useDental3DAlignment(() => props.ctx.patient.id)
const {
  analysis: nerve,
  load: loadNerve
} = useDental3DNerveDetection(() => props.ctx.patient.id)
const planning = useDental3DImplantPlanning(() => props.ctx.patient.id)

const canWrite = computed(() => can(PERMISSIONS.dental3d.write))
const frameUid = computed(() =>
  alignment.value?.status === 'accepted'
  && alignment.value.target_frame?.kind === 'dicom_patient'
  && alignment.value.target_frame.unit === 'mm'
    ? alignment.value.target_frame.frame_of_reference_uid ?? null
    : null
)
const alignmentId = computed(() =>
  alignment.value?.status === 'accepted' ? alignment.value.id ?? null : null
)

const targetForm = reactive({
  x: 0,
  y: 0,
  z: 0,
  axisX: 0,
  axisY: 0,
  axisZ: 1
})

const planForm = reactive({
  x: 0,
  y: 0,
  z: 5,
  axisX: 0,
  axisY: 0,
  axisZ: 1,
  diameterMm: 4,
  lengthMm: 10
})
const editingPlanId = ref<string | null>(null)

const clinicalScene = computed(() => withImplantPlanning(
  buildClinicalScene(scene.value ?? null, alignment.value, nerve.value),
  planning.snapshot.value
))

const latestTarget = computed(() => planning.snapshot.value?.latest_target ?? null)
const plans = computed(() => planning.snapshot.value?.plans ?? [])

onMounted(() => {
  void Promise.all([
    loadAlignment(),
    loadNerve(),
    planning.load()
  ])
})

async function createTarget(): Promise<void> {
  if (!alignmentId.value || !frameUid.value) return
  await planning.createDentistTarget({
    alignment_id: alignmentId.value,
    platform_center: { x: targetForm.x, y: targetForm.y, z: targetForm.z },
    axis: { x: targetForm.axisX, y: targetForm.axisY, z: targetForm.axisZ },
    frame_of_reference_uid: frameUid.value,
    source_identifier: `dentist-defined:${props.ctx.patient.id}`
  })
}

function candidateFromForm(): ImplantCandidatePayload | null {
  if (!frameUid.value) return null
  return {
    center: { x: planForm.x, y: planForm.y, z: planForm.z },
    axis: { x: planForm.axisX, y: planForm.axisY, z: planForm.axisZ },
    diameter_mm: planForm.diameterMm,
    length_mm: planForm.lengthMm,
    frame_of_reference_uid: frameUid.value,
    unit: 'mm',
    dimension_source: 'dentist-explicit-dimensions'
  }
}

async function savePlan(): Promise<void> {
  const candidate = candidateFromForm()
  if (!candidate) return
  if (editingPlanId.value) {
    if (await planning.editPlan(editingPlanId.value, candidate)) editingPlanId.value = null
  } else {
    await planning.createManualPlan(candidate)
  }
}

function editPlan(planId: string): void {
  const plan = plans.value.find(item => item.id === planId)
  if (!plan) return
  const candidate = plan.current_revision.candidate
  planForm.x = candidate.center.x
  planForm.y = candidate.center.y
  planForm.z = candidate.center.z
  planForm.axisX = candidate.axis.x
  planForm.axisY = candidate.axis.y
  planForm.axisZ = candidate.axis.z
  planForm.diameterMm = candidate.diameter_mm
  planForm.lengthMm = candidate.length_mm
  editingPlanId.value = planId
}

function displayCheck(check: PlanningCheckPayload): string {
  if (check.status === 'UNAVAILABLE' || check.value === null) return 'UNAVAILABLE'
  return `${check.value.toFixed(2)}${check.unit ? ` ${check.unit}` : ''}`
}
</script>

<template>
  <SummaryCard
    title="Implant planning"
    icon="i-lucide-circle-dot-dashed"
    :loading="planning.loading.value"
  >
    <div
      data-testid="dental3d-implant-planning"
      class="space-y-3"
    >
      <p class="text-caption text-muted">
        Engineering decision support in DICOM patient millimetres. No automatic clinical
        approval or hidden safety threshold. Dentist review is required.
      </p>

      <Dental3DViewer
        :clinical-scene="clinicalScene"
        :height="360"
      />

      <div
        v-if="!alignmentId || !frameUid"
        data-testid="implant-planning-alignment-required"
        class="rounded-md border border-default bg-elevated p-3 text-caption text-warning"
      >
        An accepted patient-specific IOS→CBCT alignment is required before implant planning.
      </div>

      <template v-else>
        <section class="space-y-2 rounded-md border border-default p-3">
          <div class="flex items-center justify-between gap-2">
            <div>
              <div class="text-sm font-medium text-default">
                Prosthetic target
              </div>
              <div class="text-caption text-muted">
                Explicit platform centre + normalized platform-to-apex axis.
              </div>
            </div>
            <span
              data-testid="implant-prosthetic-status"
              class="text-caption font-medium"
            >
              {{ latestTarget?.review_status ?? 'not defined' }}
            </span>
          </div>

          <div
            v-if="canWrite && (!latestTarget || latestTarget.review_status === 'rejected')"
            class="grid grid-cols-2 gap-2 md:grid-cols-6"
          >
            <input v-model.number="targetForm.x" aria-label="Prosthetic target X mm" type="number" step="0.1" class="rounded border border-default bg-default px-2 py-1" placeholder="X mm">
            <input v-model.number="targetForm.y" aria-label="Prosthetic target Y mm" type="number" step="0.1" class="rounded border border-default bg-default px-2 py-1" placeholder="Y mm">
            <input v-model.number="targetForm.z" aria-label="Prosthetic target Z mm" type="number" step="0.1" class="rounded border border-default bg-default px-2 py-1" placeholder="Z mm">
            <input v-model.number="targetForm.axisX" aria-label="Prosthetic axis X" type="number" step="0.01" class="rounded border border-default bg-default px-2 py-1" placeholder="Axis X">
            <input v-model.number="targetForm.axisY" aria-label="Prosthetic axis Y" type="number" step="0.01" class="rounded border border-default bg-default px-2 py-1" placeholder="Axis Y">
            <input v-model.number="targetForm.axisZ" aria-label="Prosthetic axis Z" type="number" step="0.01" class="rounded border border-default bg-default px-2 py-1" placeholder="Axis Z">
            <button
              data-testid="implant-create-prosthetic-target"
              type="button"
              class="col-span-2 rounded border border-default px-3 py-1 text-caption text-muted md:col-span-6"
              :disabled="planning.mutating.value"
              @click="createTarget"
            >
              Save explicit prosthetic target
            </button>
          </div>

          <div
            v-if="latestTarget?.review_status === 'pending_review' && canWrite"
            class="flex gap-2"
          >
            <button data-testid="implant-accept-prosthetic-target" type="button" class="rounded border border-default px-2 py-1 text-caption text-muted" :disabled="planning.mutating.value" @click="planning.reviewTarget('accepted')">
              Accept target
            </button>
            <button data-testid="implant-reject-prosthetic-target" type="button" class="rounded border border-default px-2 py-1 text-caption text-muted" :disabled="planning.mutating.value" @click="planning.reviewTarget('rejected')">
              Reject target
            </button>
          </div>
        </section>

        <section
          v-if="canWrite"
          class="space-y-2 rounded-md border border-default p-3"
        >
          <div class="text-sm font-medium text-default">
            {{ editingPlanId ? 'Edit implant draft — creates a new revision' : 'New manual implant draft' }}
          </div>
          <div class="text-caption text-muted">
            Enter patient-space centre, a normalized axis, and explicit dimensions.
          </div>
          <div class="grid grid-cols-2 gap-2 md:grid-cols-4">
            <input v-model.number="planForm.x" aria-label="Implant center X mm" type="number" step="0.1" class="rounded border border-default bg-default px-2 py-1" placeholder="Center X">
            <input v-model.number="planForm.y" aria-label="Implant center Y mm" type="number" step="0.1" class="rounded border border-default bg-default px-2 py-1" placeholder="Center Y">
            <input v-model.number="planForm.z" aria-label="Implant center Z mm" type="number" step="0.1" class="rounded border border-default bg-default px-2 py-1" placeholder="Center Z">
            <input v-model.number="planForm.diameterMm" aria-label="Implant diameter mm" type="number" min="0.1" step="0.1" class="rounded border border-default bg-default px-2 py-1" placeholder="Diameter">
            <input v-model.number="planForm.axisX" aria-label="Implant axis X" type="number" step="0.01" class="rounded border border-default bg-default px-2 py-1" placeholder="Axis X">
            <input v-model.number="planForm.axisY" aria-label="Implant axis Y" type="number" step="0.01" class="rounded border border-default bg-default px-2 py-1" placeholder="Axis Y">
            <input v-model.number="planForm.axisZ" aria-label="Implant axis Z" type="number" step="0.01" class="rounded border border-default bg-default px-2 py-1" placeholder="Axis Z">
            <input v-model.number="planForm.lengthMm" aria-label="Implant length mm" type="number" min="0.1" step="0.1" class="rounded border border-default bg-default px-2 py-1" placeholder="Length">
          </div>
          <div class="flex gap-2">
            <button data-testid="implant-save-plan" type="button" class="rounded border border-default px-3 py-1 text-caption text-muted" :disabled="planning.mutating.value" @click="savePlan">
              {{ editingPlanId ? 'Save new revision' : 'Create draft' }}
            </button>
            <button v-if="editingPlanId" type="button" class="rounded border border-default px-3 py-1 text-caption text-muted" @click="editingPlanId = null">
              Cancel edit
            </button>
          </div>
        </section>

        <section class="space-y-2">
          <article
            v-for="plan in plans"
            :key="plan.id"
            :data-testid="`implant-plan-${plan.id}`"
            class="rounded-md border border-default p-3 text-caption"
          >
            <div class="flex flex-wrap items-center justify-between gap-2">
              <div class="font-medium text-default">
                Plan {{ plan.id.slice(0, 8) }} · revision {{ plan.current_revision.revision_number }}
              </div>
              <span class="font-medium">{{ plan.status }}</span>
            </div>
            <div class="mt-2 grid gap-1 md:grid-cols-2">
              <div>Diameter / length: {{ plan.current_revision.candidate.diameter_mm.toFixed(1) }} / {{ plan.current_revision.candidate.length_mm.toFixed(1) }} mm</div>
              <div>Prosthetic offset: {{ displayCheck(plan.current_revision.assessment.prosthetic_offset_mm) }}</div>
              <div>Prosthetic axis angle: {{ displayCheck(plan.current_revision.assessment.prosthetic_axis_angle_deg) }}</div>
              <div>Nerve centerline distance: {{ displayCheck(plan.current_revision.assessment.nerve_surface_to_centerline_mm) }}</div>
              <div>Bone envelope: {{ displayCheck(plan.current_revision.assessment.bone_axis_span_mm) }}</div>
              <div>Clinical threshold: {{ plan.current_revision.assessment.clinical_threshold_status }}</div>
            </div>
            <div
              v-if="canWrite && (plan.status === 'draft' || plan.status === 'proposed')"
              class="mt-2 flex flex-wrap gap-2"
            >
              <button type="button" class="rounded border border-default px-2 py-1 text-muted" @click="editPlan(plan.id)">
                Edit → new revision
              </button>
              <button data-testid="implant-accept-plan" type="button" class="rounded border border-default px-2 py-1 text-muted" :disabled="planning.mutating.value" @click="planning.reviewPlan(plan.id, 'accepted')">
                Accept plan
              </button>
              <button data-testid="implant-reject-plan" type="button" class="rounded border border-default px-2 py-1 text-muted" :disabled="planning.mutating.value" @click="planning.reviewPlan(plan.id, 'rejected')">
                Reject plan
              </button>
            </div>
          </article>
          <p v-if="plans.length === 0" class="text-caption text-muted">
            No implant plan revisions yet.
          </p>
        </section>
      </template>

      <p
        v-if="planning.error.value"
        data-testid="implant-planning-error"
        class="text-caption text-warning"
      >
        {{ planning.error.value }}
      </p>
    </div>
  </SummaryCard>
</template>
