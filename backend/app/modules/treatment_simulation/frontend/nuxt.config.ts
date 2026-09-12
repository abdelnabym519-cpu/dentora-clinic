// Nuxt layer for the `treatment_simulation` module.
// Components live under ./components with no folder-prefix naming so they
// auto-resolve across layers (host provides SummaryCard, useApi, usePermissions).
export default defineNuxtConfig({
  components: [{ path: './components', pathPrefix: false }]
})
