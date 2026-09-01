import { defineAsyncComponent } from 'vue'
import { registerSlot } from '~~/app/composables/useModuleSlots'

export default defineNuxtPlugin(() => {
  registerSlot('app.overlays', {
    id: 'voice.overlay',
    component: defineAsyncComponent(() => import('../components/VoiceMount.vue')),
    order: 20,
    permission: 'voice.use'
  })
})
