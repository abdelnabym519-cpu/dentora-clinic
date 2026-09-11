import { describe, expect, it } from 'vitest'
import { latestGuard, useSharedLatestGuard } from '~/utils/latestGuard'

/**
 * The stale-response guard.
 *
 * A fetch triggered by something the user can change faster than the network
 * answers — a search box, a filter chip, a pagination control, the selected
 * patient — has to drop its result once a newer fetch for the same slot has
 * started. Otherwise the slower earlier response lands last and the screen
 * keeps showing data that belongs to a state the user already left.
 */

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((r) => {
    resolve = r
  })
  return { promise, resolve }
}

describe('latestGuard', () => {
  it('lets the newest fetch through and drops the one it superseded', async () => {
    const guard = latestGuard()
    const landed: string[] = []

    const first = deferred<string>()
    const second = deferred<string>()

    // "jo" is still in flight when "john" starts
    const loadJo = (async () => {
      const isLatest = guard.begin()
      const value = await first.promise
      if (isLatest()) landed.push(value)
    })()
    const loadJohn = (async () => {
      const isLatest = guard.begin()
      const value = await second.promise
      if (isLatest()) landed.push(value)
    })()

    // and the *earlier* request is the one that answers last
    second.resolve('results for john')
    first.resolve('results for jo')
    await Promise.all([loadJo, loadJohn])

    expect(landed).toEqual(['results for john'])
  })

  it('drops an in-flight fetch when the state is cleared without a new one', async () => {
    const guard = latestGuard()
    const landed: string[] = []
    const pending = deferred<string>()

    const load = (async () => {
      const isLatest = guard.begin()
      const value = await pending.promise
      if (isLatest()) landed.push(value)
    })()

    guard.invalidate()
    pending.resolve('the patient that was deselected')
    await load

    expect(landed).toEqual([])
  })

  it('keeps separate slots independent, so one list cannot veto another', async () => {
    const teeth = latestGuard()
    const timeline = latestGuard()
    const landed: string[] = []

    const loadTeeth = (async () => {
      const isLatest = teeth.begin()
      await Promise.resolve()
      if (isLatest()) landed.push('teeth')
    })()
    const loadTimeline = (async () => {
      const isLatest = timeline.begin()
      await Promise.resolve()
      if (isLatest()) landed.push('timeline')
    })()

    await Promise.all([loadTeeth, loadTimeline])

    expect(landed.sort()).toEqual(['teeth', 'timeline'])
  })

  it('supersedes across as many rounds as the user manages to click', async () => {
    const guard = latestGuard()
    const landed: number[] = []
    const rounds = [deferred<null>(), deferred<null>(), deferred<null>(), deferred<null>()]

    const loads = rounds.map((d, page) => (async () => {
      const isLatest = guard.begin()
      await d.promise
      if (isLatest()) landed.push(page)
    })())

    // they answer in the worst possible order: oldest last
    for (const d of [...rounds].reverse()) d.resolve(null)
    await Promise.all(loads)

    expect(landed).toEqual([3])
  })
})

describe('useSharedLatestGuard', () => {
  it('shares one counter across every caller of the same key', async () => {
    // Two components reading the same global list: the second fetch must win
    // even though it was started by a different caller.
    const componentA = useSharedLatestGuard('appointments:list')
    const componentB = useSharedLatestGuard('appointments:list')
    const landed: string[] = []

    const slow = deferred<string>()
    const fast = deferred<string>()

    const fromA = (async () => {
      const isLatest = componentA.begin()
      const value = await slow.promise
      if (isLatest()) landed.push(value)
    })()
    const fromB = (async () => {
      const isLatest = componentB.begin()
      const value = await fast.promise
      if (isLatest()) landed.push(value)
    })()

    fast.resolve('monday from B')
    slow.resolve('sunday from A')
    await Promise.all([fromA, fromB])

    expect(landed).toEqual(['monday from B'])
  })

  it('keeps a different key independent', async () => {
    const budgets = useSharedLatestGuard('budgets:list')
    const catalog = useSharedLatestGuard('catalog:items')
    const landed: string[] = []

    const a = (async () => {
      const isLatest = budgets.begin()
      await Promise.resolve()
      if (isLatest()) landed.push('budgets')
    })()
    const b = (async () => {
      const isLatest = catalog.begin()
      await Promise.resolve()
      if (isLatest()) landed.push('catalog')
    })()
    await Promise.all([a, b])

    expect(landed.sort()).toEqual(['budgets', 'catalog'])
  })
})
