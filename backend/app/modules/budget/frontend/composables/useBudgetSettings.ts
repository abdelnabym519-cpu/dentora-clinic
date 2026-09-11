import { errorDetail, errorMessage } from '~~/app/utils/error'
import type { ApiResponse } from '~~/app/types'

export interface BudgetSettings {
  budget_expiry_days: number
  plan_auto_close_days_after_expiry: number
  budget_reminders_enabled: boolean
  budget_public_auth_disabled: boolean
}

export type BudgetSettingsPatch = Partial<BudgetSettings>

export function useBudgetSettings() {
  const api = useApi()
  const toast = useToast()
  const { t } = useI18n()

  const settings = ref<BudgetSettings | null>(null)
  const loading = ref(false)
  const saving = ref(false)
  /**
   * Set when the current settings could not be read. The pages render it
   * inline with a retry instead of showing the form: a form built from
   * defaults after a failed load invites the user to save a value that was
   * never the clinic's.
   */
  const error = ref<string | null>(null)

  async function fetch() {
    loading.value = true
    error.value = null
    try {
      const response = await api.get<ApiResponse<BudgetSettings>>(
        '/api/v1/auth/clinic/settings/budget',
        { silent: true }
      )
      settings.value = response.data
    } catch (e) {
      // Was try/finally with no catch: the rejection escaped `onMounted(fetch)`
      // as an unhandled promise rejection, and the shared toast was the only
      // signal while the page rendered the form with default values.
      console.error('Error loading budget settings:', e)
      error.value = errorMessage(e, t('errors.loadFailed'))
    } finally {
      loading.value = false
    }
  }

  async function update(payload: BudgetSettingsPatch) {
    saving.value = true
    try {
      const response = await api.patch<ApiResponse<BudgetSettings>>(
        '/api/v1/auth/clinic/settings/budget',
        payload,
        { silent: true }
      )
      settings.value = response.data
      toast.add({ title: t('budget.settings.saved'), color: 'success' })
      return true
    } catch (error) {
      console.error('Error saving budget settings:', error)
      toast.add({ title: t('errors.updateFailed'), description: errorDetail(error), color: 'error' })
      return false
    } finally {
      saving.value = false
    }
  }

  return {
    settings,
    loading,
    saving,
    error,
    fetch,
    update
  }
}
