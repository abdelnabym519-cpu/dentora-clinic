<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { ClinicalCbctSeries, PatientPointMm } from '../lib/clinicalScene'
import { useDental3DMeshIO } from '../composables/useDental3DScene'

const props = defineProps<{
  cbct: ClinicalCbctSeries
  patientPoint: PatientPointMm | null
}>()

const emit = defineEmits<{
  patientPoint: [point: PatientPointMm]
}>()

const axialRef = ref<HTMLDivElement | null>(null)
const sagittalRef = ref<HTMLDivElement | null>(null)
const coronalRef = ref<HTMLDivElement | null>(null)
const loading = ref(true)
const failed = ref(false)
const { fetchDocumentBlob } = useDental3DMeshIO()

let engine: InstanceType<typeof import('@cornerstonejs/core')['RenderingEngine']> | null = null
let coreRuntime: typeof import('@cornerstonejs/core') | null = null
let toolsRuntime: typeof import('@cornerstonejs/tools') | null = null
let dicomRuntime: typeof import('@cornerstonejs/dicom-image-loader') | null = null
let volumeId: string | null = null
let toolGroupId: string | null = null
let abort: AbortController | null = null
const listeners: Array<{ element: HTMLDivElement, listener: EventListener }> = []

async function mapConcurrent<T, R>(items: readonly T[], limit: number, task: (item: T) => Promise<R>): Promise<R[]> {
  const result = new Array<R>(items.length)
  let next = 0
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (next < items.length) {
      const index = next
      next += 1
      result[index] = await task(items[index]!)
    }
  }))
  return result
}

function cleanup(): void {
  abort?.abort()
  for (const { element, listener } of listeners) {
    if (toolsRuntime) element.removeEventListener(toolsRuntime.Enums.Events.MOUSE_CLICK, listener)
  }
  listeners.length = 0
  engine?.destroy()
  engine = null
  if (toolsRuntime && toolGroupId) toolsRuntime.ToolGroupManager.destroyToolGroup(toolGroupId)
  if (coreRuntime && volumeId) {
    try {
      coreRuntime.cache.removeVolumeLoadObject(volumeId)
    } catch {
      // A partially loaded volume may never have reached the cache.
    }
  }
  dicomRuntime?.wadouri.fileManager.purge()
  volumeId = null
  toolGroupId = null
}

async function initialize(): Promise<void> {
  cleanup()
  loading.value = true
  failed.value = false
  abort = new AbortController()
  await nextTick()
  const elements = [axialRef.value, sagittalRef.value, coronalRef.value]
  if (elements.some(element => !element)) return
  try {
    const [core, tools, dicom] = await Promise.all([
      import('@cornerstonejs/core'),
      import('@cornerstonejs/tools'),
      import('@cornerstonejs/dicom-image-loader')
    ])
    coreRuntime = core
    toolsRuntime = tools
    dicomRuntime = dicom
    await core.init()
    tools.init()
    dicom.init({ maxWebWorkers: Math.max(1, Math.min(4, navigator.hardwareConcurrency || 2)) })

    const imageIds = await mapConcurrent(props.cbct.imageUrls, 6, async (url) => {
      const blob = await fetchDocumentBlob(url, abort!.signal)
      return dicom.wadouri.fileManager.add(blob)
    })
    if (imageIds.length === 0) throw new Error('CBCT series contains no instances')

    const engineId = `dentora-cbct-${props.cbct.seriesInstanceUid}`
    engine = new core.RenderingEngine(engineId)
    const viewportIds = ['dentora-axial', 'dentora-sagittal', 'dentora-coronal']
    const orientations = [
      core.Enums.OrientationAxis.AXIAL,
      core.Enums.OrientationAxis.SAGITTAL,
      core.Enums.OrientationAxis.CORONAL
    ]
    engine.setViewports(viewportIds.map((viewportId, index) => ({
      viewportId,
      type: core.Enums.ViewportType.ORTHOGRAPHIC,
      element: elements[index]!,
      defaultOptions: { orientation: orientations[index] }
    })))

    volumeId = `cornerstoneStreamingImageVolume:${props.cbct.seriesInstanceUid}`
    const volume = await core.volumeLoader.createAndCacheVolume(volumeId, { imageIds })
    await volume.load()
    await core.setVolumesForViewports(engine, [{ volumeId }], viewportIds)

    for (const tool of [tools.CrosshairsTool, tools.PanTool, tools.ZoomTool, tools.WindowLevelTool]) {
      try {
        tools.addTool(tool)
      } catch {
        // Tool classes are global and may already be registered by another viewer.
      }
    }
    toolGroupId = `${engineId}-tools`
    const toolGroup = tools.ToolGroupManager.createToolGroup(toolGroupId)
    if (toolGroup) {
      for (const tool of [tools.CrosshairsTool, tools.PanTool, tools.ZoomTool, tools.WindowLevelTool]) {
        toolGroup.addTool(tool.toolName)
      }
      for (const viewportId of viewportIds) toolGroup.addViewport(viewportId, engineId)
      toolGroup.setToolActive(tools.CrosshairsTool.toolName, {
        bindings: [{ mouseButton: tools.Enums.MouseBindings.Primary }]
      })
      toolGroup.setToolActive(tools.PanTool.toolName, {
        bindings: [{ mouseButton: tools.Enums.MouseBindings.Auxiliary }]
      })
      toolGroup.setToolActive(tools.ZoomTool.toolName, {
        bindings: [{ mouseButton: tools.Enums.MouseBindings.Secondary }]
      })
    }

    for (const element of elements as HTMLDivElement[]) {
      const listener: EventListener = (event) => {
        const world = (event as CustomEvent<{ currentPoints?: { world?: [number, number, number] } }>).detail?.currentPoints?.world
        if (world?.every(Number.isFinite)) emit('patientPoint', { x: world[0], y: world[1], z: world[2] })
      }
      element.addEventListener(tools.Enums.Events.MOUSE_CLICK, listener)
      listeners.push({ element, listener })
    }
    engine.renderViewports(viewportIds)
  } catch (error) {
    if ((error as { name?: string }).name !== 'AbortError') {
      console.error('CBCT MPR initialization failed:', error)
      failed.value = true
    }
  } finally {
    loading.value = false
  }
}

watch(() => props.patientPoint, (point) => {
  if (!point || !engine) return
  for (const viewportId of ['dentora-axial', 'dentora-sagittal', 'dentora-coronal']) {
    const viewport = engine.getViewport(viewportId)
    viewport.setCamera({ focalPoint: [point.x, point.y, point.z] })
    viewport.render()
  }
}, { deep: true })

watch(() => props.cbct.seriesInstanceUid, () => void initialize())
onMounted(() => void initialize())
onBeforeUnmount(cleanup)
</script>

<template>
  <section
    data-testid="dental3d-cbct-mpr"
    class="relative grid min-h-56 grid-cols-3 gap-1 overflow-hidden rounded-md border border-default bg-black"
  >
    <div
      ref="axialRef"
      data-testid="dental3d-mpr-axial"
      class="min-h-56"
    />
    <div
      ref="sagittalRef"
      data-testid="dental3d-mpr-sagittal"
      class="min-h-56"
    />
    <div
      ref="coronalRef"
      data-testid="dental3d-mpr-coronal"
      class="min-h-56"
    />
    <div
      v-if="loading"
      class="absolute inset-0 grid place-items-center bg-black/75 text-caption text-white"
    >
      Loading CBCT…
    </div>
    <div
      v-else-if="failed"
      class="absolute inset-0 grid place-items-center bg-black/75 text-caption text-warning"
    >
      CBCT could not be displayed safely.
    </div>
  </section>
</template>
