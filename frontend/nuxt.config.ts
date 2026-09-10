// https://nuxt.com/docs/api/configuration/nuxt-config
import { resolve } from 'node:path'
import { loadModuleLayers } from './module-layers.mjs'

/**
 * Load Nuxt Layer directories from `modules.json`.
 *
 * The backend writes this file whenever a module with a declared
 * `manifest.frontend.layer_path` is installed. Every entry is validated
 * and (when the `/module_layers` mount is absent, e.g. a plain Windows
 * checkout or the image build stage) mapped onto the real module source
 * in `backend/app/modules`; entries that cannot be resolved are reported
 * and skipped instead of crashing the build with ENOTDIR/ENOENT.
 * When the file is absent (fresh checkout, no community modules yet),
 * the layer list is empty.
 */
const modulesJsonPath = resolve(__dirname, 'modules.json')
const { layers: moduleLayers } = loadModuleLayers({ modulesJsonPath, warn: console.warn })

export default defineNuxtConfig({

  extends: moduleLayers,

  modules: [
    '@nuxt/eslint',
    '@nuxt/ui',
    '@nuxtjs/i18n',
    '@tresjs/nuxt'
  ],

  components: [
    {
      path: '~/components',
      pathPrefix: false
    }
  ],

  devtools: {
    enabled: true
  },
  app: {
    head: {
      title: 'Dentora',
      link: [
        { rel: 'icon', type: 'image/svg+xml', href: '/favicon.svg' }
      ]
    }
  },

  css: ['~/assets/css/main.css'],

  colorMode: {
    preference: 'light',
    fallback: 'light'
  },

  runtimeConfig: {
    apiBaseUrlServer: process.env.API_BASE_URL_SERVER || 'http://backend:8000',
    public: {
      apiBaseUrl: process.env.API_BASE_URL || 'http://localhost:8000',
      demoMode: process.env.NUXT_PUBLIC_DEMO_MODE === 'true',
      trialMode: process.env.NUXT_PUBLIC_TRIAL_MODE === 'true',
      trialStartedAt: process.env.NUXT_PUBLIC_TRIAL_STARTED_AT || '',
      trialDays: Number(process.env.NUXT_PUBLIC_TRIAL_DAYS || '3'),
      docsUrl: process.env.NUXT_PUBLIC_DOCS_URL || 'https://docs.dentora.example'
    }
  },
  srcDir: 'app',
  watch: [modulesJsonPath],
  compatibilityDate: '2025-01-15',

  vite: {
    worker: {
      format: 'es'
    },
    optimizeDeps: {
      include: [
        'nprogress',
        '@vueuse/core',
        '@vue/devtools-core',
        '@vue/devtools-kit',
        'marked',
        'isomorphic-dompurify',
        'vue-draggable-plus',
        'three',
        'three/addons/controls/OrbitControls.js',
        'three/addons/loaders/OBJLoader.js',
        'three/addons/loaders/PLYLoader.js',
        'three/addons/loaders/STLLoader.js',
        '@tresjs/core',
        'three-mesh-bvh',
        '@cornerstonejs/core',
        '@cornerstonejs/tools',
        '@cornerstonejs/dicom-image-loader'
      ]
    }
  },

  eslint: {
    config: {
      stylistic: {
        commaDangle: 'never',
        braceStyle: '1tbs'
      }
    }
  },

  i18n: {
    locales: [
      { code: 'en', name: 'English', file: 'en.json' },
      { code: 'es', name: 'Español', file: 'es.json' },
      { code: 'fr', name: 'Français', file: 'fr.json' },
      { code: 'pt', name: 'Português', file: 'pt.json' },
      { code: 'ar', name: 'العربية', file: 'ar.json' }
    ],
    defaultLocale: process.env.E2E_LOCALE === 'en' ? 'en' : 'ar',
    langDir: 'locales',
    strategy: 'no_prefix',
    detectBrowserLanguage: false
  },

  icon: {
    clientBundle: {
      scan: true,
      sizeLimitKb: 512
    }
  }
})
