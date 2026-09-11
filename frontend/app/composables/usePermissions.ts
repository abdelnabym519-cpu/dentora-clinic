import { PERMISSIONS } from '~/config/permissions'
import { isGranted } from '~/utils/permissions'

export function usePermissions() {
  const auth = useAuth()
  const permissions = computed<readonly string[]>(() => auth.permissions.value ?? [])

  // Wildcard-aware, mirroring the backend's ``permission_matches`` — see
  // ``~/utils/permissions``. Exact matching alone silently disagrees with
  // the API whenever a grant list still carries ``*`` / ``module.*``.
  function can(permission: string): boolean {
    return isGranted(permission, permissions.value)
  }

  function canAny(perms: string[]): boolean {
    return perms.some(p => isGranted(p, permissions.value))
  }

  function canAll(perms: string[]): boolean {
    return perms.every(p => isGranted(p, permissions.value))
  }

  const isAdmin = computed(() => can(PERMISSIONS.users.write))

  return {
    permissions: readonly(permissions),
    can,
    canAny,
    canAll,
    isAdmin
  }
}
