import { h, defineComponent, nextTick, type Component } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { mountSuspended } from '@nuxt/test-utils/runtime'
import { useConfirmDialog } from '~/composables/useConfirmDialog'
import ConfirmDialogHost from '~/components/shared/ConfirmDialogHost.vue'

/**
 * `window.confirm` is blocked inside a sandboxed iframe: it returns `false`
 * without ever asking, so every destructive button that relied on it — delete
 * invoice, cancel budget, remove plan item, delete a clinical note, retry the
 * Veri*Factu queue — silently did nothing. Thirteen call sites now go through
 * `useConfirmDialog`, whose promise must always settle, or the caller's
 * `isSubmitting`/`isProcessing` flag stays stuck forever.
 */

interface Host {
  api: ReturnType<typeof useConfirmDialog>
}

async function mountHost(): Promise<Host> {
  let api!: ReturnType<typeof useConfirmDialog>
  const HostComponent: Component = defineComponent({
    setup() {
      api = useConfirmDialog()
      return () => h(ConfirmDialogHost)
    }
  })
  await mountSuspended(HostComponent)
  // `useState` persists across tests in a file — start from a closed dialog.
  api.request.value = null
  await flush()
  return { api }
}

async function flush(): Promise<void> {
  await nextTick()
  await new Promise(resolve => setTimeout(resolve, 0))
  await nextTick()
}

/** The dialog is teleported to <body>, so query the document, not a wrapper. */
function button(testId: string): HTMLElement | null {
  return document.body.querySelector<HTMLElement>(`[data-testid="${testId}"]`)
}

async function clickWhenPresent(testId: string): Promise<void> {
  await vi.waitFor(() => {
    expect(button(testId), `${testId} should be rendered`).not.toBeNull()
  })
  button(testId)!.click()
  await flush()
}

describe('useConfirmDialog — the app-wide confirm always answers', () => {
  it('renders the question and resolves true when accepted', async () => {
    const { api } = await mountHost()

    const answer = api.confirmDialog({ title: 'Delete this invoice?', danger: true })
    await flush()

    await clickWhenPresent('confirm-dialog-accept')

    await expect(answer).resolves.toBe(true)
  })

  it('resolves false when cancelled, leaving the action unrun', async () => {
    const { api } = await mountHost()

    const answer = api.confirmDialog({ title: 'Cancel this budget?' })
    await flush()

    await clickWhenPresent('confirm-dialog-cancel')

    await expect(answer).resolves.toBe(false)
  })

  it('settles a superseded request with false so no caller hangs', async () => {
    const { api } = await mountHost()

    const first = api.confirmDialog({ title: 'First question' })
    await flush()
    const second = api.confirmDialog({ title: 'Second question' })
    await flush()

    // The first caller awaited a dialog that no longer exists.
    await expect(first).resolves.toBe(false)

    await clickWhenPresent('confirm-dialog-accept')
    await expect(second).resolves.toBe(true)
  })
})
