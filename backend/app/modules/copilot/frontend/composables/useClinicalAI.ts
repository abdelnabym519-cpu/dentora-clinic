/**
 * Patient-scoped clinical AI features (case summary, clinical report,
 * second review, treatment suggestions, case intelligence).
 *
 * Each call hits the real backend endpoint, which runs the full chain
 * (RBAC -> scoped context -> redaction -> LLM provider -> structured
 * validation). There is NO fake/local generation: an AI error is
 * surfaced to the user as an explicit "AI unavailable / error" state.
 */
export type ClinicalFeature
  = | 'case-summary'
    | 'report'
    | 'second-review'
    | 'treatment-suggestions'
    | 'case-intelligence'

export type FeatureStatus = 'idle' | 'loading' | 'success' | 'error'

export interface ClinicalAIResult {
  generated_by?: 'ai'
  model?: string
  disclaimer?: string
  insufficient_information?: boolean
  [key: string]: unknown
}

const ENDPOINTS: Record<ClinicalFeature, string> = {
  'case-summary': '/api/v1/copilot/clinical/case-summary',
  'report': '/api/v1/copilot/clinical/report',
  'second-review': '/api/v1/copilot/clinical/second-review',
  'treatment-suggestions': '/api/v1/copilot/clinical/treatment-suggestions',
  'case-intelligence': '/api/v1/copilot/clinical/case-intelligence'
}

interface ApiEnvelope<T> {
  data?: T
  message?: string | null
  errors?: string[]
}

export function useClinicalAI() {
  const api = useApi()
  const { t } = useI18n()

  const statuses = reactive<Record<ClinicalFeature, FeatureStatus>>({
    'case-summary': 'idle',
    'report': 'idle',
    'second-review': 'idle',
    'treatment-suggestions': 'idle',
    'case-intelligence': 'idle'
  })

  const results = reactive<Record<ClinicalFeature, ClinicalAIResult | null>>({
    'case-summary': null,
    'report': null,
    'second-review': null,
    'treatment-suggestions': null,
    'case-intelligence': null
  })

  const errors = reactive<Record<ClinicalFeature, string | null>>({
    'case-summary': null,
    'report': null,
    'second-review': null,
    'treatment-suggestions': null,
    'case-intelligence': null
  })

  function _errorMessage(message: string | undefined): string {
    if (!message) return t('copilot.clinical.errorGeneric')
    // Backend prefixes messages with [CODE]; surface the human part.
    const match = message.match(/^\[[A-Z_]+\]\s*(.*)$/)
    return match ? match[1] : message
  }

  async function run(feature: ClinicalFeature, patientId: string): Promise<void> {
    if (!patientId) {
      errors[feature] = t('copilot.clinical.noPatient')
      statuses[feature] = 'error'
      return
    }
    statuses[feature] = 'loading'
    errors[feature] = null
    results[feature] = null
    try {
      const body = await api.$api<ApiEnvelope<ClinicalAIResult>>(ENDPOINTS[feature], {
        method: 'POST',
        body: { patient_id: patientId }
      })
      const data = body.data
      if (!data || data.generated_by !== 'ai') {
        // Never render a non-AI payload as an AI result (no fake success).
        throw new Error('invalid_ai_response')
      }
      results[feature] = data
      statuses[feature] = 'success'
    } catch (e: unknown) {
      const envelope = (e as { data?: ApiEnvelope<unknown> })?.data
      const raw = envelope?.message || (e as Error)?.message || ''
      const code
        = raw.includes('AI_UNAVAILABLE') || raw.includes('AI request failed')
          ? 'copilot.clinical.unavailable'
          : raw.includes('AI_INVALID_OUTPUT')
            ? 'copilot.clinical.invalid'
            : null
      errors[feature] = code
        ? t(code)
        : _errorMessage(envelope?.message) || t('copilot.clinical.errorGeneric')
      statuses[feature] = 'error'
    }
  }

  async function runAll(patientId: string): Promise<void> {
    await Promise.all((Object.keys(ENDPOINTS) as ClinicalFeature[]).map(f => run(f, patientId)))
  }

  return { statuses, results, errors, run, runAll }
}
