import { h, defineComponent, type Component } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mountSuspended } from '@nuxt/test-utils/runtime'
import {
  useDental3DSegmentation,
  type SegmentationAnalysisPayload
} from '../../module_layers/dental_3d/frontend/composables/useDental3DScene'

function payload(
  overrides: Partial<SegmentationAnalysisPayload> = {}
): SegmentationAnalysisPayload {
  return {
    id: 'a-1',
    patient_id: 'p-1',
    provider: 'arch-partition',
    method: 'deterministic-arch-partition-v0',
    is_clinical: false,
    requires_review: true,
    teeth: [{ tooth_number: 11, status: 'segmented', confidence: 0.9 }],
    performed_at: '2026-08-23T12:00:00Z',
    created_at: '2026-08-23T12:00:01Z',
    review_status: 'pending',
    reviewed_at: null,
    review_note: null,
    segmented_count: 1,
    uncertain_count: 0,
    missing_count: 0,
    disclaimer: 'non-clinical decision support',
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

type Seg = ReturnType<typeof useDental3DSegmentation>

/** Mount a passthrough component so the composable runs in setup context. */
async function withSegmentation(): Promise<Seg> {
  let seg!: Seg
  const Passthrough: Component = defineComponent({
    setup() {
      seg = useDental3DSegmentation(() => 'p-1')
      return () => h('div')
    }
  })
  await mountSuspended(Passthrough)
  return seg
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('useDental3DSegmentation — load', () => {
  it('loads the latest analysis', async () => {
    stubApi({ '/segmentation': { data: payload() } })
    const seg = await withSegmentation()
    await seg.load()
    expect(seg.analysis.value?.id).toBe('a-1')
    expect(seg.running.value).toBe(false)
  })

  it('404 (never run) degrades to null analysis', async () => {
    stubApi({ '/other': { data: null } })
    const seg = await withSegmentation()
    await seg.load()
    expect(seg.analysis.value).toBeNull()
  })
})

describe('useDental3DSegmentation — run', () => {
  it('runs the analysis server-side and stores the result', async () => {
    stubApi({ '/segmentation': { data: payload({ id: 'a-2' }) } })
    const seg = await withSegmentation()
    const ok = await seg.run()
    expect(ok).toBe(true)
    expect(seg.analysis.value?.id).toBe('a-2')
    expect(seg.runFailed.value).toBe(false)
  })

  it('flags failure without breaking the card', async () => {
    stubApi({ '/other': { data: null } })
    const seg = await withSegmentation()
    const ok = await seg.run()
    expect(ok).toBe(false)
    expect(seg.runFailed.value).toBe(true)
    expect(seg.running.value).toBe(false)
  })
})

describe('useDental3DSegmentation — review', () => {
  it('records the dentist decision on the loaded analysis', async () => {
    stubApi({
      '/review': { data: payload({ review_status: 'accepted', review_note: 'checked' }) }
    })
    const seg = await withSegmentation()
    seg.analysis.value = payload()
    const ok = await seg.review('accepted', 'checked')
    expect(ok).toBe(true)
    expect(seg.analysis.value?.review_status).toBe('accepted')
    expect(seg.analysis.value?.review_note).toBe('checked')
  })

  it('refuses to review without a loaded analysis', async () => {
    stubApi({ '/review': { data: payload() } })
    const seg = await withSegmentation()
    const ok = await seg.review('accepted')
    expect(ok).toBe(false)
  })
})
