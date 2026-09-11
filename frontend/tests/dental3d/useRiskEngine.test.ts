import { h, defineComponent, type Component } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { useRiskEngine, type RiskResultPayload } from '../../module_layers/dental_3d/frontend/composables/useRiskEngine'

/**
 * Clinical-AI action contract: CLICK → REQUEST → PROCESSING → RESULT.
 *
 * A blocked AI action must state its *actual* prerequisite ("Patient-space
 * reference frame is required", "provider unavailable"), never a generic
 * "could not be generated" and never an unrelated module's permission
 * error. The card renders `error` inline, so the ambient load and the
 * actions are silent at the transport layer.
 */

const { fetchMock, toastSpy } = vi.hoisted(() => ({
  fetchMock: vi.fn(),
  toastSpy: vi.fn()
}))

mockNuxtImport('$fetch', () => fetchMock)
mockNuxtImport('useToast', () => () => ({ add: toastSpy }))

function result(overrides: Partial<RiskResultPayload> = {}): RiskResultPayload {
  return {
    id: 'r-1',
    patient_id: 'p-1',
    result_version: 1,
    contract_version: '1.0',
    factors: [],
    evidence: [],
    risk_map: { status: 'unavailable', regions: [], advisory_only: true, synthetic_geometry: false },
    provenance: {
      case_snapshot_version: 1,
      case_snapshot_contract_version: '1.0',
      source_digest: 'd',
      input_digest: 'i',
      result_digest: 'r',
      engine_version: 'e',
      policy_version: 'p',
      generated_at: '2026-09-01T10:00:00Z',
      availability_state: 'available'
    },
    review_status: 'pending_review',
    advisory_only: true,
    requires_review: true,
    is_clinical: false,
    disclaimer: 'Decision support only',
    ...overrides
  }
}

function httpError(status: number, detail: unknown) {
  return Object.assign(new Error(typeof detail === 'string' ? detail : 'failed'), {
    statusCode: status,
    status,
    data: { detail }
  })
}

type Risk = ReturnType<typeof useRiskEngine>

async function withRisk(): Promise<Risk> {
  let risk!: Risk
  const Passthrough: Component = defineComponent({
    setup() {
      risk = useRiskEngine(() => 'p-1')
      return () => h('div')
    }
  })
  await mountSuspended(Passthrough)
  return risk
}

beforeEach(() => {
  fetchMock.mockReset()
  toastSpy.mockReset()
})

afterEach(() => {
  fetchMock.mockReset()
  toastSpy.mockReset()
})

describe('useRiskEngine — load (ambient, mounted with the patient summary)', () => {
  it('stores the latest result', async () => {
    const risk = await withRisk()
    fetchMock.mockResolvedValue({ data: result() })

    await risk.load()

    expect(risk.result.value?.id).toBe('r-1')
    expect(risk.loading.value).toBe(false)
    expect(risk.error.value).toBeNull()
  })

  it('treats 404 (never generated) as an empty state, not an error', async () => {
    const risk = await withRisk()
    fetchMock.mockRejectedValue(httpError(404, 'Risk result not found'))

    await risk.load()

    expect(risk.result.value).toBeNull()
    expect(risk.error.value).toBeNull()
    expect(toastSpy).not.toHaveBeenCalled()
  })

  it('never raises a global toast for the ambient probe', async () => {
    const risk = await withRisk()
    fetchMock.mockRejectedValue(httpError(403, 'Permission denied: risk_engine.read'))

    await risk.load()

    expect(toastSpy).not.toHaveBeenCalled()
    // …but the card still learns why it has nothing to show.
    expect(risk.error.value).toContain('risk_engine.read')
  })
})

describe('useRiskEngine — generate (explicit clinical action)', () => {
  it('stores the generated result and clears the error', async () => {
    const risk = await withRisk()
    fetchMock.mockResolvedValue({ data: result({ id: 'r-2' }) })

    const ok = await risk.generate()

    expect(ok).toBe(true)
    expect(risk.result.value?.id).toBe('r-2')
    expect(risk.mutating.value).toBe(false)
    expect(risk.error.value).toBeNull()
  })

  it('surfaces the readiness gate that actually blocked it', async () => {
    const risk = await withRisk()
    fetchMock.mockRejectedValue(
      httpError(409, {
        code: 'clinical_context_insufficient',
        message: 'Patient-space reference frame is required before risk evaluation.',
        missing_or_stale: ['dicom_patient_frame']
      })
    )

    const ok = await risk.generate()

    expect(ok).toBe(false)
    expect(risk.error.value).toContain('Patient-space reference frame is required')
    // The card owns the message: no second, generic global toast.
    expect(toastSpy).not.toHaveBeenCalled()
  })

  it('surfaces an unavailable AI provider instead of a generic failure', async () => {
    const risk = await withRisk()
    fetchMock.mockRejectedValue(
      httpError(503, {
        code: 'risk_engine_provider_unavailable',
        message: 'Ollama provider selected but OLLAMA_BASE_URL is not reachable'
      })
    )

    const ok = await risk.generate()

    expect(ok).toBe(false)
    expect(risk.error.value).toContain('OLLAMA_BASE_URL is not reachable')
  })

  it('names the missing permission when the role may not trigger AI', async () => {
    const risk = await withRisk()
    fetchMock.mockRejectedValue(httpError(403, 'Permission denied: risk_engine.generate'))

    const ok = await risk.generate()

    expect(ok).toBe(false)
    expect(risk.error.value).toContain('risk_engine.generate')
  })

  it('falls back to its own message when the failure carries no explanation', async () => {
    const risk = await withRisk()
    // A non-object rejection (thrown string, aborted worker, …) has no
    // server payload at all — the composable's own message is the floor.
    fetchMock.mockRejectedValue('unexpected-failure')

    const ok = await risk.generate()

    expect(ok).toBe(false)
    expect(risk.error.value).toBe('Risk evaluation could not be generated.')
  })
})

describe('useRiskEngine — review (dentist control)', () => {
  it('records the decision', async () => {
    const risk = await withRisk()
    fetchMock.mockResolvedValue({ data: result({ review_status: 'accepted' }) })
    risk.result.value = result()

    const ok = await risk.review('accepted')

    expect(ok).toBe(true)
    expect(risk.result.value?.review_status).toBe('accepted')
  })

  it('reports why a review was refused', async () => {
    const risk = await withRisk()
    fetchMock.mockRejectedValue(httpError(409, 'Only a pending result can be reviewed'))
    risk.result.value = result({ review_status: 'accepted' })

    const ok = await risk.review('rejected')

    expect(ok).toBe(false)
    expect(risk.error.value).toBe('Only a pending result can be reviewed')
  })

  it('does nothing without a loaded result', async () => {
    const risk = await withRisk()
    expect(await risk.review('accepted')).toBe(false)
    // No review request goes out for a result that was never loaded.
    expect(fetchMock.mock.calls.some(call => String(call[0]).includes('/risk_engine/'))).toBe(false)
  })
})
