import type { Professional, PaginatedResponse } from '~/types'

const PROFESSIONAL_COLORS = [
  '#3B82F6', // blue
  '#10B981', // emerald
  '#8B5CF6', // violet
  '#F59E0B', // amber
  '#EF4444', // red
  '#EC4899', // pink
  '#06B6D4', // cyan
  '#84CC16' // lime
]

export function useProfessionals() {
  const api = useApi()
  const { t } = useI18n()

  const professionals = ref<Professional[]>([])
  const isLoading = ref(false)
  const error = ref<string | null>(null)

  const professionalColors = ref<Map<string, string>>(new Map())

  /**
   * @param options.silent Suppress the shared error toast. The professional
   * list is a cosmetic enrichment in several places (timeline author names,
   * doctor chips, agenda colour lanes) where the caller has no error surface
   * and falls back to the record's own text — a global toast there would be
   * attributed to whatever screen the user is actually on. Callers that own
   * an error UI (settings, reports, appointment modal) keep the default.
   */
  async function fetchProfessionals(options: { silent?: boolean } = {}): Promise<void> {
    isLoading.value = true
    error.value = null

    try {
      const response = await api.get<PaginatedResponse<Professional>>(
        '/api/v1/auth/professionals',
        { silent: options.silent === true }
      )
      professionals.value = response.data ?? []

      professionalColors.value = new Map()
      response.data.forEach((prof, index) => {
        const color = PROFESSIONAL_COLORS[index % PROFESSIONAL_COLORS.length]
        if (color) {
          professionalColors.value.set(prof.id, color)
        }
      })
    } catch (e) {
      error.value = t('professionals.toast.loadFailed')
      console.error('Failed to fetch professionals:', e)
    } finally {
      isLoading.value = false
    }
  }

  function getProfessionalById(id: string): Professional | undefined {
    return professionals.value.find(p => p.id === id)
  }

  function getProfessionalColor(id: string): string {
    return professionalColors.value.get(id) || '#6B7280' // Default gray
  }

  function getProfessionalInitials(professional: Professional): string {
    const first = professional.first_name.charAt(0).toUpperCase()
    const last = professional.last_name.charAt(0).toUpperCase()
    return `${first}${last}`
  }

  function getProfessionalFullName(professional: Professional): string {
    return `${professional.first_name} ${professional.last_name}`
  }

  return {
    professionals: readonly(professionals),
    isLoading: readonly(isLoading),
    error: readonly(error),
    fetchProfessionals,
    getProfessionalById,
    getProfessionalColor,
    getProfessionalInitials,
    getProfessionalFullName
  }
}
