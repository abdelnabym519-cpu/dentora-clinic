import { defineConfig, devices } from '@playwright/test'

/**
 * Playwright config for Dentora browser E2E.
 *
 * Tests drive the live dev stack (Nuxt at :3000, FastAPI at :8000,
 * Postgres seeded via `./scripts/seed-demo.sh`). The suite is
 * deliberately small and focused on smoke + RBAC boundaries; it does
 * NOT exercise every CRUD path (that's the backend pytest suite's
 * job).
 *
 * Run with: `./scripts/e2e.sh`
 */
export default defineConfig({
  testDir: './tests/e2e',
  timeout: 30_000,
  expect: { timeout: 5_000 },
  fullyParallel: false,
  retries: 0,
  workers: 1,
  reporter: [['list']],

  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://localhost:3000',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    actionTimeout: 8_000,
    navigationTimeout: 15_000
  },

  projects: [
    {
      name: 'chromium',
      // Optional: allow CI/local sandboxes to point Playwright at a
      // self-contained Chromium build (vendored with its system libs)
      // via PLAYWRIGHT_CHROMIUM_EXECUTABLE (+ comma-separated
      // PLAYWRIGHT_CHROMIUM_ARGS). When unset, Playwright downloads and
      // launches its own browser as usual.
      use: {
        ...devices['Desktop Chrome'],
        ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
          ? {
              launchOptions: {
                executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,
                args: (process.env.PLAYWRIGHT_CHROMIUM_ARGS || '').split(',').filter(Boolean)
              }
            }
          : {})
      }
    }
  ]
})
