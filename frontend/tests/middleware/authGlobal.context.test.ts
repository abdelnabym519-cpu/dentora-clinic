import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport } from '@nuxt/test-utils/runtime'
import { useNuxtApp } from '#app'
import type { RouteLocationNormalized } from 'vue-router'
import authMiddleware from '~/middleware/auth.global'

/**
 * The global auth middleware must acquire the Nuxt instance before it awaits.
 *
 * Route middleware runs through `nuxtApp.runWithContext(() => middleware(…))`,
 * which on the server is `nuxtAppCtx.callAsync(nuxt, fn)`. unctx only keeps an
 * AsyncLocalStorage when it was created with `asyncContext: true`, and Nuxt
 * passes `!!__NUXT_ASYNC_CONTEXT__ && import.meta.server` — false unless
 * `experimental.asyncContext` is enabled (it is not, by default). Without it,
 * `callAsync` resets the stored instance synchronously, the moment the
 * middleware returns its promise, and a vue-router `beforeEach` guard has no
 * Vue injection context to fall back on. So every continuation after an `await`
 * ran with no instance, and the middleware's own
 *
 *     const license = await getCommercialLicenseStatus()   // suspends here
 *     …
 *     const config = useRuntimeConfig()                    // NUXT_E1001
 *     const auth = useAuth()                               // NUXT_E1001
 *
 * threw during SSR — the same error the app reported as "Failed to fetch
 * clinic" / "Patients connection error", because the session was never
 * initialised on the server render. The client sets the instance persistently,
 * which is why this only ever showed up in the frontend container's logs.
 *
 * The test simulates the server: the first `$fetch` marks the middleware as
 * suspended, and from then on any instance composable throws the real
 * NUXT_E1001. It then asserts the navigation decisions are unchanged, so the
 * hoisting cannot quietly alter licensing, trial or auth behaviour.
 */

const NUXT_E1001 = '[nuxt] A composable that requires access to the Nuxt instance '
  + 'was called outside of a plugin, Nuxt hook, Nuxt middleware, or Vue setup function.'

const { state } = vi.hoisted(() => ({
  state: {
    /** True once the middleware has suspended at an await. */
    suspended: false,
    navigated: [] as string[],
    license: null as { enforced: boolean, active: boolean, features: string[] } | null,
    initialized: true,
    isAuthenticated: true,
    initCalls: 0,
    instanceCalls: [] as string[],
    fetches: [] as Array<{ url: string, baseURL?: string }>,
    publicRouteCalls: 0
  }
}))

/** Mirrors what Nuxt throws when `useNuxtApp()` finds no instance. */
function acquire(caller: string): void {
  state.instanceCalls.push(`${caller}:${state.suspended ? 'after-await' : 'before-await'}`)
  if (state.suspended) throw new Error(NUXT_E1001)
}

mockNuxtImport('$fetch', () => async (url: string, opts?: { baseURL?: string }) => {
  state.fetches.push({ url: String(url), baseURL: opts?.baseURL })
  // The middleware has now handed control back to the event loop: on the
  // server this is exactly where the unctx store is cleared.
  state.suspended = true
  await Promise.resolve()
  if (String(url).includes('/license/status')) return { data: state.license }
  if (String(url).includes('/auth/setup/status')) return { data: { initialized: state.initialized } }
  return { data: null }
})

mockNuxtImport('useRuntimeConfig', () => () => {
  acquire('useRuntimeConfig')
  // Merge over the real config: Nuxt's own plugins call useRuntimeConfig
  // during boot, and a partial stub starves the router plugin (the app never
  // provides $router, and @nuxt/test-utils then fails on useRouter().afterEach).
  const real = useNuxtApp().$config as {
    apiBaseUrlServer?: string
    public?: Record<string, unknown>
  }
  return {
    ...real,
    apiBaseUrlServer: 'http://backend:8000',
    public: {
      ...(real.public ?? {}),
      apiBaseUrl: '/api',
      trialMode: false,
      trialStartedAt: '',
      trialDays: 3
    }
  }
})

mockNuxtImport('useAuth', () => () => {
  acquire('useAuth')
  return {
    init: async () => { state.initCalls++ },
    isAuthenticated: { value: state.isAuthenticated }
  }
})

mockNuxtImport('navigateTo', () => (path: string) => {
  state.navigated.push(path)
  return { redirectTo: path }
})

function route(path: string): RouteLocationNormalized {
  return {
    path,
    fullPath: path,
    hash: '',
    query: {},
    params: {},
    name: undefined,
    matched: [],
    meta: {},
    redirectedFrom: undefined
  } as unknown as RouteLocationNormalized
}

beforeEach(() => {
  state.suspended = false
  state.navigated = []
  state.license = null
  state.initialized = true
  state.isAuthenticated = true
  state.initCalls = 0
  state.instanceCalls = []
  state.fetches = []
})

/**
 * Runs the middleware and asserts no instance composable was acquired after
 * the first suspension — the invariant the SSR failure violated.
 */
async function run(to: string, from = '/'): Promise<unknown> {
  const result = await authMiddleware(route(to), route(from))
  expect(
    state.instanceCalls.filter(call => call.endsWith(':after-await')),
    `instance composables acquired after an await: ${state.instanceCalls.join(', ')}`
  ).toEqual([])
  return result
}

describe('auth.global middleware — Nuxt instance ownership across awaits', () => {
  // Runs first: `isSystemInitialized` caches a positive answer at module level,
  // and this is the only case that needs the negative one.
  it('sends an unauthenticated visitor to setup when the system is not initialized', async () => {
    state.isAuthenticated = false
    state.initialized = false

    await run('/patients')

    expect(state.navigated).toEqual(['/setup'])
    // The helper now receives the base URL from the middleware instead of
    // resolving runtime config itself, so the request must still be aimed at
    // the configured API base.
    const setupFetch = state.fetches.find(f => f.url.includes('/auth/setup/status'))
    expect(setupFetch?.baseURL).toBe('/api')
  })

  it('initialises the session and lets an authenticated visitor through', async () => {
    await run('/patients')

    expect(state.initCalls).toBe(1)
    expect(state.navigated).toEqual([])
    expect(state.instanceCalls).toContain('useRuntimeConfig:before-await')
    expect(state.instanceCalls).toContain('useAuth:before-await')
  })

  it('redirects an unauthenticated visitor to the login page', async () => {
    state.isAuthenticated = false

    await run('/patients')

    expect(state.initCalls).toBe(1)
    expect(state.navigated).toEqual(['/login'])
  })

  it('keeps a public route reachable without a session', async () => {
    state.isAuthenticated = false

    await run('/booking')

    expect(state.navigated).toEqual([])
  })

  it('still enforces the commercial licence gate before anything else', async () => {
    state.license = { enforced: true, active: false, features: [] }

    await run('/patients')

    expect(state.navigated).toEqual(['/activate'])
    // The gate runs before the session is touched.
    expect(state.initCalls).toBe(0)
  })

  it('lets an activated install through the licence gate', async () => {
    state.license = { enforced: true, active: true, features: ['ai'] }

    await run('/copilot')

    expect(state.navigated).toEqual([])
    expect(state.initCalls).toBe(1)
  })
})
