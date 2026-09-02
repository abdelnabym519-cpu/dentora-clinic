// Nuxt layer for the `orthodontic_planning` module.
//
// Components live under ./components with no folder-prefix naming
// (matches host convention so <OrthodonticPlanningCard /> resolves
// across layers).
export default defineNuxtConfig({
  components: [
    { path: './components', pathPrefix: false }
  ]
})
