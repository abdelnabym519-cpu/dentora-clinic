<script setup lang="ts">
/**
 * Pathology Detection sub-tab (Diagnosis mode).
 *
 * Picks an existing X-ray/photo media document, runs the DENTEX-style
 * detector, and renders the findings overlaid on the image plus a
 * per-tooth table. Engine-absent state is surfaced as guidance, not an
 * error: clinics see exactly what to provision.
 */

import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { usePathologyDetection, type MediaDocument } from '../composables/usePathologyDetection'
import type { Diagnosis, PathologyFinding } from '../types'

const props = defineProps<{
  patientId: string
  readonly?: boolean
}>()

const { t } = useI18n()
const toast = useToast()
const config = useRuntimeConfig()
const auth = useAuth()
const {
  capabilities,
  documents,
  analyses,
  current,
  isLoading,
  isRunning,
  error,
  fetchCapabilities,
  fetchDocuments,
  fetchAnalyses,
  fetchAnalysis,
  runAnalysis,
  removeAnalysis
} = usePathologyDetection(() => props.patientId)

const selectedDocumentId = ref<string | undefined>(undefined)
const imageUrl = ref<string | null>(null)

const selectedDocument = computed<MediaDocument | null>(
  () => documents.value.find(d => d.id === selectedDocumentId.value) ?? null
)

const diagnosisTone: Record<Diagnosis, string> = {
  caries: 'bg-amber-500',
  deep_caries: 'bg-red-500',
  periapical_lesion: 'bg-purple-500',
  impacted_tooth: 'bg-blue-500'
}

const diagnosisBadge: Record<Diagnosis, string> = {
  caries: 'bg-amber-100 text-amber-800',
  deep_caries: 'bg-red-100 text-red-800',
  periapical_lesion: 'bg-purple-100 text-purple-800',
  impacted_tooth: 'bg-blue-100 text-blue-800'
}

const findings = computed<PathologyFinding[]>(() => current.value?.findings ?? [])

const boxStyle = (finding: PathologyFinding) => {
  const { x1, y1, x2, y2 } = finding.bbox
  return {
    left: `${x1 * 100}%`,
    top: `${y1 * 100}%`,
    width: `${(x2 - x1) * 100}%`,
    height: `${(y2 - y1) * 100}%`
  }
}

const fdiLabel = (finding: PathologyFinding) => {
  if (finding.tooth_number) return `${finding.tooth_number}`
  if (finding.quadrant && finding.position) return `${finding.quadrant}.${finding.position}?`
  return '—'
}

async function loadImage(document: MediaDocument | null) {
  if (imageUrl.value) {
    URL.revokeObjectURL(imageUrl.value)
    imageUrl.value = null
  }
  if (!document?.medium_url && !document?.full_url) return
  try {
    const path = document.medium_url ?? document.full_url!
    const blob = await $fetch<Blob>(path, {
      baseURL: config.public.apiBaseUrl,
      headers: { Authorization: `Bearer ${auth.accessToken.value}` },
      responseType: 'blob'
    })
    imageUrl.value = URL.createObjectURL(blob)
  } catch {
    imageUrl.value = null
  }
}

async function refreshAll() {
  await fetchCapabilities()
  await Promise.all([fetchDocuments(), fetchAnalyses()])
  const latest = analyses.value[0]
  if (latest) {
    await fetchAnalysis(latest.id)
    const doc = documents.value.find(d => d.id === current.value?.document_id)
    if (doc) selectedDocumentId.value = doc.id
  }
}

function onDocumentChange() {
  void loadImage(selectedDocument.value)
}

async function handleRun() {
  if (!selectedDocument.value) return
  try {
    await runAnalysis(selectedDocument.value.id)
    toast.add({ title: t('pathology_detection.run.done'), color: 'success' })
    void loadImage(selectedDocument.value)
  } catch {
    toast.add({ title: t('pathology_detection.run.failed'), color: 'error' })
  }
}

async function handleSelectAnalysis(id: string) {
  await fetchAnalysis(id)
  const doc = documents.value.find(d => d.id === current.value?.document_id)
  if (doc) {
    selectedDocumentId.value = doc.id
    void loadImage(doc)
  }
}

async function handleDelete(id: string) {
  await removeAnalysis(id)
  const latest = analyses.value[0]
  if (latest) {
    await fetchAnalysis(latest.id)
  }
}

onMounted(refreshAll)
watch(() => props.patientId, refreshAll)
watch(selectedDocumentId, onDocumentChange)
onBeforeUnmount(() => {
  if (imageUrl.value) URL.revokeObjectURL(imageUrl.value)
})
</script>

<template>
  <div class="space-y-4">
    <!-- Engine not provisioned: guidance, not a crash -->
    <div
      v-if="capabilities && !capabilities.available"
      class="flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 p-4"
    >
      <UIcon
        name="i-lucide-cpu"
        class="mt-0.5 text-amber-600"
      />
      <div>
        <p class="text-sm font-medium text-amber-900">
          {{ t('pathology_detection.engine.title') }}
        </p>
        <p class="mt-1 text-xs text-amber-800">
          {{ capabilities.reason || t('pathology_detection.engine.reason') }}
        </p>
      </div>
    </div>

    <div
      v-if="isLoading"
      class="flex items-center justify-center py-10 text-sm text-gray-500"
    >
      <UIcon
        name="i-lucide-loader-2"
        class="mr-2 animate-spin"
      />
      {{ t('pathology_detection.loading') }}
    </div>

    <template v-else>
      <!-- Controls -->
      <div class="flex flex-wrap items-end gap-3">
        <div class="min-w-64 flex-1">
          <label class="mb-1 block text-sm font-medium text-gray-700">
            {{ t('pathology_detection.image.label') }}
          </label>
          <USelect
            v-model="selectedDocumentId"
            :disabled="capabilities?.available === false || readonly"
            :placeholder="t('pathology_detection.image.placeholder')"
            :items="documents.map(d => ({ value: d.id, label: `${d.title} (${d.media_kind})` }))"
            class="w-full"
          />
        </div>
        <UButton
          color="primary"
          icon="i-lucide-scan-search"
          :loading="isRunning"
          :disabled="!selectedDocument || capabilities?.available !== true || readonly"
          @click="handleRun"
        >
          {{ t('pathology_detection.run.cta') }}
        </UButton>
      </div>

      <p
        v-if="error"
        class="text-sm text-red-600"
      >
        {{ error }}
      </p>

      <!-- Result detail -->
      <div
        v-if="current"
        class="grid gap-4 lg:grid-cols-2"
      >
        <div class="relative overflow-hidden rounded-lg border border-gray-200 bg-gray-950">
          <img
            v-if="imageUrl"
            :src="imageUrl"
            :alt="selectedDocument?.title || ''"
            class="mx-auto block max-h-[28rem] w-auto"
          >
          <template
            v-for="finding in findings"
            :key="finding.id"
          >
            <div
              class="absolute rounded-sm border-2 border-white/80"
              :class="diagnosisTone[finding.diagnosis]"
              :style="boxStyle(finding)"
              :title="`${finding.diagnosis} ${Math.round(finding.confidence * 100)}%`"
            >
              <span class="absolute -top-5 left-0 whitespace-nowrap rounded bg-black/70 px-1 text-[10px] text-white">
                {{ fdiLabel(finding) }} · {{ Math.round(finding.confidence * 100) }}%
              </span>
            </div>
          </template>
          <div
            v-if="!imageUrl"
            class="flex h-64 items-center justify-center text-sm text-gray-400"
          >
            {{ t('pathology_detection.image.none') }}
          </div>
        </div>

        <div class="space-y-3">
          <div class="flex items-center justify-between">
            <span class="text-sm font-medium">
              {{ t('pathology_detection.result.title') }}
            </span>
            <span
              v-if="current.status === 'failed'"
              class="rounded bg-red-100 px-2 py-0.5 text-xs text-red-800"
            >
              {{ t('pathology_detection.result.failed') }}
            </span>
            <span
              v-else
              class="text-xs text-gray-500"
            >
              {{ current.engine }} · {{ current.model_version }} · {{ current.inference_ms }}ms
            </span>
          </div>

          <div
            v-if="current.status === 'failed'"
            class="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800"
          >
            {{ current.error }}
          </div>

          <table
            v-if="findings.length > 0"
            class="w-full text-sm"
          >
            <thead>
              <tr class="border-b border-gray-200 text-left text-xs uppercase text-gray-500">
                <th class="py-2 pr-3 font-medium">
                  {{ t('pathology_detection.result.tooth') }}
                </th>
                <th class="py-2 pr-3 font-medium">
                  {{ t('pathology_detection.result.diagnosis') }}
                </th>
                <th class="py-2 font-medium">
                  {{ t('pathology_detection.result.confidence') }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="finding in findings"
                :key="finding.id"
                class="border-b border-gray-100"
              >
                <td class="py-2 pr-3 font-mono">
                  {{ fdiLabel(finding) }}
                </td>
                <td class="py-2 pr-3">
                  <span
                    class="rounded px-2 py-0.5 text-xs"
                    :class="diagnosisBadge[finding.diagnosis]"
                  >
                    {{ t(`pathology_detection.diagnosis.${finding.diagnosis}`) }}
                  </span>
                </td>
                <td class="py-2">
                  {{ Math.round(finding.confidence * 100) }}%
                </td>
              </tr>
            </tbody>
          </table>

          <div
            v-else-if="current.status === 'completed'"
            class="rounded-md border border-dashed border-gray-300 py-6 text-center text-sm text-gray-500"
          >
            {{ t('pathology_detection.result.none') }}
          </div>

          <p class="text-xs text-gray-400">
            {{ t('pathology_detection.disclaimer') }}
          </p>
        </div>
      </div>

      <!-- History -->
      <div
        v-if="analyses.length > 0"
        class="border-t border-gray-200 pt-3"
      >
        <p class="mb-2 text-sm font-medium">
          {{ t('pathology_detection.history.title') }}
        </p>
        <div class="space-y-1.5">
          <div
            v-for="analysis in analyses"
            :key="analysis.id"
            class="flex items-center justify-between rounded-md border border-gray-200 px-3 py-2 text-sm"
          >
            <button
              class="flex items-center gap-2 text-left"
              @click="handleSelectAnalysis(analysis.id)"
            >
              <span class="font-mono text-xs text-gray-400">
                {{ new Date(analysis.created_at).toLocaleString() }}
              </span>
              <span
                v-if="analysis.status === 'failed'"
                class="rounded bg-red-100 px-2 py-0.5 text-xs text-red-800"
              >
                {{ t('pathology_detection.result.failed') }}
              </span>
              <span
                v-else
                class="rounded bg-green-100 px-2 py-0.5 text-xs text-green-800"
              >
                {{ analysis.findings_count }}
              </span>
            </button>
            <UButton
              v-if="!readonly"
              icon="i-lucide-trash-2"
              variant="ghost"
              size="xs"
              :aria-label="t('pathology_detection.history.delete')"
              @click="handleDelete(analysis.id)"
            />
          </div>
        </div>
      </div>
    </template>
  </div>
</template>
