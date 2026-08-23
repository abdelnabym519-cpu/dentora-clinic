<script setup lang="ts">
/**
 * Dental3DViewer — WebGL viewer for a dental scene (three.js).
 *
 * Client-only by contract: the slot plugin loads this component through
 * ``defineAsyncComponent`` from a ``.client.ts`` plugin, and the card
 * additionally wraps it in ``<ClientOnly>`` so SSR never touches
 * WebGL.
 *
 * Rendering seam (Phase 2): the viewer renders whatever it is given —
 * a list of resolved mesh references (``SceneMeshRef`` from
 * ``../lib/sceneMeshes``) plus the synthetic tooth placements. Real
 * surface geometry (STL / OBJ) is fetched through ``useDental3DMeshIO``
 * (media's authorized download route), parsed with three.js loaders and
 * normalized into the same framing as the synthetic arch. When a real
 * mesh is ready it replaces the synthetic arch; while loading or on
 * error the synthetic arch stays visible (graceful fallback — a failed
 * scan load never breaks the card). Future mesh kinds (segmented
 * tooth, nerve path, implant) extend ``SceneMeshKind``, not this
 * component's architecture.
 *
 * Owns the full three.js lifecycle: renderer, camera, lights, orbit /
 * zoom / pan controls (OrbitControls), responsive resizing and
 * disposal of every GPU resource on unmount.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { OBJLoader } from 'three/addons/loaders/OBJLoader.js'
import { STLLoader } from 'three/addons/loaders/STLLoader.js'
import { getTreatmentColor } from '~~/app/config/odontogramConstants'
import {
  conditionColorToken,
  ENAMEL_COLOR,
  ENAMEL_COLOR_DARK,
  layoutArch,
  renderableTeeth,
  type DentalToothView
} from '../lib/dentalArch'
import {
  meshOverlay,
  pickActiveMesh,
  type MeshLoadPhase,
  type SceneMeshRef
} from '../lib/sceneMeshes'
import { useDental3DMeshIO } from '../composables/useDental3DScene'

const props = withDefaults(
  defineProps<{
    teeth: DentalToothView[]
    /** Real mesh references (resolved server-side; may be empty). */
    meshes?: SceneMeshRef[]
    /** Upper arch order (host FDI constant) — injectable for tests. */
    upperOrder?: number[]
    /** Lower arch order (host FDI constant) — injectable for tests. */
    lowerOrder?: number[]
    height?: number
  }>(),
  {
    meshes: () => [],
    upperOrder: () => [18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28],
    lowerOrder: () => [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38],
    height: 240
  }
)

const { t } = useI18n()
const colorMode = useColorMode()
const { fetchMeshContent } = useDental3DMeshIO()

const containerRef = ref<HTMLDivElement | null>(null)
const canvasRef = ref<HTMLCanvasElement | null>(null)
const webglFailed = ref(false)

let renderer: THREE.WebGLRenderer | null = null
let scene: THREE.Scene | null = null
let camera: THREE.PerspectiveCamera | null = null
let controls: OrbitControls | null = null
let animationId = 0
let resizeObserver: ResizeObserver | null = null
/** Every geometry / material created here — disposed on unmount. */
const disposables: Array<THREE.BufferGeometry | THREE.Material> = []

/** Real-mesh state machine (idle → loading → ready | error). */
const meshPhase = ref<MeshLoadPhase>('idle')
const activeMesh = computed(() => pickActiveMesh(props.meshes))
const overlay = computed(() => meshOverlay(props.meshes, meshPhase.value))

/** Target span a real mesh is scaled into (matches the arch framing). */
const MESH_TARGET_SPAN = 4.2

const isDark = computed(() => colorMode.value === 'dark')

function resolveColor(tooth: DentalToothView): string {
  if (tooth.color) return tooth.color
  const token = conditionColorToken(tooth.condition)
  if (token === null) return isDark.value ? ENAMEL_COLOR_DARK : ENAMEL_COLOR
  return getTreatmentColor(token, isDark.value)
}

/** Synthetic crown+root shape per FDI category (demo geometry only). */
function buildToothMeshes(tooth: DentalToothView): THREE.Group {
  const group = new THREE.Group()
  const unit = tooth.tooth_number % 10
  const category = unit <= 2 ? 'incisor' : unit === 3 ? 'canine' : unit <= 5 ? 'premolar' : 'molar'
  const r = category === 'molar' ? 0.16 : category === 'premolar' ? 0.13 : 0.1
  const h = category === 'incisor' || category === 'canine' ? 0.34 : 0.26

  const crownGeometry = new THREE.LatheGeometry(
    [
      new THREE.Vector2(0.001, 0),
      new THREE.Vector2(r * 0.62, h * 0.12),
      new THREE.Vector2(r, h * 0.55),
      new THREE.Vector2(r * 0.66, h * 0.95),
      new THREE.Vector2(0.001, h)
    ],
    20
  )
  const rootGeometry = new THREE.ConeGeometry(0.055, 0.42, 10)
  const material = new THREE.MeshStandardMaterial({
    color: new THREE.Color(resolveColor(tooth)),
    roughness: 0.42,
    metalness: 0.05
  })
  disposables.push(crownGeometry, rootGeometry, material)

  const crown = new THREE.Mesh(crownGeometry, material)
  const root = new THREE.Mesh(rootGeometry, material)
  root.position.y = -0.21
  group.add(crown, root)
  return group
}

function removeDentalObjects(): void {
  if (!scene) return
  // GPU resources live in `disposables` — this only drops the scene graph.
  for (const child of [...scene.children]) {
    if (child instanceof THREE.Group && child.userData.dental3d === true) {
      scene.remove(child)
    }
  }
}

function buildScene(): void {
  if (!scene) return
  removeDentalObjects()

  // Real geometry replaces the synthetic arch when it is ready.
  if (!overlay.value.renderSynthetic) return

  const upper = layoutArch(props.upperOrder, 'upper')
  const lower = layoutArch(props.lowerOrder, 'lower')

  for (const tooth of renderableTeeth(props.teeth)) {
    const placement = upper.get(tooth.tooth_number) ?? lower.get(tooth.tooth_number)
    if (!placement) continue

    const mesh = buildToothMeshes(tooth)
    mesh.position.set(placement.x, placement.y, placement.z)
    mesh.rotation.y = placement.rotY
    mesh.scale.set(placement.scale.x, placement.scale.y, placement.scale.z)
    mesh.userData.dental3d = true
    scene.add(mesh)
  }
}

/** Parse + normalize one real surface mesh into the viewer framing. */
function buildSurfaceMesh(mesh: SceneMeshRef, content: ArrayBuffer | string): THREE.Group {
  const material = new THREE.MeshStandardMaterial({
    color: new THREE.Color(isDark.value ? 0xE2E8F0 : 0xF1F5F9),
    roughness: 0.5,
    metalness: 0.08,
    side: THREE.DoubleSide
  })
  disposables.push(material)

  let object: THREE.Object3D
  if (mesh.format === 'stl') {
    const geometry = new STLLoader().parse(content as ArrayBuffer)
    geometry.computeVertexNormals()
    disposables.push(geometry)
    object = new THREE.Mesh(geometry, material)
  } else {
    const group = new OBJLoader().parse(content as string)
    group.traverse((child) => {
      if (child instanceof THREE.Mesh) {
        child.material = material
        disposables.push(child.geometry)
      }
    })
    object = group
  }

  // Normalize into the arch framing: center at the origin and scale the
  // longest dimension to MESH_TARGET_SPAN, whatever the source units
  // (intraoral scanners export mm — the viewer is unit-agnostic).
  const wrapper = new THREE.Group()
  wrapper.add(object)
  const box = new THREE.Box3().setFromObject(object)
  const size = box.getSize(new THREE.Vector3())
  const center = box.getCenter(new THREE.Vector3())
  const maxDimension = Math.max(size.x, size.y, size.z) || 1
  wrapper.scale.setScalar(MESH_TARGET_SPAN / maxDimension)
  object.position.set(-center.x, -center.y, -center.z)
  wrapper.userData.dental3d = true
  return wrapper
}

function showSurfaceMesh(mesh: SceneMeshRef, content: ArrayBuffer | string): void {
  if (!scene) return
  removeDentalObjects()
  scene.add(buildSurfaceMesh(mesh, content))
}

async function loadActiveMesh(): Promise<void> {
  const mesh = activeMesh.value
  if (!scene) return

  if (!mesh) {
    // No real geometry (anymore) → plain Phase 1 rendering.
    meshPhase.value = 'idle'
    buildScene()
    return
  }

  meshPhase.value = 'loading'
  try {
    const content = await fetchMeshContent(mesh)
    if (activeMesh.value?.id !== mesh.id || !scene) return // stale response
    showSurfaceMesh(mesh, content)
    meshPhase.value = 'ready'
  } catch (error) {
    console.error('Error loading dental mesh:', error)
    if (activeMesh.value?.id === mesh.id) {
      // Graceful fallback: explicit error chip + synthetic arch.
      meshPhase.value = 'error'
      buildScene()
    }
  }
}

function resize(): void {
  if (!renderer || !camera || !containerRef.value) return
  const { clientWidth, clientHeight } = containerRef.value
  if (clientWidth === 0 || clientHeight === 0) return
  renderer.setSize(clientWidth, clientHeight, false)
  camera.aspect = clientWidth / clientHeight
  camera.updateProjectionMatrix()
}

function init(): void {
  const canvas = canvasRef.value
  const container = containerRef.value
  if (!canvas || !container) return

  try {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true })
  } catch {
    webglFailed.value = true
    return
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))

  scene = new THREE.Scene()
  camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100)
  camera.position.set(0, 1.7, 4.6)

  const ambient = new THREE.AmbientLight(0xffffff, 0.85)
  const directional = new THREE.DirectionalLight(0xffffff, 1.5)
  directional.position.set(2.5, 3.5, 4)
  scene.add(ambient, directional)

  controls = new OrbitControls(camera, canvas)
  controls.enableDamping = true
  controls.dampingFactor = 0.08
  controls.minDistance = 1.5
  controls.maxDistance = 12
  controls.target.set(0, 0, 0)

  buildScene()
  resize()

  resizeObserver = new ResizeObserver(() => resize())
  resizeObserver.observe(container)

  const loop = () => {
    animationId = requestAnimationFrame(loop)
    controls?.update()
    if (renderer && scene && camera) renderer.render(scene, camera)
  }
  loop()
}

watch(
  () => props.teeth,
  () => {
    if (overlay.value.renderSynthetic) buildScene()
  },
  { deep: true }
)

watch(activeMesh, () => loadActiveMesh())

watch(isDark, () => {
  // Re-materialize whatever is on screen (synthetic colors / scan tone).
  if (meshPhase.value === 'ready' && activeMesh.value) loadActiveMesh()
  else buildScene()
})

onMounted(() => {
  init()
  loadActiveMesh()
})

onBeforeUnmount(() => {
  if (animationId) cancelAnimationFrame(animationId)
  resizeObserver?.disconnect()
  controls?.dispose()
  removeDentalObjects()
  for (const resource of disposables) resource.dispose()
  disposables.length = 0
  renderer?.dispose()
  renderer = null
  scene = null
  camera = null
  controls = null
})
</script>

<template>
  <div>
    <div
      v-if="webglFailed"
      data-testid="dental3d-webgl-fallback"
      class="flex items-center justify-center rounded-md border border-default bg-elevated text-caption text-muted"
      :style="{ height: `${height}px` }"
    >
      {{ t('dental_3d.viewer.webglUnavailable') }}
    </div>
    <div
      v-else
      ref="containerRef"
      data-testid="dental3d-viewer"
      class="relative w-full cursor-grab overflow-hidden rounded-md border border-default bg-default"
      :style="{ height: `${height}px` }"
    >
      <canvas
        ref="canvasRef"
        data-testid="dental3d-canvas"
        class="block h-full w-full"
      />
      <span class="pointer-events-none absolute bottom-1 right-2 text-subtle text-caption">
        {{ t('dental_3d.viewer.hint') }}
      </span>
      <span
        v-if="overlay.showLoading"
        data-testid="dental3d-mesh-loading"
        class="pointer-events-none absolute left-2 top-2 rounded bg-elevated/90 px-2 py-1 text-caption text-muted"
      >
        {{ t('dental_3d.viewer.meshLoading') }}
      </span>
      <span
        v-else-if="overlay.showError"
        data-testid="dental3d-mesh-error"
        class="pointer-events-none absolute left-2 top-2 rounded bg-elevated/90 px-2 py-1 text-caption text-warning"
      >
        {{ t('dental_3d.viewer.meshError') }}
      </span>
      <span
        v-else-if="overlay.showBadge"
        data-testid="dental3d-mesh-badge"
        class="pointer-events-none absolute left-2 top-2 rounded bg-elevated/90 px-2 py-1 text-caption text-muted"
        :title="activeMesh?.label ?? undefined"
      >
        {{ t('dental_3d.viewer.meshBadge') }} · {{ activeMesh?.format.toUpperCase() }}
      </span>
    </div>
  </div>
</template>
