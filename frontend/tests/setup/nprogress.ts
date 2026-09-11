/**
 * Global test stub for the `nprogress` client plugin.
 *
 * The real module removes its progress bar from a nested ~200 ms timer. Under
 * vitest that timer routinely outlives the environment of the file that started
 * it, and the callback then dies with `ReferenceError: document is not defined`.
 * Vitest counts that as an *unhandled* error and fails the whole run even though
 * every test passed — and since the timer fires inside whichever file happens to
 * be running at that moment, stubbing it file-by-file only moves the failure
 * around. Mocking it once here removes the timers for every test file.
 */
import { vi } from 'vitest'

vi.mock('nprogress', () => ({
  default: {
    configure: () => {},
    start: () => {},
    done: () => {},
    remove: () => {},
    isStarted: () => false,
    set: () => {},
    inc: () => {},
    trickle: () => {},
    setParent: () => {},
    getStatus: () => null,
    isRendered: () => false
  }
}))
