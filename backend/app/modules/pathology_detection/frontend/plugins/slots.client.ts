import { defineAsyncComponent } from 'vue'
import { registerSlot } from '~~/app/composables/useModuleSlots'

/**
 * Slot registrations for the `pathology_detection` module.
 *
 * Hosts (`patients`) expose stable slot names and never import this
 * module — the registry is the only contract.
 */
export default defineNuxtPlugin(() => {
  // Sub-tab inside the Diagnosis mode (after odontogram at order 0 and
  // periodontogram at order 20).
  registerSlot('patient.diagnosis.subtabs', {
    id: 'pathology_detection',
    component: defineAsyncComponent(
      () => import('../components/PathologyDetectionView.vue')
    ),
    order: 30,
    permission: 'pathology_detection.read',
    labelKey: 'pathology_detection.tab.label'
  })
})
