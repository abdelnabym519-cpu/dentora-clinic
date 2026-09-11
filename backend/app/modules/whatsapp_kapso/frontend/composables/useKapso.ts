import type { ApiResponse } from '~~/app/types'
import { errorMessage } from '~~/app/utils/error'

export interface KapsoSettings {
  phone_number_id: string | null
  business_account_id: string | null
  display_phone_number: string | null
  has_api_key: boolean
  has_webhook_secret: boolean
  is_active: boolean
  is_verified: boolean
  last_verified_at: string | null
  last_template_sync_at: string | null
}

export interface KapsoTemplate {
  name: string
  language: string
  status: string
  category: string | null
  synced_at: string | null
}

const BASE = '/api/v1/whatsapp_kapso'

export function useKapso() {
  const api = useApi()
  const { t } = useI18n()
  const settings = useState<KapsoSettings | null>('kapso:settings', () => null)
  const templates = useState<KapsoTemplate[]>('kapso:templates', () => [])
  const loading = ref(false)
  const saving = ref(false)
  const syncing = ref(false)
  /**
   * Set when the stored settings could not be read. The page renders this
   * inline with a Retry instead of the form: with `settings` null the form is
   * built from blanks, and one Save would then overwrite the clinic's phone
   * number and stored secrets with empty strings.
   */
  const error = ref<string | null>(null)

  async function fetchSettings() {
    loading.value = true
    error.value = null
    try {
      const res = await api.get<ApiResponse<KapsoSettings>>(`${BASE}/settings`, { silent: true })
      settings.value = res.data
    } catch (e) {
      // Was try/finally with no catch: the rejection escaped the page's bare
      // onMounted and the form rendered from blank defaults with a live Save.
      console.error('Error loading WhatsApp (Kapso) settings:', e)
      error.value = errorMessage(e, t('errors.loadFailed'))
      settings.value = null
    } finally {
      loading.value = false
    }
  }

  async function saveSettings(payload: Record<string, unknown>) {
    saving.value = true
    try {
      // Silent: onSave() reports this failure itself, with the server's reason.
      const res = await api.put<ApiResponse<KapsoSettings>>(`${BASE}/settings`, payload, { silent: true })
      settings.value = res.data
      return true
    } finally {
      saving.value = false
    }
  }

  async function syncTemplates() {
    syncing.value = true
    try {
      // Silent: onSync() reports this failure itself, with the server's reason.
      const res = await api.post<ApiResponse<KapsoTemplate[]>>(`${BASE}/templates/sync`, {}, { silent: true })
      templates.value = res.data ?? []
      return res.data
    } finally {
      syncing.value = false
    }
  }

  async function mapTemplate(notificationType: string, locale: string, templateName: string) {
    // Silent: onMap() reports this failure itself, with the server's reason.
    await api.post(`${BASE}/templates/map`, {
      notification_type: notificationType,
      locale,
      template_name: templateName
    }, { silent: true })
  }

  async function testConnection(toNumber: string, templateName: string, language = 'es') {
    // Silent: onTest() reports this failure itself, with the server's reason.
    const res = await api.post<ApiResponse<{ success: boolean, error: string | null }>>(
      `${BASE}/test`,
      { to_number: toNumber, template_name: templateName, language },
      { silent: true }
    )
    return res.data
  }

  return {
    settings,
    templates,
    loading,
    saving,
    syncing,
    error,
    fetchSettings,
    saveSettings,
    syncTemplates,
    mapTemplate,
    testConnection
  }
}
