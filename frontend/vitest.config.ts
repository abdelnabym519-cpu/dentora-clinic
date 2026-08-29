import { defineVitestConfig } from '@nuxt/test-utils/config'

export default defineVitestConfig({
  test: {
    environment: 'nuxt',
    globals: true,
    // The integrated app loads every built-in Nuxt layer before tests start.
    // On cold CI workers that deterministic bootstrap can exceed Vitest's
    // 10-second default even though individual tests remain fast.
    hookTimeout: 120_000,
    // Starting one full Nuxt environment per test file at once exhausts
    // cold CI workers. Four workers keep the suite parallel and bounded.
    maxWorkers: 4,
    // Playwright E2E specs live under tests/e2e/. They use their own
    // test runner (see playwright.config.ts + scripts/e2e.sh) and must
    // not be picked up by vitest — doing so throws
    // "Playwright Test did not expect test.describe() to be called here".
    exclude: ['**/node_modules/**', '**/dist/**', 'tests/e2e/**'],
    environmentOptions: {
      nuxt: {
        mock: {
          intersectionObserver: true,
          indexedDb: true
        }
      }
    }
  }
})
