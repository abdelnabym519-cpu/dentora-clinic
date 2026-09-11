import type { OverdueInvoice } from '~~/app/types'

/**
 * Shared state for reports widgets on the home dashboard. Overdue
 * invoices are fetched once and reused by the hero tile and the
 * attention panel.
 */
export function useHomeReports() {
  const { fetchOverdueInvoices, errors, clearErrors } = useReports()

  const overdue = useState<OverdueInvoice[]>('reports.home:overdue', () => [])
  const overdueLoaded = useState<boolean>('reports.home:overdue-loaded', () => false)
  /**
   * Why the overdue list could not be read, or null when it could.
   *
   * `fetchOverdueInvoices` resolves to `[]` both when nothing is overdue and
   * when the request failed. The hero tile and the attention panel rendered
   * both as a green "no overdue invoices" all-clear — on the home dashboard,
   * where a clinic chases money from. The failure is now distinguishable.
   */
  const overdueError = useState<string | null>('reports.home:overdue-error', () => null)

  async function loadOverdue(): Promise<OverdueInvoice[]> {
    clearErrors()
    overdue.value = await fetchOverdueInvoices()
    overdueLoaded.value = true
    // Same useReports() instance as the fetch above, read straight after it.
    overdueError.value = errors.value.overdueInvoices ?? null
    return overdue.value
  }

  return {
    overdue: readonly(overdue),
    overdueLoaded: readonly(overdueLoaded),
    overdueError: readonly(overdueError),
    loadOverdue
  }
}
