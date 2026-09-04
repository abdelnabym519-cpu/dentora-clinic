// Nuxt layer for the `pathology_detection` module.
//
// Components live under ./components with no folder-prefix naming
// (matches host convention so <PathologyDetectionView /> resolves
// across layers).
export default defineNuxtConfig({
  components: [
    { path: './components', pathPrefix: false }
  ],
  i18n: {
    locales: [
      { code: 'en', file: 'en.json' },
      { code: 'es', file: 'es.json' },
      { code: 'fr', file: 'fr.json' },
      { code: 'pt', file: 'pt.json' },
      { code: 'ar', file: 'ar.json' }
    ],
    langDir: 'locales'
  }
})
