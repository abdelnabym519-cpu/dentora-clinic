import { defineAsyncComponent } from 'vue'
import { registerSlot } from '~~/app/composables/useModuleSlots'

/**
 * Slot registrations for the `dental_3d` module.
 *
 * Hosts (`patients`) expose stable slot names and never import this
 * module. The registry is the only contract — the module stays
 * independently removable.
 */
export default defineNuxtPlugin(() => {
  registerSlot('patient.summary.cards', {
    id: 'dental_3d.patient.summary.cards.viewer',
    component: defineAsyncComponent(
      () => import('../components/Dental3DCard.vue')
    ),
    order: 50,
    permission: 'dental_3d.read'
  })

  registerSlot('patient.summary.cards', {
    id: 'dental_3d.patient.summary.cards.implant-planning',
    component: defineAsyncComponent(
      () => import('../components/ImplantPlanningCard.vue')
    ),
    order: 51,
    permission: 'dental_3d.read'
  })

  registerSlot('patient.summary.cards', {
    id: 'dental_3d.patient.summary.cards.risk-engine',
    component: defineAsyncComponent(
      () => import('../components/RiskEngineCard.vue')
    ),
    order: 52,
    permission: 'risk_engine.read'
  })
})
