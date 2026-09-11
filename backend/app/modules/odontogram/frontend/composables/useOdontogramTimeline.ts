/**
 * useOdontogramTimeline - Manages historical view of odontogram
 *
 * Handles:
 * - Fetching timeline dates
 * - Loading historical odontogram state at a specific date
 * - Switching between live and historical view
 */

import type {
  ApiResponse,
  OdontogramData,
  ToothRecord,
  Treatment
} from '~~/app/types'
import { errorMessage } from '~~/app/utils/error'
import { latestGuard } from '~~/app/utils/latestGuard'

export function useOdontogramTimeline() {
  const api = useApi()
  const toast = useToast()
  const { t } = useI18n()

  // ============================================================================
  // State
  // ============================================================================

  /** List of dates with changes */
  const timelineDates = ref<Array<{ date: string, change_count: number }>>([])

  /** Currently viewing date (null = live view) */
  const viewingDate = ref<string | null>(null)

  /** Historical teeth data */
  const historicalTeeth = ref<ToothRecord[]>([])

  /** Historical treatments data */
  const historicalTreatments = ref<Treatment[]>([])

  /** Loading state */
  const loading = ref(false)

  // ============================================================================
  // Computed
  // ============================================================================

  /** Whether viewing historical state */
  const isViewingHistory = computed(() => viewingDate.value !== null)

  // ============================================================================
  // API Methods
  // ============================================================================

  // Two separate slots, two separate guards: the list of history dates, and
  // the chart rendered *at* one of them. Clicking through dates quickly is the
  // normal way to read a history, and a late response must not leave the chart
  // showing one date's teeth under another date's label.
  const datesGuard = latestGuard()
  const historicalGuard = latestGuard()

  /** Fetch timeline dates for a patient */
  async function fetchTimeline(patientId: string): Promise<void> {
    const isLatest = datesGuard.begin()
    loading.value = true
    try {
      const response = await api.get<ApiResponse<{
        dates: Array<{ date: string, change_count: number }>
        total: number
      }>>(
        `/api/v1/odontogram/patients/${patientId}/odontogram/timeline`
      )
      if (!isLatest()) return
      timelineDates.value = response.data.dates ?? []
    } catch (err) {
      if (!isLatest()) return
      console.error('Error fetching timeline:', err)
      timelineDates.value = []
    } finally {
      if (isLatest()) loading.value = false
    }
  }

  /** Fetch odontogram state at a specific date */
  async function fetchOdontogramAtDate(patientId: string, date: string): Promise<void> {
    const isLatest = historicalGuard.begin()
    loading.value = true
    try {
      const response = await api.get<ApiResponse<OdontogramData>>(
        `/api/v1/odontogram/patients/${patientId}/odontogram/at?date=${date}`
      )
      if (!isLatest()) return
      historicalTeeth.value = response.data.teeth ?? []
      historicalTreatments.value = response.data.treatments ?? []
      viewingDate.value = date
    } catch (err) {
      if (!isLatest()) return
      console.error('Error fetching historical odontogram:', err)
      toast.add({
        title: t('common.error'),
        description: errorMessage(err, t('errors.loadFailed')),
        color: 'error'
      })
    } finally {
      if (isLatest()) loading.value = false
    }
  }

  /** Return to current/live view */
  function returnToCurrentView(): void {
    viewingDate.value = null
    historicalTeeth.value = []
    historicalTreatments.value = []
  }

  /** Reset all timeline state */
  function reset(): void {
    timelineDates.value = []
    viewingDate.value = null
    historicalTeeth.value = []
    historicalTreatments.value = []
  }

  // ============================================================================
  // Return
  // ============================================================================

  return {
    // State
    timelineDates,
    viewingDate,
    historicalTeeth,
    historicalTreatments,
    loading,

    // Computed
    isViewingHistory,

    // API
    fetchTimeline,
    fetchOdontogramAtDate,
    returnToCurrentView,
    reset
  }
}
