/**
 * Shared state for treatment-catalog selectors (single + multi).
 * Loads popular items on demand and runs a debounce-free search over the
 * catalog API. Owns the loading flags so both selectors can share UX.
 */
import type { TreatmentCatalogItem, ApiResponse } from '~/types'
import { errorMessage } from '~/utils/error'

export function useTreatmentCatalogSearch() {
  const api = useApi()
  const { searchItems, getItemName, formatPrice } = useCatalog()
  const { t, locale } = useI18n()

  const popularItems = ref<TreatmentCatalogItem[]>([])
  const searchResults = ref<TreatmentCatalogItem[]>([])
  const isSearching = ref(false)
  const isLoadingPopular = ref(false)
  /**
   * The "common treatments" suggestions are optional decoration mounted
   * inside appointment / budget / plan modals: a failure is reported by the
   * selector's own empty-label, never as a toast over that workflow.
   */
  const loadError = ref('')
  /**
   * A failed search must not read as "no matches" — that sends the user
   * hunting for a treatment that exists.
   */
  const searchError = ref('')

  async function loadPopularItems() {
    isLoadingPopular.value = true
    try {
      const response = await api.get<ApiResponse<TreatmentCatalogItem[]>>(
        '/api/v1/catalog/items/popular?limit=8',
        { silent: true }
      )
      popularItems.value = response.data
      loadError.value = ''
    } catch (e: unknown) {
      popularItems.value = []
      loadError.value = errorMessage(e, t('selector.loadFailed'))
    } finally {
      isLoadingPopular.value = false
    }
  }

  async function search(query: string) {
    if (!query || query.length < 2) {
      searchResults.value = []
      return
    }
    isSearching.value = true
    searchError.value = ''
    try {
      const results = await searchItems(query, 12, { silent: true })
      searchResults.value = results as unknown as TreatmentCatalogItem[]
    } catch (e: unknown) {
      searchResults.value = []
      searchError.value = errorMessage(e, t('selector.searchFailed'))
    } finally {
      isSearching.value = false
    }
  }

  function getCategoryName(item: TreatmentCatalogItem): string {
    if (item.category && item.category.names) {
      return item.category.names[locale.value] || item.category.names.es || ''
    }
    return ''
  }

  return {
    popularItems,
    searchResults,
    isSearching,
    isLoadingPopular,
    loadError,
    searchError,
    loadPopularItems,
    search,
    getItemName,
    formatPrice,
    getCategoryName
  }
}
