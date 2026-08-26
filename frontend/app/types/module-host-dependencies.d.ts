import type { PlannedTreatmentItem, TreatmentCatalogItem } from './index'

type CatalogSearchItem = Pick<
  TreatmentCatalogItem,
  'id' | 'internal_code' | 'names' | 'default_price' | 'is_active'
>

interface HostCatalogComposable {
  searchItems(query: string, limit?: number): Promise<CatalogSearchItem[]>
  getItemName(item: TreatmentCatalogItem, overrideLocale?: string): string
  formatPrice(price: number | undefined | null, currency?: string): string
}

interface HostTreatmentPlansComposable {
  fetchPatientPendingItems(patientId: string): Promise<PlannedTreatmentItem[]>
}

declare global {
  /** Runtime auto-import supplied by the catalog Nuxt layer. */
  function useCatalog(): HostCatalogComposable

  /** Runtime auto-import supplied by the treatment_plan Nuxt layer. */
  function useTreatmentPlans(): HostTreatmentPlansComposable
}

export {}
