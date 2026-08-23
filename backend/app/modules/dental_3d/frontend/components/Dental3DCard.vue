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
import { computed, ref } from 'vue'
import { PERMISSIONS } from '~~/app/config/permissions'
import { useDental3DMeshIO, useDental3DScene, toViewerTeeth, summarizeScene } from '../composables/useDental3DScene'
import { toSceneMeshes } from '../lib/sceneMeshes'
import type { DentalToothView } from '../lib/dentalArch'

interface Ctx {
  patient: { id: string }
}

const props = defineProps<{ ctx: Ctx }>()

const { t } = useI18n()
const { can } = usePermissions()
const { uploadMesh } = useDental3DMeshIO()

const { data, status, refresh } = useDental3DScene(() => props.ctx.patient.id)

const scene = computed(() => data.value)
const failed = computed(() => status.value !== 'pending' && scene.value === null)
const viewerTeeth = computed<DentalToothView[]>(() => toViewerTeeth(scene.value))
const summary = computed(() => summarizeScene(scene.value))
const sceneMeshes = computed(() => toSceneMeshes(scene.value))
const hasRealMesh = computed(() => sceneMeshes.value.length > 0)

const canUpload = computed(() => can(PERMISSIONS.dental3d.write))
const uploading = ref(false)
const uploadFailed = ref(false)
const fileInputRef = ref<HTMLInputElement | null>(null)

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
          :height="230"
        />
        <template #fallback>
          <div
            data-testid="dental3d-loading"
            class="skeleton h-[230px] w-full rounded-md"
          />
        </template>
      </ClientOnly>

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
