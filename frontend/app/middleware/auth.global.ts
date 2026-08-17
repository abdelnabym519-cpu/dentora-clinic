import { getTrialStatus } from '~/utils/trial'

const SETUP_PATH = '/setup'
const LICENSE_PATH = '/activate'
const TRIAL_EXPIRED_PATH = '/trial-expired'

let systemInitialized: boolean | null = null

async function isSystemInitialized(): Promise<boolean> {
  if (systemInitialized === true) return true
  const config = useRuntimeConfig()
  const baseURL = import.meta.server ? config.apiBaseUrlServer : config.public.apiBaseUrl
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

async function getCommercialLicenseStatus(): Promise<{ enforced: boolean, active: boolean } | null> {
  const config = useRuntimeConfig()
  const baseURL = import.meta.server ? config.apiBaseUrlServer : config.public.apiBaseUrl
  try {
    const res = await $fetch<{ data: { enforced: boolean, active: boolean } }>(
      '/api/v1/license/status',
      { baseURL }
    )
    return res.data
  } catch {
    return null
  }
}

export default defineNuxtRouteMiddleware(async (to) => {
  // Commercial local installs must activate before the first admin/clinic
  // setup. Hosted/dev deployments return enforced=false and are unchanged.
  const license = await getCommercialLicenseStatus()
  if (license?.enforced && !license.active) {
    return to.path === LICENSE_PATH ? undefined : navigateTo(LICENSE_PATH)
  }
  if (to.path === LICENSE_PATH && license?.active) return navigateTo('/')

  const config = useRuntimeConfig()
  const trial = getTrialStatus(config.public)

  if (trial.enabled && trial.expired) {
    return to.path === TRIAL_EXPIRED_PATH ? undefined : navigateTo(TRIAL_EXPIRED_PATH)
  }
  if (to.path === TRIAL_EXPIRED_PATH) return navigateTo('/')

  const auth = useAuth()

  const publicRoutes = ['/login', SETUP_PATH, LICENSE_PATH, '/p/budget', '/booking']
  const isPublicRoute = publicRoutes.some(route => to.path === route || to.path.startsWith(route + '/'))

  await auth.init()

  if (auth.isAuthenticated.value) {
    if (to.path === '/login' || to.path === SETUP_PATH) return navigateTo('/')
    return
  }

  if (!(await isSystemInitialized())) {
    return to.path === SETUP_PATH ? undefined : navigateTo(SETUP_PATH)
  }

  if (to.path === SETUP_PATH) return navigateTo('/login')

  if (!isPublicRoute) return navigateTo('/login')
})
