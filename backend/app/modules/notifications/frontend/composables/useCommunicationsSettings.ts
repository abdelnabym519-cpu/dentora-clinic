import type { ApiResponse } from '~~/app/types'
import { errorDetail, errorMessage } from '~~/app/utils/error'

export interface CommunicationsSettings {
  language: string
}

export type CommunicationsSettingsPatch = Partial<CommunicationsSettings>

export function useCommunicationsSettings() {
  const api = useApi()
  const toast = useToast()
  const { t } = useI18n()

  const settings = ref<CommunicationsSettings | null>(null)
  const loading = ref(false)
  const saving = ref(false)
  /**
   * Set when the current settings could not be read: the page shows this
   * with a retry rather than a language picker initialised to a default the
   * clinic never chose.
   */
  const error = ref<string | null>(null)

  async function fetch() {
    loading.value = true
    error.value = null
    try {
      const response = await api.get<ApiResponse<CommunicationsSettings>>(
        '/api/v1/auth/clinic/settings/communications',
        { silent: true }
      )
      settings.value = response.data
    } catch (e) {
      // Was try/finally with no catch: unhandled rejection from
      // `onMounted(fetch)` and a form rendered from defaults.
      console.error('Error loading communications settings:', e)
      error.value = errorMessage(e, t('errors.loadFailed'))
    } finally {
      loading.value = false
    }
  }

  async function update(payload: CommunicationsSettingsPatch) {
    saving.value = true
    try {
      const response = await api.patch<ApiResponse<CommunicationsSettings>>(
        '/api/v1/auth/clinic/settings/communications',
        payload,
        { silent: true }
      )
      settings.value = response.data
      toast.add({
        title: t('notifications.communications.language.saved'),
        color: 'success'
      })
      return true
    } catch (e) {
      toast.add({ title: t('errors.updateFailed'), description: errorDetail(e), color: 'error' })
      return false
    } finally {
      saving.value = false
    }
  }

  return { settings, loading, saving, error, fetch, update }
}
