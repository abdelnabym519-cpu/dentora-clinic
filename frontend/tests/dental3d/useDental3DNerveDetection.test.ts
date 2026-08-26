import { h, defineComponent, type Component } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mountSuspended } from '@nuxt/test-utils/runtime'
import {
  useDental3DNerveDetection,
  type NerveAnalysisPayload
} from '../../module_layers/dental_3d/frontend/composables/useDental3DScene'

function payload(
  overrides: Partial<NerveAnalysisPayload> = {}
): NerveAnalysisPayload {
  return {
    id: 'n-1',
    patient_id: 'p-1',
    provider: 'canonical-mandible',
    method: 'canonical-mandible-model-v0',
    is_clinical: false,
    requires_review: true,
    pathways: [
      {
        side: 'left',
        region: 'mandibular_canal',
        source: 'canonical_demo_model',
        status: 'uncertain',
        confidence: 0.6,
        points: [
          { x: 2.65, y: -0.98, z: -1.85 },
          { x: 2.3, y: -0.84, z: -1.52 }
        ]
      }
    ],
    proximities: [
      {
        tooth_number: 38,
        side: 'left',
        distance_mm: 1.53,
        closest_point_index: 1,
        warning: 'near',
        confidence: 0.6
      }
    ],
    performed_at: '2026-08-24T12:00:00Z',
    created_at: '2026-08-24T12:00:01Z',
    review_status: 'pending',
    reviewed_at: null,
    review_note: null,
    disclaimer: 'AI-assisted / simulated nerve detection',
    ...overrides
  }
}

/** Stub $fetch for the API paths the composable touches. */
function stubApi(responses: Record<string, unknown>): void {
  vi.stubGlobal(
    '$fetch',
    vi.fn(async (url: string) => {
      for (const [prefix, value] of Object.entries(responses)) {
        if (url.includes(prefix)) return value
      }
      throw Object.assign(new Error('not found'), {
        statusCode: 404,
        status: 404,
        response: { status: 404, _data: { message: 'not found' } }
      })
    })
  )
}

type Nerve = ReturnType<typeof useDental3DNerveDetection>

/** Mount a passthrough component so the composable runs in setup context. */
async function withNerve(): Promise<Nerve> {
  let nerve!: Nerve
  const Passthrough: Component = defineComponent({
    setup() {
      nerve = useDental3DNerveDetection(() => 'p-1')
      return () => h('div')
    }
  })
  await mountSuspended(Passthrough)
  return nerve
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('useDental3DNerveDetection — load', () => {
  it('loads the latest analysis', async () => {
    stubApi({ '/nerve-detection': { data: payload() } })
    const nerve = await withNerve()
    await nerve.load()
    expect(nerve.analysis.value?.id).toBe('n-1')
    expect(nerve.running.value).toBe(false)
    expect(nerve.runFailed.value).toBe(false)
  })

  it('404 (never run) degrades to null analysis', async () => {
    stubApi({ '/nothing': { data: null } })
    const nerve = await withNerve()
    await nerve.load()
    expect(nerve.analysis.value).toBeNull()
  })
})

describe('useDental3DNerveDetection — run', () => {
  it('runs the analysis server-side and stores the result', async () => {
    stubApi({ '/nerve-detection': { data: payload({ id: 'n-2' }) } })
    const nerve = await withNerve()
    const ok = await nerve.run()
    expect(ok).toBe(true)
    expect(nerve.analysis.value?.id).toBe('n-2')
    expect(nerve.runFailed.value).toBe(false)
  })

  it('flags failure without breaking the card', async () => {
    stubApi({ '/nothing': { data: null } })
    const nerve = await withNerve()
    const ok = await nerve.run()
    expect(ok).toBe(false)
    expect(nerve.runFailed.value).toBe(true)
    expect(nerve.running.value).toBe(false)
  })
})

describe('useDental3DNerveDetection — review', () => {
  it('records the dentist decision on the loaded analysis', async () => {
    stubApi({
      '/review': { data: payload({ review_status: 'accepted', review_note: 'checked' }) }
    })
    const nerve = await withNerve()
    nerve.analysis.value = payload()
    const ok = await nerve.review('accepted', 'checked the radiograph')
    expect(ok).toBe(true)
    expect(nerve.analysis.value?.review_status).toBe('accepted')
    expect(nerve.analysis.value?.review_note).toBe('checked')
  })

  it('refuses to review without a loaded analysis', async () => {
    stubApi({ '/review': { data: payload() } })
    const nerve = await withNerve()
    const ok = await nerve.review('rejected')
    expect(ok).toBe(false)
  })
})
