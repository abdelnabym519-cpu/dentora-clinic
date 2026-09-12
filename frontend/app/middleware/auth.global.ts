import { getTrialStatus } from '~/utils/trial'

const SETUP_PATH = '/setup'
const LICENSE_PATH = '/activate'
const TRIAL_EXPIRED_PATH = '/trial-expired'

interface CommercialLicenseStatus {
  enforced: boolean
  active: boolean
  features: string[]
}

let systemInitialized: boolean | null = null

/**
 * Both helpers take the API base URL instead of resolving it themselves.
 *
 * They are module-level functions invoked from the middleware *after* it has
 * awaited, and `useRuntimeConfig()` reaches the Nuxt instance through
 * `useNuxtApp()`. With `experimental.asyncContext` disabled (Nuxt's default)
 * unctx stores the instance in a module-scope variable that `callAsync`
 * clears as soon as the middleware suspends, and a vue-router guard has no
 * Vue injection context to fall back on — so resolving config here throws
 * NUXT_E1001 during SSR. The caller resolves it once, before its first await.
 */
async function isSystemInitialized(baseURL: string): Promise<boolean> {
  if (systemInitialized === true) return true
  try {
    const res = await $fetch<{ data: { initialized: boolean } }>(
      '/api/v1/auth/setup/status',
      { baseURL }
    )
    systemInitialized = res.data.initialized
  } catch {
    systemInitialized = true
  }
  return systemInitialized
}

async function getCommercialLicenseStatus(
  baseURL: string
): Promise<CommercialLicenseStatus | null> {
  try {
    const res = await $fetch<{ data: CommercialLicenseStatus }>(
      '/api/v1/license/status',
      { baseURL }
    )
    return res.data
  } catch {
    return null
  }
}

export default defineNuxtRouteMiddleware(async (to) => {
  /**
   * Everything that needs the Nuxt instance is captured here, before the
   * first `await`.
   *
   * Route middleware runs through `nuxtApp.runWithContext(() => middleware(…))`,
   * which on the server is `nuxtAppCtx.callAsync(nuxt, fn)`. unctx only keeps
   * an AsyncLocalStorage when it is created with `asyncContext: true`, and
   * Nuxt passes `!!__NUXT_ASYNC_CONTEXT__ && import.meta.server` — false unless
   * `experimental.asyncContext` is enabled. Without it `callAsync` resets the
   * stored instance synchronously, the moment this function returns its
   * promise, so every continuation after an `await` runs with no instance and
   * `useRuntimeConfig()` / `useAuth()` throw:
   *
   *   [nuxt] A composable that requires access to the Nuxt instance was called
   *   outside of a plugin, Nuxt hook, Nuxt middleware, or Vue setup function.
   *
   * Acquiring them up front costs nothing — `useAuth()` was already built on
   * every navigation that reached the auth section below — and keeps SSR and
   * client behaviour identical (the client sets the instance persistently, so
   * it never noticed).
   */
  const config = useRuntimeConfig()
  const baseURL = import.meta.server ? config.apiBaseUrlServer : config.public.apiBaseUrl
  const auth = useAuth()
  const commercialLicense = useState<CommercialLicenseStatus | null>(
    'commercial-license:status',
    () => null
  )

  // Commercial local installs must activate before the first admin/clinic
  // setup. Hosted/dev deployments return enforced=false and are unchanged.
  const license = await getCommercialLicenseStatus(baseURL)
  commercialLicense.value = license

  if (license?.enforced && !license.active) {
    return to.path === LICENSE_PATH ? undefined : navigateTo(LICENSE_PATH)
  }
  if (to.path === LICENSE_PATH && license?.active) return navigateTo('/')

  const aiLicensed = !license?.enforced || (
    license.active
    && license.features.some(feature => feature.trim().toLowerCase() === 'ai')
  )

  const isAiRoute = (
    to.path === '/copilot'
    || to.path.startsWith('/copilot/')
    || to.path === '/settings/integrations/copilot'
    || to.path.startsWith('/settings/integrations/copilot/')
  )

  if (license?.enforced && license.active && isAiRoute && !aiLicensed) {
    return navigateTo('/')
  }

  const trial = getTrialStatus(config.public)

  if (trial.enabled && trial.expired) {
    return to.path === TRIAL_EXPIRED_PATH ? undefined : navigateTo(TRIAL_EXPIRED_PATH)
  }
  if (to.path === TRIAL_EXPIRED_PATH) return navigateTo('/')

  const publicRoutes = ['/login', SETUP_PATH, LICENSE_PATH, '/p/budget', '/booking']
  const isPublicRoute = publicRoutes.some(route => to.path === route || to.path.startsWith(route + '/'))

  await auth.init()

  if (auth.isAuthenticated.value) {
    if (to.path === '/login' || to.path === SETUP_PATH) return navigateTo('/')
    return
  }

  if (!(await isSystemInitialized(baseURL))) {
    return to.path === SETUP_PATH ? undefined : navigateTo(SETUP_PATH)
  }

  if (to.path === SETUP_PATH) return navigateTo('/login')

  if (!isPublicRoute) return navigateTo('/login')
})
