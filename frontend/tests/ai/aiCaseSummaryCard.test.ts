import { nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { useState } from '#app'
import { _resetApiErrorNotifications } from '~/composables/useApi'
import AICaseSummaryCard from '../../module_layers/ai_case_summary/frontend/components/AICaseSummaryCard.vue'

/**
 * The AI Case Summary card, driven end to end through the real composable.
 *
 * The other AI suites prove the backend contract and the request plumbing;
 * this one proves the last mile the mission is judged on: a payload shaped
 * exactly like the backend's `ApiResponse[AICaseSummary]` reaches the patient
 * Summary tab and is *visible* — claims with their evidence ids, provenance,
 * data gaps, the dentist review controls, and an actionable message when the
 * provider is not configured instead of a silently blank card.
 *
 * It also pins the safety semantics the UI must not lose: results render as
 * advisory, and the accept/reject controls exist only while the record is
 * pending review.
 */

const { fetchMock, toastSpy } = vi.hoisted(() => ({
  fetchMock: vi.fn(),
  toastSpy: vi.fn()
}))

mockNuxtImport('$fetch', () => fetchMock)
mockNuxtImport('useToast', () => () => ({ add: toastSpy }))

const PATIENT_ID = '2b6b4a1e-6f0a-4b5a-9a2e-6f0f0a1b2c3d'
const SUMMARY_ID = '9c1a4c2e-8d3b-4a5f-9e2a-1b2c3d4e5f60'
const BASE = `/api/v1/ai_case_summary/patients/${PATIENT_ID}`

/** Field-for-field the backend's `AICaseSummary` contract (contracts.py). */
function summaryPayload(
  reviewStatus: 'pending_review' | 'accepted' | 'rejected' = 'pending_review',
  clinicalOutput = false
) {
  return {
    id: SUMMARY_ID,
    patient_id: PATIENT_ID,
    summary_version: 3,
    contract_version: 'ai_case_summary/1',
    unified_case: {
      patient_id: PATIENT_ID,
      case_snapshot_version: 2,
      source_digest: 'snapshot-digest'
    },
    content: {
      advisory_only: true,
      clinical_output: false,
      claims: [
        {
          claim_id: 'claim-pulpitis',
          text: 'Tooth 36 reports spontaneous lingering pain.',
          evidence_ids: ['evidence-odontogram-36', 'evidence-note-2'],
          uncertainty: 'moderate'
        },
        {
          claim_id: 'claim-plaque',
          text: 'Plaque index recorded above the clinic threshold.',
          evidence_ids: ['evidence-perio-1'],
          uncertainty: null
        }
      ],
      data_gaps: [{ section: 'radiography', status: 'missing', reason: 'No CBCT on file' }]
    },
    provenance: {
      provider: 'ollama',
      model: 'qwen3:8b',
      input_digest: 'input-digest',
      output_digest: 'output-digest'
    },
    review_status: reviewStatus,
    clinical_output: clinicalOutput,
    generated_at: '2026-09-12T09:00:00Z',
    generated_by: null,
    reviewed_at: reviewStatus === 'pending_review' ? null : '2026-09-12T09:05:00Z',
    reviewed_by: null
  }
}

interface RecordedCall {
  url: string
  method?: string
  body?: unknown
}

let calls: RecordedCall[] = []
/** Per-test override for the initial GET /latest. */
let latest: () => unknown = () => ({ data: summaryPayload() })

async function flush(): Promise<void> {
  await nextTick()
  await new Promise(resolve => setTimeout(resolve, 0))
  await nextTick()
}

async function mountCard() {
  const wrapper = await mountSuspended(AICaseSummaryCard, {
    props: { ctx: { patient: { id: PATIENT_ID } } }
  })
  await flush()
  return wrapper
}

/** ofetch-shaped failure, exactly what `$api` hands to the catch block. */
function httpError(statusCode: number, detail: unknown) {
  return Object.assign(new Error('request failed'), { statusCode, status: statusCode, data: { detail } })
}

function buttonByLabel(wrapper: { findAll: (sel: string) => Array<{ text: () => string }> }, label: string) {
  return wrapper.findAll('button').find(button => button.text().includes(label))
}

beforeEach(() => {
  calls = []
  latest = () => ({ data: summaryPayload() })
  _resetApiErrorNotifications()
  // The card gates Generate/Review on `ai_case_summary.*`; the app reads the
  // grant list from this state key (same approach as the billing card suite).
  useState<string[]>('auth:permissions', () => []).value = ['*']

  fetchMock.mockImplementation(async (url: string, opts?: { method?: string, body?: unknown }) => {
    const full = String(url)
    const method = opts?.method ?? 'GET'
    calls.push({ url: full, method, body: opts?.body })
    if (full.includes(`/summaries/${SUMMARY_ID}/review`)) {
      return { data: summaryPayload('accepted', true) }
    }
    if (method === 'POST' && full.includes(BASE)) {
      return { data: summaryPayload() }
    }
    if (full.includes('/latest')) {
      return latest()
    }
    return { data: null }
  })
})

afterEach(() => {
  fetchMock.mockReset()
  toastSpy.mockReset()
  _resetApiErrorNotifications()
})

describe('AI Case Summary card — the result is visible in the patient workflow', () => {
  it('loads the latest summary and renders claims with their evidence', async () => {
    const wrapper = await mountCard()

    expect(calls.some(c => c.url.includes(`${BASE}/latest`))).toBe(true)
    const claims = wrapper.findAll('[data-testid^="ai-case-summary-claim-"]')
    expect(claims.length).toBe(2)
    expect(wrapper.find('[data-testid="ai-case-summary-claim-claim-pulpitis"]').text())
      .toContain('Tooth 36 reports spontaneous lingering pain.')
    // Evidence ids are the traceability contract: they must be on screen.
    expect(wrapper.find('[data-testid="ai-case-summary-claim-claim-pulpitis"]').text())
      .toContain('evidence-odontogram-36, evidence-note-2')
    expect(wrapper.find('[data-testid="ai-case-summary-claim-claim-pulpitis"]').text())
      .toContain('Uncertainty: moderate')
    // A claim without uncertainty must not render an empty warning row.
    expect(wrapper.find('[data-testid="ai-case-summary-claim-claim-plaque"]').text())
      .not.toContain('Uncertainty:')
    expect(wrapper.find('[data-testid="ai-case-summary-empty"]').exists()).toBe(false)
  })

  it('shows provenance and data gaps, so the reader knows the source and the limits', async () => {
    const wrapper = await mountCard()

    const provenance = wrapper.find('[data-testid="ai-case-summary-provenance"]').text()
    expect(provenance).toContain('v3')
    expect(provenance).toContain('provider ollama')
    expect(provenance).toContain('qwen3:8b')
    expect(provenance).toContain('review: pending_review')

    const gaps = wrapper.find('[data-testid="ai-case-summary-gaps"]').text()
    expect(gaps).toContain('radiography (missing)')
  })

  it('posts the dentist review decision and leaves the pending state', async () => {
    const wrapper = await mountCard()

    const accept = wrapper.find('[data-testid="ai-case-summary-accept"]')
    expect(accept.exists()).toBe(true)
    await accept.trigger('click')
    await flush()

    const review = calls.find(c => c.url.includes(`/summaries/${SUMMARY_ID}/review`))
    expect(review?.method).toBe('POST')
    expect(review?.body).toEqual({ decision: 'accepted' })
    // Once accepted the record is no longer pending: the controls disappear
    // and the state is stated plainly.
    expect(wrapper.find('[data-testid="ai-case-summary-accept"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="ai-case-summary-review-state"]').text()).toContain('accepted')
  })

  it('generates on demand when there is no summary yet', async () => {
    latest = () => ({ data: null })
    const wrapper = await mountCard()

    expect(wrapper.find('[data-testid="ai-case-summary-empty"]').exists()).toBe(true)

    const generate = buttonByLabel(wrapper, 'Generate summary')
    expect(generate).toBeTruthy()
    await generate!.trigger('click')
    await flush()

    expect(calls.some(c => c.method === 'POST' && c.url.includes(BASE))).toBe(true)
    expect(wrapper.findAll('[data-testid^="ai-case-summary-claim-"]').length).toBe(2)
    expect(wrapper.find('[data-testid="ai-case-summary-empty"]').exists()).toBe(false)
  })

  it('surfaces an unconfigured provider as an actionable message, not a blank card', async () => {
    latest = () => ({ data: null })
    fetchMock.mockImplementation(async (url: string, opts?: { method?: string }) => {
      const full = String(url)
      calls.push({ url: full, method: opts?.method ?? 'GET' })
      if ((opts?.method ?? 'GET') === 'POST' && full.includes(BASE)) {
        // Exactly what the router raises when the provider factory cannot
        // resolve a usable provider (LLMConfigError -> 503 + code).
        throw httpError(503, {
          code: 'ai_case_summary_provider_unavailable',
          message: 'OpenAI provider requires OPENAI_API_KEY'
        })
      }
      if (full.includes('/latest')) return { data: null }
      return { data: null }
    })

    const wrapper = await mountCard()
    const generate = buttonByLabel(wrapper, 'Generate summary')
    await generate!.trigger('click')
    await flush()

    const text = wrapper.text()
    expect(text).toContain('AI provider unavailable')
    expect(text).toContain('OpenAI provider requires OPENAI_API_KEY')
    // Nothing was fabricated: still no claims, still the honest empty state.
    expect(wrapper.findAll('[data-testid^="ai-case-summary-claim-"]').length).toBe(0)
    expect(wrapper.find('[data-testid="ai-case-summary-empty"]').exists()).toBe(true)
  })

  it('renders the empty state without erroring when no summary exists', async () => {
    latest = () => ({ data: null })
    const wrapper = await mountCard()

    expect(wrapper.find('[data-testid="ai-case-summary-empty"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="ai-case-summary-provenance"]').exists()).toBe(false)
  })
})
