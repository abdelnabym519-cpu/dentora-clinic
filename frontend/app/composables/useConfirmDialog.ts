export interface ConfirmDialogOptions {
  /**
   * The question, in the user's language. Callers keep the copy they already
   * passed to `window.confirm`, so no string is lost or re-translated.
   */
  title: string
  description?: string
  confirmLabel?: string
  cancelLabel?: string
  /** Destructive actions get the danger colour on the accept button. */
  danger?: boolean
}

// The resolver cannot live in `useState` — Nuxt serializes that into the SSR
// payload, and a function is not serializable. It is only ever assigned on the
// client (see the `import.meta.client` guard below).
let settle: ((confirmed: boolean) => void) | null = null

/**
 * Promise-based replacement for `window.confirm`.
 *
 * Why the native dialog is a defect here: in a sandboxed iframe — which is how
 * a preview or an embedded deployment runs — `confirm()` is *blocked* and
 * returns `false` without ever asking, so every destructive button (delete
 * invoice, cancel budget, remove plan item, retry the Veri*Factu queue)
 * silently does nothing. It also cannot be localized beyond its message,
 * styled, or keyboard-trapped.
 *
 * Call shape is unchanged:
 *
 *     const { confirmDialog } = useConfirmDialog()
 *     if (!await confirmDialog({ title: t('invoice.confirmations.delete'), danger: true })) return
 *
 * The dialog itself is rendered once, app-wide, by `<ConfirmDialogHost />` in
 * `app.vue`.
 */
export function useConfirmDialog() {
  const request = useState<ConfirmDialogOptions | null>('ui:confirm-dialog', () => null)

  function confirmDialog(options: ConfirmDialogOptions): Promise<boolean> {
    if (!import.meta.client) return Promise.resolve(false)
    // Never leave an earlier caller awaiting a dialog that will not close.
    settle?.(false)
    request.value = options
    return new Promise<boolean>((resolve) => {
      settle = resolve
    })
  }

  /** The host calls this when the user answers — or dismisses the dialog. */
  function resolveConfirmDialog(confirmed: boolean): void {
    request.value = null
    const done = settle
    settle = null
    done?.(confirmed)
  }

  return { request, confirmDialog, resolveConfirmDialog }
}
