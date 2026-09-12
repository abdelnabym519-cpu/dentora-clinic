import { nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { useState } from '#app'
import { _resetApiErrorNotifications } from '~/composables/useApi'
import PrescriptionsPage from '../../module_layers/prescriptions/frontend/pages/prescriptions/index.vue'

/**
 * The prescriptions page's patient picker.
 *
 * It is hand-rolled — an input plus an absolutely positioned result list — and
 * it had three defects that all end in the wrong name on a prescription:
 *
 * 1. one request per keystroke with nothing checking which answer was newest,
 *    so a slow reply for a shorter prefix could replace the results for the
 *    text actually in the box;
 * 2. no way to dismiss the list — it only vanished when it was emptied, so it
 *    kept floating over the form after the user clicked away, and Escape did
 *    nothing;
 * 3. no keyboard path to a result at all.
 */

const { fetchMock, toastSpy } = vi.hoisted(() => ({
  fetchMock: vi.fn(),
  toastSpy: vi.fn()
}))

mockNuxtImport('$fetch', () => fetchMock)
mockNuxtImport('useToast', () => () => ({ add: toastSpy }))

const SEARCH_URL = '/api/v1/patients?search='

/** Query whose answer the test holds back, to reproduce a slow earlier reply. */
let parkTerm: string | null = null
let releaseParked: ((value: unknown) => void) | null = null
let searched: string[] = []
let listCalls: string[] = []

const PATIENTS_BY_TERM: Record<string, Array<{ id: string, first_name: string, last_name: string }>> = {
  ma: [
    { id: 'p-1', first_name: 'Maria', last_name: 'One' },
    { id: 'p-2', first_name: 'Marta', last_name: 'Two' }
  ]
}

async function flush(): Promise<void> {
  await nextTick()
  await new Promise(resolve => setTimeout(resolve, 0))
  await nextTick()
}

function input(): HTMLInputElement {
  const el = document.body.querySelector<HTMLInputElement>('[data-testid="prescription-patient-search"]')
  if (!el) throw new Error('patient search input not rendered')
  return el
}

function listbox(): HTMLElement | null {
  return document.body.querySelector<HTMLElement>('#prescription-patient-listbox')
}

function options(): HTMLButtonElement[] {
  return Array.from(document.body.querySelectorAll<HTMLButtonElement>('#prescription-patient-listbox [role="option"]'))
}

async function type(value: string): Promise<void> {
  const el = input()
  el.value = value
  el.dispatchEvent(new Event('input', { bubbles: true }))
  await flush()
}

let wrapper: { unmount: () => void } | null = null

beforeEach(() => {
  parkTerm = null
  releaseParked = null
  searched = []
  listCalls = []
  _resetApiErrorNotifications()
  useState<string[]>('auth:permissions', () => []).value = ['*']

  fetchMock.mockImplementation(async (url: string) => {
    const full = String(url)

    if (full.includes(SEARCH_URL)) {
      const term = decodeURIComponent(full.split('search=')[1]?.split('&')[0] ?? '')
      searched.push(term)
      if (term === parkTerm) {
        return new Promise((resolve) => {
          releaseParked = resolve
        })
      }
      return { data: PATIENTS_BY_TERM[term] ?? [{ id: `p-${term}`, first_name: term.toUpperCase(), last_name: 'Fast' }] }
    }
    if (full.includes('/api/v1/prescriptions')) {
      listCalls.push(full)
      return { data: [] }
    }
    return { data: [] }
  })
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  document.body.innerHTML = ''
  fetchMock.mockReset()
  toastSpy.mockReset()
  _resetApiErrorNotifications()
})

async function mountPage() {
  wrapper = await mountSuspended(PrescriptionsPage, { attachTo: document.body })
  await flush()
}

describe('prescriptions patient picker', () => {
  it('keeps the results that match the text in the box when an earlier search answers last', async () => {
    await mountPage()

    // Two characters is the picker's minimum, so the slow query is 'ma' and the
    // one that supersedes it is 'mar'.
    parkTerm = 'ma'
    await type('ma')
    expect(searched).toEqual(['ma'])

    parkTerm = null
    await type('mar')
    await flush()

    expect(options().map(o => o.textContent?.trim())).toEqual(['MAR Fast'])

    // Now the stale answer arrives, carrying the *wider* match set.
    releaseParked?.({ data: PATIENTS_BY_TERM.ma })
    await flush()
    await flush()

    expect(options().map(o => o.textContent?.trim())).toEqual(['MAR Fast'])
    expect(listbox()?.textContent).not.toContain('Maria')
  })

  it('reaches a result with the arrow keys and Enter, and selects the highlighted one', async () => {
    await mountPage()

    await type('ma')
    expect(listbox()).toBeTruthy()
    expect(input().getAttribute('aria-expanded')).toBe('true')

    input().dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }))
    await flush()
    expect(input().getAttribute('aria-activedescendant')).toBe('prescription-patient-option-0')
    expect(options()[0]?.getAttribute('aria-selected')).toBe('true')

    input().dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }))
    await flush()
    expect(input().getAttribute('aria-activedescendant')).toBe('prescription-patient-option-1')

    input().dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    await flush()
    await flush()

    // The *second* patient is the one selected, the list is gone, and the
    // history that follows is read for that patient — not for the first match.
    expect(input().value).toBe('Marta Two')
    expect(listbox()).toBeNull()
    expect(listCalls.some(c => c.includes('p-2'))).toBe(true)
    expect(listCalls.some(c => c.includes('p-1'))).toBe(false)
  })

  it('Escape closes the list without choosing anyone', async () => {
    await mountPage()
    // The page reads the (unfiltered) history on mount; only a *new* call would
    // mean a patient got selected.
    const listCallsBefore = listCalls.length

    await type('ma')
    expect(listbox()).toBeTruthy()

    input().dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await flush()

    expect(listbox()).toBeNull()
    expect(input().getAttribute('aria-expanded')).toBe('false')
    expect(input().value).toBe('ma')
    expect(listCalls).toHaveLength(listCallsBefore)
  })

  it('a click outside closes the list, a click inside does not', async () => {
    await mountPage()

    await type('ma')
    expect(listbox()).toBeTruthy()

    // Inside: hovering an option must not dismiss the list.
    options()[0]!.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true }))
    await flush()
    expect(listbox()).toBeTruthy()

    document.body.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true }))
    await flush()
    expect(listbox()).toBeNull()
  })
})
