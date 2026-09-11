/**
 * Permission matching — frontend mirror of the backend contract.
 *
 * ``app/core/auth/permissions.py:permission_matches`` is the authority:
 * ``"*"`` grants everything and ``"module.*"`` grants every permission in
 * that namespace. ``/auth/me`` normally hands the UI an already-expanded,
 * concrete list, but a wildcard can still reach the client (a module
 * grants ``"*"`` to a role and an endpoint requires a permission the
 * module never declared, so expansion has nothing to expand into).
 *
 * Matching only exact strings in that case hides — or worse, shows —
 * surfaces inconsistently with what the backend actually authorizes, so
 * the UI resolves grants with the same rules the API does.
 */

/** True when ``granted`` satisfies ``required`` (wildcard-aware). */
export function permissionMatches(required: string, granted: string): boolean {
  if (granted === '*') return true
  if (granted.endsWith('.*')) {
    // Keep the trailing dot: "verifactu.*" must not match "verifactu2.x".
    const prefix = granted.slice(0, -1)
    return required.startsWith(prefix)
  }
  return granted === required
}

/** True when any grant in ``granted`` satisfies ``required``. */
export function isGranted(required: string, grantedList: readonly string[]): boolean {
  return grantedList.some(granted => permissionMatches(required, granted))
}
