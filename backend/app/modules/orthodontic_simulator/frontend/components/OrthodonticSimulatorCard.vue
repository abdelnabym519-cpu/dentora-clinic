<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import type { TresContext } from '@tresjs/core'
import * as THREE from 'three'
import {
  capabilityHeadline,
  movementPayload,
  schematicTeeth,
  stageLabel,
  type PreviewMode,
  type SchematicTooth,
  type SimulatorArch
} from '../lib/simulator'
import { useOrthodonticSimulator } from '../composables/useOrthodonticSimulator'

interface Ctx {
  patient: { id: string }
}

const props = defineProps<{ ctx: Ctx }>()
const { can } = usePermissions()
const {
  capability,
  capabilityStatus,
  running,
  runError,
  result,
  run
} = useOrthodonticSimulator(() => props.ctx.patient.id)

const arch = ref<SimulatorArch>('maxillary')
const selectedFdi = ref('11')
const previewMode = ref<PreviewMode>('before')
const stageIndex = ref(0)
const playing = ref(false)
const webglFailed = ref(false)
const x = ref(0)
const y = ref(0)
const z = ref(0)
const tip = ref(0)
const torque = ref(0)
const rotation = ref(0)
let timer: ReturnType<typeof setInterval> | null = null

const cameraPosition = new THREE.Vector3(0, 0, 19)
const keyLightPosition = new THREE.Vector3(4, 8, 12)
const toothScale = new THREE.Vector3(0.72, 1, 0.58)

const teeth = computed(() => schematicTeeth(arch.value))
const translationEnabled = computed(() => capability.value?.translation_eligible === true)
const rotationEnabled = computed(() => capability.value?.rotation_eligible === true)
const canWrite = computed(() => can('orthodontic_simulator.write'))
const stageCount = computed(() => result.value?.result.stages.length ?? 0)
const stageText = computed(() => stageLabel(stageIndex.value, stageCount.value))
const headline = computed(() => capabilityHeadline(capability.value ?? null))
const currentDigest = computed(() => result.value?.result.reproducibility_digest ?? null)

function schematicPosition(tooth: SchematicTooth): THREE.Vector3 {
  return new THREE.Vector3(tooth.x, tooth.y, tooth.z)
}

function selectTooth(fdi: string): void {
  selectedFdi.value = fdi
}

function setArch(next: SimulatorArch): void {
  arch.value = next
  selectedFdi.value = next === 'maxillary' ? '11' : '41'
}

function setPreviewMode(next: PreviewMode): void {
  previewMode.value = next
}

function stopPlayback(): void {
  playing.value = false
  if (timer !== null) clearInterval(timer)
  timer = null
}

function togglePlayback(): void {
  if (stageCount.value <= 1) return
  if (playing.value) {
    stopPlayback()
    return
  }
  playing.value = true
  timer = setInterval(() => {
    if (stageCount.value === 0) {
      stopPlayback()
      return
    }
    stageIndex.value = (stageIndex.value + 1) % stageCount.value
  }, 900)
}

async function runSelected(): Promise<void> {
  if (!translationEnabled.value || !canWrite.value) return
  const response = await run(movementPayload(selectedFdi.value, {
    x: x.value,
    y: y.value,
    z: z.value,
    tip: rotationEnabled.value ? tip.value : 0,
    torque: rotationEnabled.value ? torque.value : 0,
    rotation: rotationEnabled.value ? rotation.value : 0
  }))
  stageIndex.value = response?.result.stages.length ? 0 : 0
  previewMode.value = response ? 'after' : 'before'
}

function onReady(context: TresContext): void {
  const renderer = context.renderer.instance
  if (!(renderer instanceof THREE.WebGLRenderer) || !renderer.capabilities.isWebGL2) {
    webglFailed.value = true
  }
}

onBeforeUnmount(stopPlayback)
</script>

<template>
  <SummaryCard
    title="Orthodontic Simulator"
    icon="i-lucide-git-compare-arrows"
    :loading="capabilityStatus === 'pending'"
  >
    <section data-testid="orthodontic-simulator-card" class="space-y-3">
      <div class="rounded-md border border-default bg-elevated p-3 text-caption">
        <p data-testid="orthodontic-simulator-headline" class="font-medium text-default">
          {{ headline }}
        </p>
        <p class="mt-1 text-muted">
          Deterministic visualization sandbox only — not a clinical prediction, diagnosis, or treatment approval.
        </p>
      </div>

      <div
        v-if="capability"
        data-testid="orthodontic-simulator-capability"
        class="space-y-1 text-caption"
      >
        <div class="flex flex-wrap gap-x-3 text-muted">
          <span>Whole-arch: {{ capability.whole_arch_mesh_count }}</span>
          <span>Per-tooth: {{ capability.per_tooth_mesh_count }}</span>
          <span>Reviewed: {{ capability.reviewed_per_tooth_mesh_count }}</span>
          <span>Accepted frame: {{ capability.accepted_alignment ? 'yes' : 'no' }}</span>
        </div>
        <ul v-if="capability.reasons.length" class="list-disc space-y-0.5 ps-5 text-warning">
          <li v-for="reason in capability.reasons" :key="reason.code" :data-reason-code="reason.code">
            {{ reason.message }}
          </li>
        </ul>
      </div>

      <div class="flex flex-wrap items-center gap-2">
        <button
          data-testid="ortho-upper-jaw"
          type="button"
          class="rounded border border-default px-2 py-1 text-caption"
          :aria-pressed="arch === 'maxillary'"
          @click="setArch('maxillary')"
        >
          Upper jaw
        </button>
        <button
          data-testid="ortho-lower-jaw"
          type="button"
          class="rounded border border-default px-2 py-1 text-caption"
          :aria-pressed="arch === 'mandibular'"
          @click="setArch('mandibular')"
        >
          Lower jaw
        </button>
        <span data-testid="ortho-selected-fdi" class="ms-auto text-caption font-medium">
          FDI {{ selectedFdi }}
        </span>
      </div>

      <ClientOnly>
        <div
          v-if="webglFailed"
          data-testid="ortho-webgl-fallback"
          class="grid h-52 place-items-center rounded-md border border-default bg-elevated text-caption text-warning"
        >
          WebGL2 is required for the 3D selector.
        </div>
        <div v-else class="h-52 overflow-hidden rounded-md border border-default bg-black">
          <TresCanvas
            data-testid="ortho-tres-canvas"
            render-mode="on-demand"
            :antialias="true"
            clear-color="#070b12"
            @ready="onReady"
            @error="webglFailed = true"
          >
            <TresPerspectiveCamera :position="cameraPosition" :fov="40" />
            <TresAmbientLight :intensity="1.8" />
            <TresDirectionalLight :position="keyLightPosition" :intensity="2" />
            <TresGroup>
              <TresMesh
                v-for="tooth in teeth"
                :key="tooth.fdi"
                :position="schematicPosition(tooth)"
                :scale="toothScale"
                :user-data="{ fdi: tooth.fdi, schematicOnly: true }"
                @click="selectTooth(tooth.fdi)"
              >
                <TresSphereGeometry :args="[0.7, 16, 12]" />
                <TresMeshStandardMaterial :color="selectedFdi === tooth.fdi ? '#60a5fa' : '#f3f4f6'" />
              </TresMesh>
            </TresGroup>
          </TresCanvas>
        </div>
        <template #fallback>
          <div class="h-52 rounded-md border border-default bg-elevated" />
        </template>
      </ClientOnly>
      <p class="text-subtle text-caption">
        FDI selector is schematic navigation only. It is not patient anatomy and never receives patient movement transforms.
      </p>

      <div class="grid grid-cols-3 gap-2 text-caption">
        <label>X mm<input v-model.number="x" data-testid="ortho-x" type="number" step="0.05" class="mt-1 w-full rounded border border-default bg-default px-2 py-1" :disabled="!translationEnabled"></label>
        <label>Y mm<input v-model.number="y" data-testid="ortho-y" type="number" step="0.05" class="mt-1 w-full rounded border border-default bg-default px-2 py-1" :disabled="!translationEnabled"></label>
        <label>Z mm<input v-model.number="z" data-testid="ortho-z" type="number" step="0.05" class="mt-1 w-full rounded border border-default bg-default px-2 py-1" :disabled="!translationEnabled"></label>
        <label>Tip °<input v-model.number="tip" data-testid="ortho-tip" type="number" step="0.5" class="mt-1 w-full rounded border border-default bg-default px-2 py-1" :disabled="!rotationEnabled"></label>
        <label>Torque °<input v-model.number="torque" data-testid="ortho-torque" type="number" step="0.5" class="mt-1 w-full rounded border border-default bg-default px-2 py-1" :disabled="!rotationEnabled"></label>
        <label>Rotation °<input v-model.number="rotation" data-testid="ortho-rotation" type="number" step="0.5" class="mt-1 w-full rounded border border-default bg-default px-2 py-1" :disabled="!rotationEnabled"></label>
      </div>

      <div class="flex flex-wrap gap-2">
        <button
          data-testid="ortho-run"
          type="button"
          class="rounded border border-default px-3 py-1 text-caption disabled:opacity-50"
          :disabled="!translationEnabled || !canWrite || running"
          @click="runSelected"
        >
          {{ running ? 'Building stages…' : 'Build deterministic stages' }}
        </button>
        <button
          data-testid="ortho-play"
          type="button"
          class="rounded border border-default px-3 py-1 text-caption disabled:opacity-50"
          :disabled="stageCount <= 1"
          @click="togglePlayback"
        >
          {{ playing ? 'Pause' : 'Play' }}
        </button>
      </div>

      <div class="space-y-2 border-t border-default pt-2">
        <div class="flex gap-2" role="group" aria-label="Preview mode">
          <button v-for="mode in (['before', 'after', 'overlay'] as PreviewMode[])" :key="mode" type="button" class="rounded border border-default px-2 py-1 text-caption disabled:opacity-50" :data-testid="`ortho-mode-${mode}`" :aria-pressed="previewMode === mode" :disabled="stageCount === 0 && mode !== 'before'" @click="setPreviewMode(mode)">
            {{ mode[0]!.toUpperCase() + mode.slice(1) }}
          </button>
        </div>
        <label class="block text-caption">
          {{ stageText }}
          <input v-model.number="stageIndex" data-testid="ortho-stage-slider" type="range" min="0" :max="Math.max(stageCount - 1, 0)" step="1" class="mt-1 w-full" :disabled="stageCount === 0">
        </label>
      </div>

      <p
        v-if="runError"
        data-testid="ortho-run-error"
        class="text-caption text-warning"
      >
        {{ runError }}
      </p>
      <p
        v-if="currentDigest"
        data-testid="ortho-digest"
        class="break-all font-mono text-subtle text-caption"
      >
        {{ currentDigest }}
      </p>
    </section>
  </SummaryCard>
</template>
