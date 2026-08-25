<script setup lang="ts">
/** ThreeUI clinical viewer. Geometry remains in native DICOM-patient mm. */
import { computed, onBeforeUnmount, reactive, ref, shallowRef } from 'vue'
import type { TresContext, TresPointerEvent } from '@tresjs/core'
import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { acceleratedRaycast } from 'three-mesh-bvh'
import type { ClinicalScene, PatientPointMm } from '../lib/clinicalScene'
import { registryFromClinicalScene } from '../lib/aiOverlayRegistry'
import { measurementFromLandmarks, type PatientMeasurement } from '../lib/patientMeasurements'
import { synchronizePatientPoint } from '../lib/patientCoordinateSync'
import { riskRegionsOf, type RiskClinicalScene } from '../lib/riskMap'

const props = withDefaults(defineProps<{
  clinicalScene: ClinicalScene | null
  height?: number
}>(), { height: 420 })

THREE.Mesh.prototype.raycast = acceleratedRaycast

const defaultCameraPosition = new THREE.Vector3(0, 0, 300)
const defaultLightPosition = new THREE.Vector3(150, 220, 300)

const webglFailed = ref(false)
const loading = ref(false)
const loadError = ref<string | null>(null)
const selectedPoint = ref<PatientPointMm | null>(null)
const landmarks = ref<PatientPointMm[]>([])
const measurements = ref<PatientMeasurement[]>([])
const clippingEnabled = ref(false)
const clippingAxis = ref<'x' | 'y' | 'z'>('z')
const clippingOffsetMm = ref(0)
const bounds = shallowRef<THREE.Box3 | null>(null)
const overlayVisibility = reactive<Record<string, boolean>>({})

let context: TresContext | null = null
let controls: OrbitControls | null = null

const registry = computed(() => props.clinicalScene
  ? registryFromClinicalScene(props.clinicalScene)
  : null)
const overlays = computed(() => registry.value?.list() ?? [])

const renderedScene = computed<ClinicalScene | null>(() => {
  if (!props.clinicalScene) return null
  const visible = (id: string) => overlayVisibility[id] !== false
  const next = {
    ...props.clinicalScene,
    geometry: props.clinicalScene.geometry.filter(layer => !layer.provenance.modelId || visible(layer.id)),
    nerves: props.clinicalScene.nerves.filter(pathway => visible(pathway.id)),
    riskRegions: riskRegionsOf(props.clinicalScene).filter(region => visible(region.id))
  } as RiskClinicalScene
  return next
})

const clippingPlane = computed<THREE.Plane | null>(() => {
  if (!clippingEnabled.value) return null
  const normal = clippingAxis.value === 'x'
    ? new THREE.Vector3(1, 0, 0)
    : clippingAxis.value === 'y'
      ? new THREE.Vector3(0, 1, 0)
      : new THREE.Vector3(0, 0, 1)
  return new THREE.Plane(normal, -clippingOffsetMm.value)
})

function onReady(nextContext: TresContext): void {
  context = nextContext
  const renderer = nextContext.renderer.instance
  if (!(renderer instanceof THREE.WebGLRenderer) || !renderer.capabilities.isWebGL2) {
    webglFailed.value = true
    return
  }
  renderer.localClippingEnabled = true
  const camera = nextContext.camera.activeCamera.value
  controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = false
  controls.screenSpacePanning = true
  controls.addEventListener('change', () => nextContext.renderer.invalidate())
  fitCamera()
}

function fitCamera(): void {
  if (!context || !controls || !bounds.value || bounds.value.isEmpty()) return
  const camera = context.camera.activeCamera.value
  if (!(camera instanceof THREE.PerspectiveCamera)) return
  const center = bounds.value.getCenter(new THREE.Vector3())
  const size = bounds.value.getSize(new THREE.Vector3())
  const radius = Math.max(size.length() * 0.5, 1)
  const distance = radius / Math.tan(THREE.MathUtils.degToRad(camera.fov * 0.5)) * 1.25
  camera.position.set(center.x, center.y, center.z + distance)
  camera.near = Math.max(0.1, distance - radius * 2.5)
  camera.far = Math.max(camera.near + 100, distance + radius * 4)
  camera.updateProjectionMatrix()
  controls.target.copy(center)
  controls.update()
  context.renderer.invalidate()
}

function onBounds(nextBounds: THREE.Box3): void {
  bounds.value = nextBounds.clone()
  fitCamera()
}

function onPick(event: TresPointerEvent): void {
  if (!props.clinicalScene || !event.object?.userData.clinicalPickable) return
  const point = { x: event.point.x, y: event.point.y, z: event.point.z }
  selectedPoint.value = point
  landmarks.value = [...landmarks.value.slice(-30), point]
  if (landmarks.value.length % 2 === 0) {
    const measurement = measurementFromLandmarks(
      landmarks.value.at(-2) ?? null,
      landmarks.value.at(-1) ?? null,
      `measurement-${measurements.value.length + 1}`
    )
    if (measurement) measurements.value = [...measurements.value, measurement]
  }
}

function onMprPoint(point: PatientPointMm): void {
  if (!props.clinicalScene) return
  selectedPoint.value = synchronizePatientPoint({
    frameOfReferenceUid: props.clinicalScene.frame.frameOfReferenceUid,
    unit: 'mm',
    point
  }, props.clinicalScene.frame)
}

function clearMeasurements(): void {
  landmarks.value = []
  measurements.value = []
}

function toggleOverlay(id: string, visible: boolean): void {
  overlayVisibility[id] = visible
  registry.value?.setVisible(id, visible)
  context?.renderer.invalidate()
}

onBeforeUnmount(() => {
  controls?.dispose()
  controls = null
  context = null
})
</script>

<template>
  <section
    data-testid="dental3d-threeui"
    class="space-y-2"
  >
    <div
      v-if="!clinicalScene"
      data-testid="dental3d-clinical-scene-empty"
      class="grid place-items-center rounded-md border border-default bg-elevated px-4 text-center text-caption text-muted"
      :style="{ height: `${height}px` }"
    >
      No registered patient-space clinical geometry is available. Synthetic geometry is not shown.
    </div>
    <div
      v-else-if="webglFailed"
      data-testid="dental3d-webgl-fallback"
      class="grid place-items-center rounded-md border border-default bg-elevated text-caption text-warning"
      :style="{ height: `${height}px` }"
    >
      WebGL2 is required for the clinical 3D viewer.
    </div>
    <div
      v-else
      class="relative overflow-hidden rounded-md border border-default bg-black"
      :style="{ height: `${height}px` }"
    >
      <TresCanvas
        data-testid="dental3d-tres-canvas"
        render-mode="on-demand"
        :dpr="[1, 2]"
        :antialias="true"
        :alpha="false"
        clear-color="#070b12"
        @ready="onReady"
        @error="webglFailed = true"
        @click="onPick"
      >
        <TresPerspectiveCamera
          :position="defaultCameraPosition"
          :near="0.1"
          :far="10000"
        />
        <TresAmbientLight :intensity="1.1" />
        <TresDirectionalLight
          :position="defaultLightPosition"
          :intensity="2.2"
        />
        <Dental3DClinicalScene
          v-if="renderedScene"
          :scene="renderedScene"
          :clipping-plane="clippingPlane"
          :landmarks="landmarks"
          :measurements="measurements"
          @bounds="onBounds"
          @loading="loading = $event"
          @error="loadError = $event"
        />
      </TresCanvas>

      <div class="absolute left-2 top-2 flex flex-wrap gap-1 text-caption">
        <span class="rounded bg-black/75 px-2 py-1 text-white">DICOM patient · mm</span>
        <span
          v-if="loading"
          class="rounded bg-black/75 px-2 py-1 text-white"
        >Loading clinical geometry…</span>
        <span
          v-if="loadError"
          class="rounded bg-black/75 px-2 py-1 text-warning"
        >{{ loadError }}</span>
      </div>
      <div
        v-if="selectedPoint"
        data-testid="dental3d-patient-point"
        class="absolute bottom-2 left-2 rounded bg-black/75 px-2 py-1 text-caption text-white"
      >
        {{ selectedPoint.x.toFixed(2) }}, {{ selectedPoint.y.toFixed(2) }}, {{ selectedPoint.z.toFixed(2) }} mm
      </div>
    </div>

    <div
      v-if="clinicalScene"
      class="grid gap-2 md:grid-cols-3"
    >
      <div class="rounded-md border border-default p-2 text-caption">
        <div class="font-medium text-default">
          Patient-space tools
        </div>
        <div class="mt-1 flex flex-wrap gap-2">
          <button
            type="button"
            class="rounded border border-default px-2 py-1 text-muted"
            @click="clearMeasurements"
          >
            Clear landmarks
          </button>
          <label class="inline-flex items-center gap-1 text-muted">
            <input
              v-model="clippingEnabled"
              type="checkbox"
            > Clip
          </label>
          <select
            v-model="clippingAxis"
            class="rounded border border-default bg-default px-1"
          >
            <option value="x">X</option>
            <option value="y">Y</option>
            <option value="z">Z</option>
          </select>
          <input
            v-model.number="clippingOffsetMm"
            aria-label="Clipping offset millimetres"
            type="number"
            step="1"
            class="w-20 rounded border border-default bg-default px-1"
          >
        </div>
        <ul
          data-testid="dental3d-measurements"
          class="mt-1 text-muted"
        >
          <li
            v-for="measurement in measurements"
            :key="measurement.id"
          >
            {{ measurement.id }}: {{ measurement.distanceMm.toFixed(2) }} mm
          </li>
        </ul>
      </div>

      <div class="rounded-md border border-default p-2 text-caption">
        <div class="font-medium text-default">
          AI overlays
        </div>
        <label
          v-for="overlay in overlays"
          :key="overlay.id"
          class="mt-1 flex items-center justify-between gap-2 text-muted"
        >
          <span>{{ overlay.type }} · {{ overlay.reviewStatus }}</span>
          <input
            type="checkbox"
            :checked="overlayVisibility[overlay.id] !== false"
            @change="toggleOverlay(overlay.id, ($event.target as HTMLInputElement).checked)"
          >
        </label>
        <p
          v-if="overlays.length === 0"
          class="mt-1 text-subtle"
        >
          No registered AI overlay.
        </p>
      </div>

      <div class="rounded-md border border-default p-2 text-caption">
        <div class="font-medium text-default">
          Safety and provenance
        </div>
        <p class="mt-1 text-muted">
          Frame: {{ clinicalScene.frame.frameOfReferenceUid }}
        </p>
        <p class="text-muted">
          Alignment: {{ clinicalScene.alignment?.status ?? 'not accepted' }}
        </p>
        <p
          v-for="layer in clinicalScene.geometry"
          :key="layer.id"
          class="truncate text-subtle"
          :title="layer.provenance.identifier"
        >
          {{ layer.kind }} · {{ layer.reviewStatus }} · {{ layer.provenance.source }}
        </p>
        <p
          v-for="blocker in clinicalScene.blockers"
          :key="blocker"
          class="text-warning"
        >
          {{ blocker }}
        </p>
      </div>
    </div>

    <Dental3DCbctMpr
      v-if="clinicalScene"
      :cbct="clinicalScene.cbct"
      :patient-point="selectedPoint"
      @patient-point="onMprPoint"
    />
  </section>
</template>
