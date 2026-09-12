import { nextTick } from 'vue'
import { afterEach, describe, expect, it } from 'vitest'
import { mountSuspended } from '@nuxt/test-utils/runtime'
import PerioIndicesBanner from '../../module_layers/periodontogram/frontend/components/PerioIndicesBanner.vue'

/**
 * Closing a periodontogram session asks the clinician for observations.
 *
 * The dialog used to close itself and wipe the textarea the instant it emitted,
 * i.e. *before* the request resolved. When the close failed — a 409 because the
 * session was closed in another tab, a 422, a network drop — the session
 * correctly stayed a draft and the chart toasted the reason, but what the
 * clinician had typed was gone and the dialog was shut: reopen, retype, try
 * again. The dialog now stays exactly as they left it, and only the parent,
 * which is what knows the outcome, closes it.
 */

const DRAFT = {
  id: 'snap-1',
  patient_id: 'pat-1',
  status: 'draft' as const,
  recorded_at: '2026-09-01T10:00:00Z',
  closed_at: null
}

const INDICES = { bop_pct: 12, pi_pct: 30, cal_mean_mm: 2.1, deep_pockets_count: 4 }

const NOTES = 'Generalised bleeding on probing, 6mm pocket at 36 distal.'

async function flush(): Promise<void> {
  await nextTick()
  await new Promise(resolve => setTimeout(resolve, 0))
  await nextTick()
}

function notesField(): HTMLTextAreaElement | null {
  return document.body.querySelector<HTMLTextAreaElement>('[data-testid="perio-close-notes"]')
}

function confirmButton(): HTMLButtonElement | null {
  return document.body.querySelector<HTMLButtonElement>('[data-testid="perio-close-confirm"]')
}

function openButton(): HTMLButtonElement {
  const el = document.body.querySelector<HTMLButtonElement>('[data-testid="perio-close-open"]')
  if (!el) throw new Error('close-session button not rendered')
  return el
}

let wrapper: Awaited<ReturnType<typeof mountSuspended>> | null = null

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  document.body.innerHTML = ''
})

async function mountBanner() {
  wrapper = await mountSuspended(PerioIndicesBanner, {
    props: { indices: INDICES, snapshot: DRAFT, closing: false },
    attachTo: document.body
  })
  await flush()
  return wrapper
}

async function openDialogAndType(): Promise<void> {
  openButton().click()
  await flush()
  const field = notesField()
  if (!field) throw new Error('the close dialog did not open')
  field.value = NOTES
  field.dispatchEvent(new Event('input', { bubbles: true }))
  await flush()
}

describe('periodontogram close-session dialog', () => {
  it('keeps the typed observations when the close fails', async () => {
    await mountBanner()
    await openDialogAndType()

    confirmButton()!.click()
    await flush()

    // The request went out with the notes…
    expect(wrapper!.emitted('close')).toEqual([[NOTES]])
    // …and the dialog is still there with them still typed, because nobody has
    // said the close succeeded yet.
    expect(notesField()).toBeTruthy()
    expect(notesField()!.value).toBe(NOTES)

    // The parent's request finishes and the close did NOT take (the session is
    // still a draft). This is the moment the notes used to be lost.
    await wrapper!.setProps({ closing: false })
    await flush()

    expect(notesField(), 'the dialog must survive a failed close').toBeTruthy()
    expect(notesField()!.value).toBe(NOTES)
    expect(wrapper!.emitted('close')).toHaveLength(1)
  })

  it('closes and clears only when the parent reports success', async () => {
    await mountBanner()
    await openDialogAndType()

    confirmButton()!.click()
    await flush()
    expect(notesField()).toBeTruthy()

    // What the chart calls once `closeSession` really resolved.
    ;(wrapper!.vm as unknown as { closeSucceeded: () => void }).closeSucceeded()
    await flush()

    expect(notesField()).toBeNull()
  })

  it('does not fire a second close while one is in flight', async () => {
    await mountBanner()
    await openDialogAndType()

    confirmButton()!.click()
    await wrapper!.setProps({ closing: true })
    await flush()

    // Same tick, before the pending state rendered: the handler guard is what
    // stops this one, not the button's `:loading`.
    confirmButton()!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flush()

    expect(wrapper!.emitted('close')).toHaveLength(1)
  })
})
