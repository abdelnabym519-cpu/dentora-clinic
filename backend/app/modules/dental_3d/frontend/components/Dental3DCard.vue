<script setup lang="ts">
/**
 * Dental3DCard — smart-card for the patient Resumen grid.
 *
 * Registered into ``patient.summary.cards`` by the dental_3d module
 * (see ``plugins/slots.client.ts``). Renders the patient's 3D preview:
 * real scan geometry when the backend provides mesh references
 * (Phase 2), the synthetic non-clinical arch otherwise (Phase 1
 * fallback). Holders of ``dental_3d.write`` can upload STL/OBJ scans
 * straight from the card; storage goes through the backend into the
 * existing media module. The disclaimer line stays visible by design —
 * visualization, not a diagnostic tool.
 */
import { computed, onMounted, ref } from 'vue'
import { PERMISSIONS } from '~~/app/config/permissions'
import { useDental3DMeshIO, useDental3DScene, useDental3DSegmentation, useDental3DNerveDetection, toViewerTeeth, summarizeScene } from '../composables/useDental3DScene'
import { toSceneMeshes } from '../lib/sceneMeshes'
import { toSegmentationView, uncertainTeeth } from '../lib/segmentationView'
import { toNerveView, nearTeeth, watchTeeth } from '../lib/nerveView'
import type { DentalToothView } from '../lib/dentalArch'

interface Ctx {
  patient: { id: string }
}

const props = defineProps<{ ctx: Ctx }>()

const { t } = useI18n()
const { can } = usePermissions()
const { uploadMesh } = useDental3DMeshIO()

const { data, status, refresh } = useDental3DScene(() => props.ctx.patient.id)
const {
  analysis: rawAnalysis,
  running: segmentationRunning,
  runFailed: segmentationRunFailed,
  reviewing,
  load: loadSegmentation,
  run: runSegmentation,
  review: reviewSegmentation
} = useDental3DSegmentation(() => props.ctx.patient.id)

const scene = computed(() => data.value ?? null)
const failed = computed(() => status.value !== 'pending' && scene.value === null)
const viewerTeeth = computed<DentalToothView[]>(() => toViewerTeeth(scene.value))
const summary = computed(() => summarizeScene(scene.value))
const sceneMeshes = computed(() => toSceneMeshes(scene.value))
const hasRealMesh = computed(() => sceneMeshes.value.length > 0)

/** Normalized segmentation analysis (Phase 3) — null when not run. */
const segmentation = computed(() => toSegmentationView(rawAnalysis.value))
const uncertainList = computed(() => uncertainTeeth(segmentation.value))
const uncertainLabel = computed(() =>
  uncertainList.value.map(tooth => tooth.toothNumber).join(', ')
)

const canUpload = computed(() => can(PERMISSIONS.dental3d.write))
const canReviewSegmentation = computed(() => can(PERMISSIONS.dental3d.write))
const uploading = ref(false)
const uploadFailed = ref(false)
const fileInputRef = ref<HTMLInputElement | null>(null)

const {
  analysis: rawNerveAnalysis,
  running: nerveRunning,
  runFailed: nerveRunFailed,
  reviewing: nerveReviewing,
  load: loadNerve,
  run: runNerve,
  review: reviewNerve
} = useDental3DNerveDetection(() => props.ctx.patient.id)

/** Normalized nerve analysis (Phase 4) — null when not run. */
const nerve = computed(() => toNerveView(rawNerveAnalysis.value))
const primaryNervePathway = computed(() => nerve.value?.pathways[0] ?? null)
const nerveNearList = computed(() => nearTeeth(nerve.value))
const nerveWatchList = computed(() => watchTeeth(nerve.value))
const nerveNearLabel = computed(() =>
  nerveNearList.value.map(p => p.toothNumber).join(', ')
)
const nerveWatchLabel = computed(() =>
  nerveWatchList.value.map(p => p.toothNumber).join(', ')
)
const canRunNerve = computed(() => can(PERMISSIONS.dental3d.write))
/** Overlay toggle — defaults on once an analysis exists. */
const showNerve = ref(true)

onMounted(() => {
  void loadSegmentation()
  void loadNerve()
})

async function onRunSegmentation(): Promise<void> {
  await runSegmentation()
}

async function onReviewSegmentation(decision: 'accepted' | 'rejected'): Promise<void> {
  await reviewSegmentation(decision)
}

async function onRunNerve(): Promise<void> {
  showNerve.value = true
  await runNerve()
}

async function onReviewNerve(decision: 'accepted' | 'rejected'): Promise<void> {
  await reviewNerve(decision)
}

async function onUploadChange(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  uploading.value = true
  uploadFailed.value = false
  const mesh = await uploadMesh(props.ctx.patient.id, file)
  uploading.value = false
  if (mesh) await refresh()
  else uploadFailed.value = true
  input.value = ''
}
</script>

<template>
  <SummaryCard
    :title="t('dental_3d.card.title')"
    icon="i-lucide-rotate-3d"
    :loading="status === 'pending'"
  >
    <div
      data-testid="dental3d-card"
      class="space-y-2"
    >
      <p class="text-caption text-muted">
        {{ t('dental_3d.card.subtitle', { count: summary.rendered }) }}
        <span
          v-if="summary.flagged > 0"
          class="tnum"
        >
          · {{ t('dental_3d.card.flagged', { count: summary.flagged }) }}
        </span>
        <span
          v-if="hasRealMesh"
          data-testid="dental3d-mesh-count"
          class="tnum"
        >
          · {{ t('dental_3d.card.meshCount', { count: sceneMeshes.length }) }}
        </span>
      </p>

      <div
        v-if="failed"
        data-testid="dental3d-error"
        class="text-caption text-muted"
      >
        {{ t('dental_3d.card.error') }}
      </div>
      <ClientOnly v-else>
        <Dental3DViewer
          :teeth="viewerTeeth"
          :meshes="sceneMeshes"
          :segmentation="segmentation"
          :nerve="nerve"
          :show-nerve="showNerve"
          :height="230"
        />
        <template #fallback>
          <div
            data-testid="dental3d-loading"
            class="skeleton h-[230px] w-full rounded-md"
          />
        </template>
      </ClientOnly>

      <!-- Phase 3: automatic tooth segmentation — non-clinical decision
           support with dentist review (ADR 0021). -->
      <div
        data-testid="dental3d-segmentation"
        class="space-y-1 border-t border-default pt-2"
      >
        <div class="flex items-center justify-between gap-2">
          <span
            data-testid="dental3d-segmentation-status"
            class="text-caption font-medium text-default"
          >
            {{ t('dental_3d.segmentation.title') }}:
            <span v-if="segmentation === null">
              {{ segmentationRunning ? t('dental_3d.segmentation.running') : t('dental_3d.segmentation.none') }}
            </span>
            <span v-else-if="segmentation.review.status === 'pending'">
              {{ t('dental_3d.segmentation.reviewPending') }}
            </span>
            <span v-else-if="segmentation.review.status === 'accepted'">
              {{ t('dental_3d.segmentation.reviewAccepted') }}
            </span>
            <span v-else>{{ t('dental_3d.segmentation.reviewRejected') }}</span>
          </span>
          <button
            v-if="canReviewSegmentation"
            data-testid="dental3d-segmentation-run"
            type="button"
            class="rounded border border-default px-2 py-0.5 text-caption text-muted hover:bg-elevated disabled:opacity-60"
            :disabled="segmentationRunning"
            @click="onRunSegmentation"
          >
            {{ segmentationRunning ? t('dental_3d.segmentation.running') : t('dental_3d.segmentation.run') }}
          </button>
        </div>

        <template v-if="segmentation !== null">
          <div
            data-testid="dental3d-segmentation-counts"
            class="flex flex-wrap gap-x-2 text-caption text-muted"
          >
            <span>{{ t('dental_3d.segmentation.segmented', { count: segmentation.counts.segmented }) }}</span>
            <span>· {{ t('dental_3d.segmentation.uncertain', { count: segmentation.counts.uncertain }) }}</span>
            <span>· {{ t('dental_3d.segmentation.missing', { count: segmentation.counts.missing }) }}</span>
          </div>
          <p class="text-subtle text-caption">
            {{ t('dental_3d.segmentation.method', { method: segmentation.method }) }}
            — {{ t('dental_3d.segmentation.nonClinical') }}
          </p>
          <p
            v-if="uncertainList.length > 0"
            data-testid="dental3d-segmentation-uncertain"
            class="text-caption text-warning"
          >
            {{ t('dental_3d.segmentation.uncertainTeeth', { teeth: uncertainLabel }) }}
          </p>
          <div
            v-if="segmentation.review.status === 'pending' && canReviewSegmentation"
            class="flex gap-2"
          >
            <button
              data-testid="dental3d-segmentation-accept"
              type="button"
              class="rounded border border-default px-2 py-0.5 text-caption text-muted hover:bg-elevated disabled:opacity-60"
              :disabled="reviewing"
              @click="onReviewSegmentation('accepted')"
            >
              {{ t('dental_3d.segmentation.accept') }}
            </button>
            <button
              data-testid="dental3d-segmentation-reject"
              type="button"
              class="rounded border border-default px-2 py-0.5 text-caption text-muted hover:bg-elevated disabled:opacity-60"
              :disabled="reviewing"
              @click="onReviewSegmentation('rejected')"
            >
              {{ t('dental_3d.segmentation.reject') }}
            </button>
          </div>
          <p
            v-if="segmentation.review.status !== 'pending'"
            data-testid="dental3d-segmentation-review-state"
            class="text-subtle text-caption"
          >
            {{ segmentation.review.status === 'accepted'
              ? t('dental_3d.segmentation.reviewAccepted')
              : t('dental_3d.segmentation.reviewRejected') }}
            <template v-if="segmentation.review.note">
              — {{ segmentation.review.note }}
            </template>
          </p>
        </template>
        <p
          v-if="segmentationRunFailed"
          data-testid="dental3d-segmentation-error"
          class="text-caption text-warning"
        >
          {{ t('dental_3d.segmentation.runError') }}
        </p>
      </div>

      <!-- Phase 4: mandibular nerve detection — AI-assisted / simulated
           decision support with dentist verification (ADR 0022). -->
      <div
        data-testid="dental3d-nerve"
        class="space-y-1 border-t border-default pt-2"
      >
        <div class="flex items-center justify-between gap-2">
          <span
            data-testid="dental3d-nerve-status"
            class="text-caption font-medium text-default"
          >
            {{ t('dental_3d.nerve.title') }}:
            <span v-if="nerve === null">
              {{ nerveRunning ? t('dental_3d.nerve.running') : t('dental_3d.nerve.none') }}
            </span>
            <span v-else-if="nerve.review.status === 'pending'">
              {{ t('dental_3d.nerve.reviewPending') }}
            </span>
            <span v-else-if="nerve.review.status === 'accepted'">
              {{ t('dental_3d.nerve.reviewAccepted') }}
            </span>
            <span v-else>{{ t('dental_3d.nerve.reviewRejected') }}</span>
          </span>
          <div class="flex items-center gap-2">
            <label
              v-if="nerve !== null"
              class="inline-flex cursor-pointer items-center gap-1 text-caption text-muted"
            >
              <input
                v-model="showNerve"
                data-testid="dental3d-nerve-toggle"
                type="checkbox"
                class="accent-current"
              >
              {{ t('dental_3d.nerve.showPathway') }}
            </label>
            <button
              v-if="canRunNerve"
              data-testid="dental3d-nerve-run"
              type="button"
              class="rounded border border-default px-2 py-0.5 text-caption text-muted hover:bg-elevated disabled:opacity-60"
              :disabled="nerveRunning"
              @click="onRunNerve"
            >
              {{ nerveRunning ? t('dental_3d.nerve.running') : t('dental_3d.nerve.run') }}
            </button>
          </div>
        </div>

        <template v-if="nerve !== null">
          <div
            data-testid="dental3d-nerve-counts"
            class="flex flex-wrap gap-x-2 text-caption text-muted"
          >
            <span>{{ t('dental_3d.nerve.pathways', { count: nerve.counts.pathways }) }}</span>
            <span>· {{ t('dental_3d.nerve.near', { count: nerve.counts.near }) }}</span>
            <span>· {{ t('dental_3d.nerve.watch', { count: nerve.counts.watch }) }}</span>
          </div>
          <p class="text-subtle text-caption">
            {{ t('dental_3d.nerve.method', { method: nerve.method }) }}
            — {{ nerve.disclaimer }}
          </p>
          <p
            v-if="nerve.status === 'failed' && nerve.failure"
            data-testid="dental3d-nerve-model-failure"
            class="text-caption text-warning"
          >
            {{ nerve.failure.message }}
          </p>
          <p
            v-if="primaryNervePathway"
            class="text-subtle text-caption"
          >
            {{ t('dental_3d.nerve.confidence', {
              value: Math.round(primaryNervePathway.confidence * 100) / 100
            }) }}
            · {{ primaryNervePathway.status === 'uncertain'
              ? t('dental_3d.nerve.uncertainModel') : t('dental_3d.nerve.detectedModel') }}
          </p>
          <p
            v-if="nerveNearList.length > 0"
            data-testid="dental3d-nerve-near"
            class="text-caption text-warning"
          >
            {{ t('dental_3d.nerve.nearTeeth', { teeth: nerveNearLabel }) }}
            — {{ t('dental_3d.nerve.estimated') }}
          </p>
          <p
            v-if="nerveWatchList.length > 0"
            data-testid="dental3d-nerve-watch"
            class="text-caption text-muted"
          >
            {{ t('dental_3d.nerve.watchTeeth', { teeth: nerveWatchLabel }) }}
            — {{ t('dental_3d.nerve.estimated') }}
          </p>
          <div
            v-if="nerve.review.status === 'pending' && canRunNerve"
            class="flex gap-2"
          >
            <button
              data-testid="dental3d-nerve-accept"
              type="button"
              class="rounded border border-default px-2 py-0.5 text-caption text-muted hover:bg-elevated disabled:opacity-60"
              :disabled="nerveReviewing"
              @click="onReviewNerve('accepted')"
            >
              {{ t('dental_3d.nerve.accept') }}
            </button>
            <button
              data-testid="dental3d-nerve-reject"
              type="button"
              class="rounded border border-default px-2 py-0.5 text-caption text-muted hover:bg-elevated disabled:opacity-60"
              :disabled="nerveReviewing"
              @click="onReviewNerve('rejected')"
            >
              {{ t('dental_3d.nerve.reject') }}
            </button>
          </div>
          <p
            v-if="nerve.review.status === 'accepted' || nerve.review.status === 'rejected'"
            data-testid="dental3d-nerve-review-state"
            class="text-subtle text-caption"
          >
            {{ nerve.review.status === 'accepted'
              ? t('dental_3d.nerve.reviewAccepted')
              : t('dental_3d.nerve.reviewRejected') }}
            <template v-if="nerve.review.note">
              — {{ nerve.review.note }}
            </template>
          </p>
        </template>
        <p
          v-if="nerveRunFailed"
          data-testid="dental3d-nerve-error"
          class="text-caption text-warning"
        >
          {{ t('dental_3d.nerve.runError') }}
        </p>
      </div>

      <label
        v-if="canUpload"
        data-testid="dental3d-mesh-upload"
        class="inline-flex cursor-pointer items-center gap-1 rounded-md border border-default px-2 py-1 text-caption text-muted hover:bg-elevated"
        :class="{ 'pointer-events-none opacity-60': uploading }"
      >
        <input
          ref="fileInputRef"
          type="file"
          class="hidden"
          accept=".stl,.obj"
          data-testid="dental3d-mesh-upload-input"
          :disabled="uploading"
          @change="onUploadChange"
        >
        <span
          class="i-lucide-upload"
          aria-hidden="true"
        />
        {{ uploading ? t('dental_3d.card.uploading') : t('dental_3d.card.upload') }}
      </label>
      <div
        v-if="uploadFailed"
        data-testid="dental3d-upload-error"
        class="text-caption text-warning"
      >
        {{ t('dental_3d.card.uploadError') }}
      </div>
    </div>

    <template #footer>
      <span class="text-subtle">
        {{ hasRealMesh ? t('dental_3d.card.scanDisclaimer') : t('dental_3d.card.disclaimer') }}
      </span>
    </template>
  </SummaryCard>
</template>
