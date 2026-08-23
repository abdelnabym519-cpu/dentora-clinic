/**
 * dentalArch — pure FDI odontogram geometry helpers.
 *
 * Framework-free math seam (ADR 0019): nothing here imports three.js
 * or Vue, so the layout is unit-testable without WebGL and the viewer
 * simply applies the returned placements to ``THREE.Object3D``
 * transforms. Keeping it pure also means a future renderer (or a
 * server-side preview generator) can reuse the exact same arch.
 *
 * Layout model: an arch of n teeth is parametrised by t ∈ [-1, 1]
 * across the order array (t = 0 at the midline), so for the standard
 * 16-tooth arch the central incisors flank the midline at t = ±1/15.
 *
 * - x = ±ARCH_HALF_WIDTH · t — patient's right (Q1/Q4) at negative x,
 *   mirrored about the midline.
 * - z = -ARCH_DEPTH · t² — a parabola pulling molars back from the
 *   camera; centrals sit essentially at the front.
 * - rotY = MOLAR_YAW · t — molars yaw outward, centrals face the
 *   camera (≈ 0, not exactly 0 for t = ±1/15).
 * - y = ±ARCH_GAP / 2 — upper arch above the occlusal plane, lower
 *   below it.
 * - Deciduous teeth shrink by DECIDUOUS_SCALE so a mixed arch keeps
 *   plausible relative proportions.
 */

/** Light-theme enamel tone for healthy teeth. */
export const ENAMEL_COLOR = '#f5f2ea'

/** Dark-theme enamel tone for healthy teeth. */
export const ENAMEL_COLOR_DARK = '#c8cfd6'

/** Molar |x| offset from the midline. */
const ARCH_HALF_WIDTH = 2.2

/** How deep molars sit relative to the central incisors (z < 0). */
const ARCH_DEPTH = 1.5

/** Vertical gap between the upper and lower arch centroids. */
const ARCH_GAP = 0.5

/** Outward yaw applied at the arch ends (t = ±1). */
const MOLAR_YAW = Math.PI / 5

/** Deciduous teeth render smaller than their permanent successors. */
const DECIDUOUS_SCALE = 0.78

/** Per-category base proportions (multiplied by DECIDUOUS_SCALE for baby teeth). */
const TOOTH_SCALE: Record<ToothSizeCategory, { x: number, y: number, z: number }> = {
  incisor: { x: 1.0, y: 1.1, z: 0.8 },
  canine: { x: 1.05, y: 1.15, z: 0.9 },
  premolar: { x: 1.1, y: 1.2, z: 1.0 },
  molar: { x: 1.25, y: 1.25, z: 1.1 }
}

export type ArchSide = 'upper' | 'lower'

export type ToothSizeCategory = 'incisor' | 'canine' | 'premolar' | 'molar'

/** Viewer-ready transform for one tooth (applied verbatim to three.js). */
export type ToothPlacement = {
  x: number
  y: number
  z: number
  rotY: number
  scale: { x: number, y: number, z: number }
}

/** One tooth of a dental scene, as returned by the dental_3d API. */
export type DentalToothView = {
  tooth_number: number
  present: boolean
  visible: boolean
  condition: string
  color: string | null
}

/** FDI quadrant digit (1–4 permanent, 5–8 deciduous). Throws RangeError otherwise. */
export function quadrantOf(fdi: number): 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 {
  if (!Number.isInteger(fdi)) {
    throw new RangeError(`tooth number must be an integer: ${fdi}`)
  }
  const quadrant = Math.trunc(fdi / 10)
  const units = fdi % 10
  if (quadrant < 1 || quadrant > 8 || units < 1 || units > 8) {
    throw new RangeError(`not a valid FDI tooth number: ${fdi}`)
  }
  return quadrant as 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8
}

/** Which arch a tooth belongs to (quadrants 1/2/5/6 upper, 3/4/7/8 lower). */
export function archOf(fdi: number): ArchSide {
  const quadrant = quadrantOf(fdi)
  return quadrant === 1 || quadrant === 2 || quadrant === 5 || quadrant === 6
    ? 'upper'
    : 'lower'
}

/** Size category from the FDI units digit (1/2 incisor … 6–8 molar). */
export function categoryOf(fdi: number): ToothSizeCategory {
  const units = fdi % 10
  if (units <= 2) return 'incisor'
  if (units === 3) return 'canine'
  if (units <= 5) return 'premolar'
  return 'molar'
}

/** True for deciduous (baby) tooth numbers — FDI quadrants 5–8. */
export function isDeciduousToothNumber(fdi: number): boolean {
  return quadrantOf(fdi) >= 5
}

/**
 * Lay one arch out along a parabolic curve.
 *
 * ``order`` lists FDI numbers from one side's third molar to the
 * other's (the viewer's default orders follow the host odontogram
 * conventions). Duplicate or cross-arch numbers simply produce
 * placements the caller may ignore.
 */
export function layoutArch(order: readonly number[], side: ArchSide): Map<number, ToothPlacement> {
  const placements = new Map<number, ToothPlacement>()
  const count = order.length
  order.forEach((fdi, index) => {
    // t ∈ [-1, 1] across the arch; a single tooth sits at the midline.
    const t = count > 1 ? (index / (count - 1)) * 2 - 1 : 0
    const shrink = isDeciduousToothNumber(fdi) ? DECIDUOUS_SCALE : 1
    const base = TOOTH_SCALE[categoryOf(fdi)]
    placements.set(fdi, {
      x: t * ARCH_HALF_WIDTH * shrink,
      y: (side === 'upper' ? 1 : -1) * (ARCH_GAP / 2),
      z: -ARCH_DEPTH * t * t,
      rotY: MOLAR_YAW * t,
      scale: { x: base.x * shrink, y: base.y * shrink, z: base.z * shrink }
    })
  })
  return placements
}

/**
 * Colour token for a tooth condition, or null for healthy enamel.
 *
 * Non-healthy conditions pass through verbatim so the host treatment
 * palette (``odontogramConstants``) stays the single source of colour
 * truth — the 3D layer never invents clinical colours.
 */
export function conditionColorToken(condition: string): string | null {
  return condition === '' || condition === 'healthy' ? null : condition
}

/** Teeth the viewer should draw: present and not hidden by view state. */
export function renderableTeeth(teeth: readonly DentalToothView[]): DentalToothView[] {
  return teeth.filter(tooth => tooth.present && tooth.visible)
}
