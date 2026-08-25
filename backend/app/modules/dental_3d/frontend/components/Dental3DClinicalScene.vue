<script setup lang="ts">
import { onBeforeUnmount, shallowRef, watch } from 'vue'
import { useTres } from '@tresjs/core'
import * as THREE from 'three'
import { OBJLoader } from 'three/addons/loaders/OBJLoader.js'
import { PLYLoader } from 'three/addons/loaders/PLYLoader.js'
import { STLLoader } from 'three/addons/loaders/STLLoader.js'
import { computeBoundsTree, disposeBoundsTree } from 'three-mesh-bvh'
import type {
  ClinicalGeometryLayer,
  ClinicalScene,
  PatientPointMm
} from '../lib/clinicalScene'
import { implantPlanningOf } from '../lib/implantScene'
import type { PatientMeasurement } from '../lib/patientMeasurements'
import { useDental3DMeshIO } from '../composables/useDental3DScene'

const props = defineProps<{
  scene: ClinicalScene
  clippingPlane: THREE.Plane | null
  landmarks: PatientPointMm[]
  measurements: PatientMeasurement[]
}>()

const emit = defineEmits<{
  bounds: [box: THREE.Box3]
  loading: [value: boolean]
  error: [message: string]
}>()

const { invalidate } = useTres()
const { fetchGeometryContent } = useDental3DMeshIO()
const patientRoot = shallowRef(new THREE.Group())
const annotationRoot = shallowRef(new THREE.Group())
patientRoot.value.name = 'dentora-patient-space-root-mm'
annotationRoot.value.name = 'dentora-patient-annotations-mm'

let request: AbortController | null = null
let generation = 0

function materialsOf(object: THREE.Object3D): THREE.Material[] {
  const materials: THREE.Material[] = []
  object.traverse((child) => {
    if (!(child instanceof THREE.Mesh)) return
    if (Array.isArray(child.material)) materials.push(...child.material)
    else if (child.material) materials.push(child.material)
  })
  return materials
}

function disposeGroup(group: THREE.Group): void {
  group.traverse((child) => {
    if (!(child instanceof THREE.Mesh) && !(child instanceof THREE.Line)) return
    const geometry = child.geometry as THREE.BufferGeometry & { boundsTree?: unknown }
    if (geometry.boundsTree) disposeBoundsTree.call(geometry)
    geometry.dispose()
    const materials = Array.isArray(child.material) ? child.material : [child.material]
    for (const material of materials) material.dispose()
  })
  group.clear()
}

function layerColor(layer: ClinicalGeometryLayer): number {
  if (layer.kind === 'ios_surface') return 0xD8DEE9
  if (layer.kind === 'tooth') return 0xF8FAFC
  if (layer.kind === 'mandible') return 0xD6B88D
  return 0xA7C7E7
}

function clinicalMaterial(layer: ClinicalGeometryLayer): THREE.MeshStandardMaterial {
  return new THREE.MeshStandardMaterial({
    color: layerColor(layer),
    roughness: 0.55,
    metalness: 0.02,
    side: THREE.DoubleSide,
    transparent: layer.reviewStatus === 'pending',
    opacity: layer.reviewStatus === 'pending' ? 0.78 : 1,
    clippingPlanes: props.clippingPlane ? [props.clippingPlane] : []
  })
}

function prepareGeometry(geometry: THREE.BufferGeometry): void {
  if (!geometry.getAttribute('normal')) geometry.computeVertexNormals()
  geometry.computeBoundingBox()
  computeBoundsTree.call(geometry, { maxLeafTris: 20 })
}

function parseLayer(layer: ClinicalGeometryLayer, content: ArrayBuffer | string): THREE.Object3D {
  const material = clinicalMaterial(layer)
  let object: THREE.Object3D
  if (layer.format === 'stl') {
    const geometry = new STLLoader().parse(content as ArrayBuffer)
    prepareGeometry(geometry)
    object = new THREE.Mesh(geometry, material)
  } else if (layer.format === 'ply') {
    const geometry = new PLYLoader().parse(content as ArrayBuffer)
    prepareGeometry(geometry)
    object = new THREE.Mesh(geometry, material)
  } else {
    object = new OBJLoader().parse(content as string)
    object.traverse((child) => {
      if (child instanceof THREE.Mesh) {
        prepareGeometry(child.geometry)
        child.material = material.clone()
      }
    })
    material.dispose()
  }

  const wrapper = new THREE.Group()
  wrapper.name = `clinical-layer:${layer.kind}:${layer.id}`
  wrapper.matrixAutoUpdate = false
  const matrixValues = layer.patientTransform.flat() as [
    number, number, number, number,
    number, number, number, number,
    number, number, number, number,
    number, number, number, number
  ]
  wrapper.matrix.set(...matrixValues)
  wrapper.userData.clinicalLayer = layer
  object.traverse((child) => {
    if (child instanceof THREE.Mesh) {
      child.userData.clinicalPickable = true
      child.userData.clinicalLayerId = layer.id
    }
  })
  wrapper.add(object)
  return wrapper
}

function nerveObject(scene: ClinicalScene): THREE.Group {
  const group = new THREE.Group()
  group.name = 'clinical-nerve-overlays'
  for (const pathway of scene.nerves) {
    const curve = new THREE.CatmullRomCurve3(
      pathway.points.map(point => new THREE.Vector3(point.x, point.y, point.z))
    )
    const geometry = new THREE.TubeGeometry(
      curve,
      Math.max(24, pathway.points.length * 4),
      0.6,
      8,
      false
    )
    prepareGeometry(geometry)
    const material = new THREE.MeshStandardMaterial({
      color: pathway.status === 'uncertain' ? 0xF59E0B : 0xEF4444,
      transparent: pathway.reviewStatus === 'pending' || pathway.status === 'uncertain',
      opacity: pathway.reviewStatus === 'pending' || pathway.status === 'uncertain' ? 0.65 : 0.92,
      clippingPlanes: props.clippingPlane ? [props.clippingPlane] : []
    })
    const mesh = new THREE.Mesh(geometry, material)
    mesh.name = `nerve:${pathway.id}`
    mesh.userData.clinicalPickable = true
    mesh.userData.aiOverlayId = pathway.id
    group.add(mesh)
  }
  return group
}

function implantPlanningObject(scene: ClinicalScene): THREE.Group {
  const group = new THREE.Group()
  group.name = 'clinical-implant-planning-overlays'
  const planning = implantPlanningOf(scene)
  const patientY = new THREE.Vector3(0, 1, 0)

  for (const implant of planning.implants) {
    const geometry = new THREE.CylinderGeometry(
      implant.diameterMm * 0.5,
      implant.diameterMm * 0.5,
      implant.lengthMm,
      32
    )
    prepareGeometry(geometry)
    const material = new THREE.MeshStandardMaterial({
      color: implant.status === 'accepted' ? 0x22C55E : 0x38BDF8,
      roughness: 0.4,
      metalness: 0.35,
      transparent: implant.status !== 'accepted',
      opacity: implant.status === 'accepted' ? 0.9 : 0.72,
      clippingPlanes: props.clippingPlane ? [props.clippingPlane] : []
    })
    const mesh = new THREE.Mesh(geometry, material)
    const axis = new THREE.Vector3(implant.axis.x, implant.axis.y, implant.axis.z)
    mesh.position.set(implant.center.x, implant.center.y, implant.center.z)
    mesh.quaternion.setFromUnitVectors(patientY, axis)
    mesh.name = `implant-plan:${implant.planId}:revision:${implant.revisionNumber}`
    mesh.userData.clinicalPickable = true
    mesh.userData.implantPlanId = implant.planId
    group.add(mesh)

    const half = implant.lengthMm * 0.5
    const center = new THREE.Vector3(implant.center.x, implant.center.y, implant.center.z)
    const axisGeometry = new THREE.BufferGeometry().setFromPoints([
      center.clone().addScaledVector(axis, -half),
      center.clone().addScaledVector(axis, half)
    ])
    const axisMaterial = new THREE.LineBasicMaterial({
      color: 0xE2E8F0,
      clippingPlanes: props.clippingPlane ? [props.clippingPlane] : []
    })
    group.add(new THREE.Line(axisGeometry, axisMaterial))
  }

  for (const target of planning.prostheticTargets) {
    const center = new THREE.Vector3(target.center.x, target.center.y, target.center.z)
    const axis = new THREE.Vector3(target.axis.x, target.axis.y, target.axis.z)
    const marker = new THREE.Mesh(
      new THREE.SphereGeometry(1.25, 16, 12),
      new THREE.MeshStandardMaterial({
        color: 0xF59E0B,
        clippingPlanes: props.clippingPlane ? [props.clippingPlane] : []
      })
    )
    marker.position.copy(center)
    marker.name = `prosthetic-target:${target.id}`
    marker.userData.clinicalPickable = true
    group.add(marker)

    const axisGeometry = new THREE.BufferGeometry().setFromPoints([
      center,
      center.clone().addScaledVector(axis, 12)
    ])
    const axisMaterial = new THREE.LineBasicMaterial({
      color: 0xF59E0B,
      clippingPlanes: props.clippingPlane ? [props.clippingPlane] : []
    })
    group.add(new THREE.Line(axisGeometry, axisMaterial))
  }

  return group
}

async function loadScene(): Promise<void> {
  request?.abort()
  request = new AbortController()
  const current = ++generation
  emit('loading', true)
  try {
    const loaded = await Promise.all(props.scene.geometry.map(async (layer) => {
      const content = await fetchGeometryContent(layer.url, layer.format, request!.signal)
      return parseLayer(layer, content)
    }))
    if (current !== generation) {
      for (const object of loaded) {
        const temporary = new THREE.Group()
        temporary.add(object)
        disposeGroup(temporary)
      }
      return
    }
    disposeGroup(patientRoot.value)
    patientRoot.value.position.set(0, 0, 0)
    patientRoot.value.scale.set(1, 1, 1)
    patientRoot.value.rotation.set(0, 0, 0)
    patientRoot.value.add(
      ...loaded,
      nerveObject(props.scene),
      implantPlanningObject(props.scene)
    )
    patientRoot.value.updateMatrixWorld(true)
    const bounds = new THREE.Box3().setFromObject(patientRoot.value)
    if (!bounds.isEmpty()) emit('bounds', bounds)
    invalidate()
  } catch (error) {
    if ((error as { name?: string }).name !== 'AbortError') {
      emit('error', 'Clinical geometry could not be loaded')
    }
  } finally {
    if (current === generation) emit('loading', false)
  }
}

function buildAnnotations(): void {
  disposeGroup(annotationRoot.value)
  const landmarkMaterial = new THREE.MeshStandardMaterial({
    color: 0x22D3EE,
    clippingPlanes: props.clippingPlane ? [props.clippingPlane] : []
  })
  for (const [index, point] of props.landmarks.entries()) {
    const geometry = new THREE.SphereGeometry(0.75, 16, 12)
    const mesh = new THREE.Mesh(geometry, landmarkMaterial.clone())
    mesh.name = `landmark:${index + 1}`
    mesh.position.set(point.x, point.y, point.z)
    annotationRoot.value.add(mesh)
  }
  landmarkMaterial.dispose()
  for (const measurement of props.measurements) {
    const geometry = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(measurement.start.x, measurement.start.y, measurement.start.z),
      new THREE.Vector3(measurement.end.x, measurement.end.y, measurement.end.z)
    ])
    const material = new THREE.LineBasicMaterial({
      color: 0x22D3EE,
      clippingPlanes: props.clippingPlane ? [props.clippingPlane] : []
    })
    annotationRoot.value.add(new THREE.Line(geometry, material))
  }
  invalidate()
}

watch(() => props.scene, () => void loadScene(), { immediate: true, deep: false })
watch(
  [() => props.landmarks, () => props.measurements],
  buildAnnotations,
  { immediate: true, deep: true }
)
watch(() => props.clippingPlane, (plane) => {
  for (const material of [...materialsOf(patientRoot.value), ...materialsOf(annotationRoot.value)]) {
    material.clippingPlanes = plane ? [plane] : []
    material.needsUpdate = true
  }
  invalidate()
}, { deep: true })

onBeforeUnmount(() => {
  generation += 1
  request?.abort()
  disposeGroup(patientRoot.value)
  disposeGroup(annotationRoot.value)
})
</script>

<template>
  <primitive :object="patientRoot" />
  <primitive :object="annotationRoot" />
</template>
