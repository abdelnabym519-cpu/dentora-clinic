// Nuxt layer for the `booking` module.
//
// Provides the public patient booking page and reusable booking components.
// i18n locales will be added after the public flow UI is created.

export default defineNuxtConfig({
  components: [
    { path: './components', pathPrefix: false }
  ]
})
