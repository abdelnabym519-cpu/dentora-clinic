import { describe, expect, it } from 'vitest'
import {
  archOf,
  categoryOf,
  conditionColorToken,
  isDeciduousToothNumber,
  layoutArch,
  quadrantOf,
  renderableTeeth
} from '../../module_layers/dental_3d/frontend/lib/dentalArch'

const UPPER_ORDER = [18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28]
const LOWER_ORDER = [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38]

describe('dentalArch — FDI helpers', () => {
  it('maps quadrants to arches (permanent + deciduous)', () => {
    expect(archOf(16)).toBe('upper')
    expect(archOf(25)).toBe('upper')
    expect(archOf(34)).toBe('lower')
    expect(archOf(47)).toBe('lower')
    // Deciduous: 5x/6x upper, 7x/8x lower.
    expect(archOf(55)).toBe('upper')
    expect(archOf(66)).toBe('upper')
    expect(archOf(74)).toBe('lower')
    expect(archOf(83)).toBe('lower')
  })

  it('derives size category from the FDI units digit', () => {
    expect(categoryOf(11)).toBe('incisor')
    expect(categoryOf(12)).toBe('incisor')
    expect(categoryOf(13)).toBe('canine')
    expect(categoryOf(14)).toBe('premolar')
    expect(categoryOf(15)).toBe('premolar')
    expect(categoryOf(16)).toBe('molar')
    expect(categoryOf(18)).toBe('molar')
  })

  it('detects deciduous numbers', () => {
    expect(isDeciduousToothNumber(75)).toBe(true)
    expect(isDeciduousToothNumber(16)).toBe(false)
  })

  it('rejects invalid FDI numbers', () => {
    expect(() => quadrantOf(9)).toThrow(RangeError)
    expect(() => quadrantOf(99)).toThrow(RangeError)
  })
})

describe('dentalArch — arch layout', () => {
  it('places all 16 teeth of an arch with mirrored midline', () => {
    const upper = layoutArch(UPPER_ORDER, 'upper')
    expect(upper.size).toBe(16)

    // Patient's right (Q1) renders on the viewer's LEFT (negative x)…
    expect(upper.get(18)!.x).toBeLessThan(0)
    // …and the patient's left (Q2) on the viewer's RIGHT.
    expect(upper.get(28)!.x).toBeGreaterThan(0)
    // Central incisors hug the midline symmetrically.
    expect(upper.get(11)!.x).toBeCloseTo(-upper.get(21)!.x, 5)
  })

  it('curves molars back from the camera along a parabola', () => {
    const upper = layoutArch(UPPER_ORDER, 'upper')
    // Central incisors (11/21) flank the midline: index 7 and 8 of 16,
    // so they sit essentially at the front (z ≈ 0, not exactly 0).
    const leftCentral = upper.get(11)!
    const rightCentral = upper.get(21)!
    const molar = upper.get(18)!
    expect(leftCentral.z).toBeCloseTo(0, 1)
    expect(rightCentral.z).toBeCloseTo(0, 1)
    expect(molar.z).toBeLessThan(0)
    // Parabolic: the molar sits deeper than the canine.
    expect(molar.z).toBeLessThan(upper.get(13)!.z)
  })

  it('stacks upper above lower and orients teeth outward', () => {
    const upper = layoutArch(UPPER_ORDER, 'upper')
    const lower = layoutArch(LOWER_ORDER, 'lower')
    expect(upper.get(11)!.y).toBeGreaterThan(0)
    expect(lower.get(41)!.y).toBeLessThan(0)
    // Molars yaw to face outward; centrals face the camera. Central
    // incisors sit adjacent to the midline (t = ±1/15), so rotY ≈ 0
    // but not exactly 0 in a 16-tooth arch.
    expect(upper.get(11)!.rotY).toBeCloseTo(0, 1)
    expect(Math.abs(upper.get(18)!.rotY)).toBeGreaterThan(0)
    expect(upper.get(18)!.rotY).toBeLessThan(0) // left side rotates outward-left
    expect(upper.get(28)!.rotY).toBeGreaterThan(0)
  })

  it('scales molars wider than incisors and deciduous teeth smaller', () => {
    const upper = layoutArch(UPPER_ORDER, 'upper')
    expect(upper.get(16)!.scale.x).toBeGreaterThan(upper.get(11)!.scale.x)

    const deciduous = layoutArch([55, 54, 53, 52, 51, 61, 62, 63, 64, 65], 'upper')
    const permanent = layoutArch(UPPER_ORDER, 'upper')
    expect(deciduous.get(55)!.scale.x).toBeLessThan(permanent.get(16)!.scale.x)
  })

  it('handles a single-tooth arch without dividing by zero', () => {
    const single = layoutArch([11], 'upper')
    expect(single.get(11)!.x).toBe(0)
  })
})

describe('dentalArch — colour tokens + renderability', () => {
  it('healthy maps to the enamel token (null)', () => {
    expect(conditionColorToken('healthy')).toBeNull()
    expect(conditionColorToken('')).toBeNull()
  })

  it('conditions pass through for the host treatment palette', () => {
    expect(conditionColorToken('caries')).toBe('caries')
    expect(conditionColorToken('implant')).toBe('implant')
  })

  it('filters to present + visible teeth', () => {
    const teeth = [
      { tooth_number: 11, present: true, condition: 'healthy', color: null, visible: true },
      { tooth_number: 16, present: true, condition: 'caries', color: null, visible: false },
      { tooth_number: 46, present: false, condition: 'missing', color: null, visible: true }
    ]
    expect(renderableTeeth(teeth).map(t => t.tooth_number)).toEqual([11])
  })
})
