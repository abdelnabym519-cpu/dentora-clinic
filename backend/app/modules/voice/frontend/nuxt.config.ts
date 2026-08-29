export default defineNuxtConfig({
  components: [{ path: './components', pathPrefix: false }],
  i18n: {
    locales: [
      { code: 'en', file: 'en.json' },
      { code: 'es', file: 'es.json' },
      { code: 'fr', file: 'fr.json' },
      { code: 'pt', file: 'pt.json' },
      { code: 'ar', file: 'ar.json' }
    ],
    // Nuxt i18n resolves layer langDir from the Nuxt 4 `i18n/` base.
    // Voice keeps its locale assets alongside the removable layer.
    langDir: '../locales'
  }
})
