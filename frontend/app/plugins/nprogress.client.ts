import NProgress from 'nprogress'
import 'nprogress/nprogress.css'

export default defineNuxtPlugin(() => {
  // Vitest tears down its DOM between Nuxt test environments. NProgress.done()
  // deliberately schedules a delayed DOM removal; letting that timer survive
  // teardown causes an unhandled `document is not defined` error even though
  // the application test itself has passed. The progress bar is purely visual,
  // so do not register its router hooks in unit-test environments.
  if (process.env.NODE_ENV === 'test') return

  const router = useRouter()

  // Configure NProgress
  NProgress.configure({
    showSpinner: false,
    speed: 200,
    minimum: 0.1
  })

  router.beforeEach(() => {
    NProgress.start()
  })

  router.afterEach(() => {
    NProgress.done()
  })
})
