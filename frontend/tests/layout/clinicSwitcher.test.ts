import { nextTick, ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import ClinicSwitcher from '~/components/ClinicSwitcher.vue'

/**
 * The clinic switcher is the one hand-rolled menu in the shell (everything else
 * is a `UModal` / `USlideover` / `UDropdownMenu`, which Nuxt UI dismisses and
 * focus-traps for us). It had no keyboard behaviour at all — no Escape, no way
 * to walk the clinics, no focus restoration — it stayed open over the page
 * content when the user clicked somewhere else, and `choose()` was not
 * single-flight, so reopening it during a switch minted a token for a *second*
 * clinic and raced the page reload.
 */

const { switchClinic, fetchClinic, toastSpy, selectedClinicId } = vi.hoisted(() => ({
  switchClinic: vi.fn(),
  fetchClinic: vi.fn(),
  toastSpy: vi.fn(),
  selectedClinicId: { current: 'cl-a' }
}))

mockNuxtImport('useAuth', () => () => ({
  clinics: ref([
    { id: 'cl-a', name: 'Clinic Alpha', role: 'admin' },
    { id: 'cl-b', name: 'Clinic Beta', role: 'dentist' },
    { id: 'cl-c', name: 'Clinic Gamma', role: 'dentist' }
  ]),
  switchClinic
}))
mockNuxtImport('useClinic', () => () => ({
  clinicName: ref('Clinic Alpha'),
  fetchClinic
}))
mockNuxtImport('useSelectedClinicId', () => () => ref(selectedClinicId.current))
mockNuxtImport('useToast', () => () => ({ add: toastSpy }))

async function flush(): Promise<void> {
  await nextTick()
  await new Promise(resolve => setTimeout(resolve, 0))
  await nextTick()
}

function menu(): HTMLElement | null {
  return document.body.querySelector<HTMLElement>('[role="menu"]')
}

function items(): HTMLButtonElement[] {
  return Array.from(document.body.querySelectorAll<HTMLButtonElement>('button[role="menuitem"]'))
}

function trigger(): HTMLButtonElement {
  const el = document.body.querySelector<HTMLButtonElement>('[aria-haspopup="menu"]')
  if (!el) throw new Error('switcher trigger not rendered')
  return el
}

beforeEach(() => {
  switchClinic.mockReset()
  fetchClinic.mockReset()
  toastSpy.mockReset()
  selectedClinicId.current = 'cl-a'
})

let wrapper: { unmount: () => void } | null = null

afterEach(() => {
  // Unmount so the component's own document listeners come off with it.
  wrapper?.unmount()
  wrapper = null
  document.body.innerHTML = ''
})

describe('clinic switcher — menu behaviour', () => {
  it('opens on the trigger, lands on the active clinic, and walks with the arrow keys', async () => {
    wrapper = await mountSuspended(ClinicSwitcher, { attachTo: document.body })
    await flush()

    expect(menu()).toBeNull()

    trigger().click()
    await flush()

    expect(menu()).toBeTruthy()
    expect(trigger().getAttribute('aria-expanded')).toBe('true')
    expect(items().map(i => i.dataset.clinicId)).toEqual(['cl-a', 'cl-b', 'cl-c'])

    // Focus starts on the clinic the trigger already names, so Enter confirms it.
    expect((document.activeElement as HTMLElement).dataset?.clinicId).toBe('cl-a')

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }))
    await flush()
    expect((document.activeElement as HTMLElement).dataset?.clinicId).toBe('cl-b')

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true }))
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true }))
    await flush()
    expect((document.activeElement as HTMLElement).dataset?.clinicId).toBe('cl-c')
  })

  it('Escape closes it and returns focus to the trigger', async () => {
    wrapper = await mountSuspended(ClinicSwitcher, { attachTo: document.body })
    await flush()

    trigger().click()
    await flush()
    expect(menu()).toBeTruthy()

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await flush()

    expect(menu()).toBeNull()
    expect(document.activeElement).toBe(trigger())
    expect(switchClinic).not.toHaveBeenCalled()
  })

  it('a click outside closes it', async () => {
    wrapper = await mountSuspended(ClinicSwitcher, { attachTo: document.body })
    await flush()

    trigger().click()
    await flush()
    expect(menu()).toBeTruthy()

    document.body.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true }))
    await flush()

    expect(menu()).toBeNull()
  })

  it('a click inside the menu does not close it', async () => {
    wrapper = await mountSuspended(ClinicSwitcher, { attachTo: document.body })
    await flush()

    trigger().click()
    await flush()

    items()[1]!.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true }))
    await flush()

    expect(menu()).toBeTruthy()
  })

  it('switches once: a second clinic picked while the first switch is in flight is ignored', async () => {
    let release: ((value: boolean) => void) | null = null
    switchClinic.mockImplementation(() => new Promise<boolean>((resolve) => {
      release = resolve
    }))

    wrapper = await mountSuspended(ClinicSwitcher, { attachTo: document.body })
    await flush()

    trigger().click()
    await flush()

    // Two picks in the same tick. `choose()` closes the menu, but Vue only
    // re-renders on the next tick, so both buttons are still there to be
    // clicked — this is the window the handler-level guard covers, which
    // `:disabled` on the trigger cannot.
    const list = items()
    list[1]!.click() // Clinic Beta
    list[2]!.click() // Clinic Gamma, before the DOM caught up
    await flush()

    expect(switchClinic).toHaveBeenCalledTimes(1)
    expect(switchClinic).toHaveBeenCalledWith('cl-b')
    // The trigger reports the pending switch instead of inviting another one.
    expect(trigger().hasAttribute('disabled')).toBe(true)

    trigger().click() // a disabled button ignores a native click
    await flush()
    expect(menu()).toBeNull()

    release?.(false)
    await flush()
    await flush()

    expect(switchClinic).toHaveBeenCalledTimes(1)
    expect(fetchClinic).not.toHaveBeenCalled()
    expect(toastSpy).toHaveBeenCalledTimes(1)
    expect(toastSpy.mock.calls[0]?.[0]).toMatchObject({ color: 'error' })
    expect(trigger().hasAttribute('disabled')).toBe(false)
  })
})
