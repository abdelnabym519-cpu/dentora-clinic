import { chromium, type FullConfig } from '@playwright/test'

const API_BASE = process.env.E2E_API_BASE || 'http://127.0.0.1:8000'
const WARMUP_TIMEOUT_MS = 120_000

export default async function globalSetup(config: FullConfig) {
  const configuredBaseURL = config.projects[0]?.use.baseURL
  const baseURL = typeof configuredBaseURL === 'string'
    ? configuredBaseURL
    : (process.env.E2E_BASE_URL || 'http://localhost:3000')
  const origin = new URL(baseURL).origin

  const browser = await chromium.launch({ headless: true })

  try {
    const context = await browser.newContext()
    const form = new URLSearchParams()
    form.set('username', 'admin@demo.clinic')
    form.set('password', 'demo1234')

    const response = await context.request.post(`${API_BASE}/api/v1/auth/login`, {
      data: form.toString(),
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
    })

    if (!response.ok()) {
      throw new Error(`E2E warm-up login failed: HTTP ${response.status()}`)
    }

    const body = await response.json() as { access_token?: string }
    if (!body.access_token) {
      throw new Error('E2E warm-up login did not return access_token')
    }

    await context.addCookies([
      { name: 'access_token', value: body.access_token, url: origin }
    ])
    await context.addInitScript(() => {
      window.localStorage.setItem('dentora-locale', 'en')
      document.documentElement.lang = 'en'
      document.documentElement.dir = 'ltr'
    })

    const page = await context.newPage()
    await page.goto(origin, { waitUntil: 'load', timeout: WARMUP_TIMEOUT_MS })
    await page.getByTestId('dashboard-screen').waitFor({
      state: 'visible',
      timeout: WARMUP_TIMEOUT_MS
    })
    await page.getByTestId('dashboard-skeleton').waitFor({
      state: 'hidden',
      timeout: WARMUP_TIMEOUT_MS
    })
  } finally {
    await browser.close()
  }
}
