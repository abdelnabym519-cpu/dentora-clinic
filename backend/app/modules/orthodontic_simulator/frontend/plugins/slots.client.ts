import { defineAsyncComponent } from 'vue'
import { registerSlot } from '~~/app/composables/useModuleSlots'

/** Independently removable Orthodontic Simulator patient-summary registration. */
export default defineNuxtPlugin(() => {
  registerSlot('patient.summary.cards', {
    id: 'orthodontic_simulator.patient.summary.cards.simulator',
    component: defineAsyncComponent(
      () => import('../components/OrthodonticSimulatorCard.vue')
    ),
    order: 53,
    permission: 'orthodontic_simulator.read'
  })
})
