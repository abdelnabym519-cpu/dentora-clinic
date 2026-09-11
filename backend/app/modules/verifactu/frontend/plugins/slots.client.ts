import { defineAsyncComponent } from 'vue'
import { registerSlot } from '~~/app/composables/useModuleSlots'
import { PERMISSIONS } from '~~/app/config/permissions'

interface InvoiceCtx {
  invoice?: { compliance_data?: Record<string, unknown> | null } | null
  clinic?: { country?: string | null, settings?: { country?: string | null } | null } | null
}

export default defineNuxtPlugin(() => {
  registerSlot('settings.sections', {
    id: 'verifactu.settings.cards',
    component: defineAsyncComponent(() => import('../components/SettingsCardsSlot.vue')),
    // Settings-scope read: the card links into /settings/verifactu, whose
    // pages all answer 403 without it. Gating here keeps the entry out of
    // the settings IA instead of offering a door that slams shut.
    permission: PERMISSIONS.verifactu.settingsRead,
    order: 60,
    category: 'billing',
    labelKey: 'verifactu.settingsCards.title',
    descriptionKey: 'verifactu.settingsCards.description',
    searchKeywords: ['verifactu', 'aeat', 'impuesto', 'factura electronica', 'factura electrónica', 'rd 1007/2023']
  })

  // Renders the Verifactu state panel inside the invoice detail page
  // for ES clinics (or whenever the invoice already carries an ES
  // compliance block — e.g. issued before country setting was set).
  // Billing knows nothing about this entry.
  //
  // Gated on the records-scope read: the panel reconciles its state with
  // GET /verifactu/records on mount, and every action it offers belongs
  // to a Verifactu grant. Users without one keep the read-only AEAT badge
  // (which is derived from the invoice payload) instead of a panel that
  // can only answer 403.
  registerSlot('invoice.detail.compliance', {
    id: 'verifactu.invoice.detail.compliance',
    component: defineAsyncComponent(() => import('../components/verifactu/InvoiceVerifactuSlot.vue')),
    permission: PERMISSIONS.verifactu.recordsRead,
    order: 10,
    condition: (raw) => {
      const ctx = (raw ?? {}) as InvoiceCtx
      const country = ctx.clinic?.country ?? ctx.clinic?.settings?.country ?? null
      const hasES = !!(ctx.invoice?.compliance_data as Record<string, unknown> | undefined)?.ES
      return country === 'ES' || hasES
    }
  })

  // Global banner. The layout renders <ModuleSlot name="app.banners">
  // unconditionally; the banner component self-fetches /health and
  // hides itself when rejected_count is zero. Fast no-op for clinics
  // that don't use Verifactu.
  //
  // Permission-gated at the slot level with the grant the endpoint
  // actually requires (GET /verifactu/health → verifactu.settings.read).
  // Without it the banner mounted for every role holding *any* Verifactu
  // grant (dentists and receptionists hold records.read), polled an
  // endpoint they are not authorized for, and the shared 403 handling
  // turned that into an "Access denied" toast on whatever unrelated
  // screen the user was on. The component repeats the check and probes
  // silently — see RejectedGlobalBanner.vue.
  registerSlot('app.banners', {
    id: 'verifactu.app.banners.rejected',
    component: defineAsyncComponent(
      () => import('../components/verifactu/RejectedGlobalBanner.vue')
    ),
    permission: PERMISSIONS.verifactu.settingsRead,
    order: 10
  })

  // Compact AEAT chip in each invoice list row + invoice detail header.
  // Same component (ComplianceBadge) — the slot ctx carries the
  // invoice. Hidden automatically when the row has no compliance_data
  // for ES (badge composable returns null).
  const isESInvoiceCtx = (raw: unknown) => {
    const ctx = (raw ?? {}) as InvoiceCtx
    const country = ctx.clinic?.country ?? ctx.clinic?.settings?.country ?? null
    const hasES = !!(ctx.invoice?.compliance_data as Record<string, unknown> | undefined)?.ES
    return country === 'ES' || hasES
  }

  registerSlot('invoice.list.row.meta', {
    id: 'verifactu.invoice.list.row.meta',
    component: defineAsyncComponent(
      () => import('../components/verifactu/ComplianceBadge.vue')
    ),
    order: 10,
    condition: isESInvoiceCtx
  })

  registerSlot('invoice.detail.header.meta', {
    id: 'verifactu.invoice.detail.header.meta',
    component: defineAsyncComponent(
      () => import('../components/verifactu/ComplianceBadge.vue')
    ),
    order: 10,
    condition: isESInvoiceCtx
  })

  // Toolbar filter on the invoice list. Multi-select severity +
  // "Solo problemas" shortcut. Mounted only for ES clinics.
  registerSlot('invoice.list.toolbar.filters', {
    id: 'verifactu.invoice.list.toolbar.filters',
    component: defineAsyncComponent(
      () => import('../components/verifactu/ComplianceFilter.vue')
    ),
    order: 10,
    condition: (raw) => {
      const ctx = (raw ?? {}) as { clinic?: { country?: string | null, settings?: { country?: string | null } | null } }
      const country = ctx.clinic?.country ?? ctx.clinic?.settings?.country ?? null
      return country === 'ES'
    }
  })
})
