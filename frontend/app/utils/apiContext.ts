/**
 * Operation context for API requests.
 *
 * Every request that reaches the shared error handling in ``useApi``
 * must be able to say *which operation failed*. Without it, a 403 from
 * an ambient background probe (the Veri*Factu compliance banner polling
 * ``/verifactu/health``) rendered as a bare "Access denied" toast while
 * the user was navigating patients — an accurate HTTP status attached
 * to the wrong screen.
 *
 * These helpers derive a stable, human-readable label from the request
 * path so the shared error UI always names the failing operation, and
 * so callers can pass an explicit ``operation`` label when they know
 * better (e.g. a localized button name).
 */

export interface ApiOperationContext {
  /** Stable identifier used for toast de-duplication, e.g. ``verifactu/health``. */
  key: string
  /** Backend module namespace, e.g. ``verifactu``. ``app`` when it can't be derived. */
  module: string
  /** Trailing meaningful segment, e.g. ``health``. Empty for bare collections. */
  action: string
  /** Human-readable label, e.g. ``Verifactu health``. */
  label: string
}

/** UUID / numeric path segments identify a record, never an operation. */
const RECORD_ID_SEGMENT
  = /^(\d+|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/i

function humanize(segment: string): string {
  return segment
    .split(/[_\-.]+/)
    .filter(Boolean)
    .map((word) => {
      // "3d" -> "3D": a digit followed by a single letter is an acronym
      // suffix, not a word (dental_3d, cbct_2d, …).
      const acronym = /^(\d+)([a-z])$/.exec(word)
      if (acronym) return `${acronym[1]}${acronym[2]!.toUpperCase()}`
      return word.charAt(0).toUpperCase() + word.slice(1)
    })
    .join(' ')
}

/**
 * Derive the operation context of an API path.
 *
 * ``/api/v1/dental_3d/patients/<uuid>/implant-planning``
 * → ``{ module: 'dental_3d', action: 'implant-planning', label: 'Dental 3D implant planning' }``
 */
export function apiOperationContext(path: string): ApiOperationContext {
  const pathname = path.split('?')[0] ?? ''
  const segments = pathname.split('/').filter(Boolean)
  // Drop the ``/api/<version>`` prefix so the first real segment is the
  // owning module. Paths that don't follow the convention still work —
  // their first segment is treated as the module.
  const rest = segments[0] === 'api' ? segments.slice(2) : segments
  const moduleName = rest[0] ?? 'app'
  const action
    = [...rest.slice(1)].reverse().find(segment => !RECORD_ID_SEGMENT.test(segment)) ?? ''

  return {
    key: action ? `${moduleName}/${action}` : moduleName,
    module: moduleName,
    action,
    label: action ? `${humanize(moduleName)} ${humanize(action)}` : humanize(moduleName)
  }
}
