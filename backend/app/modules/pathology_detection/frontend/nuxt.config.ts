// Nuxt layer for the `pathology_detection` module.
//
// Components live under ./components with no folder-prefix naming
// (matches host convention so <PathologyDetectionView /> resolves
// across layers).
export default defineNuxtConfig({
  components: [
    { path: './components', pathPrefix: false }
  ]
})
