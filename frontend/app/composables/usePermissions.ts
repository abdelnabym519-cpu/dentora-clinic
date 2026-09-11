import { PERMISSIONS } from '~/config/permissions'

export function usePermissions() {
  const auth = useAuth()
  const permissions = computed<readonly string[]>(() => auth.permissions.value ?? [])

  // Mirrors backend permissions.permission_matches(): "*" grants
  // everything, "module.*" grants every module permission. The backend
  // enforcement already expands wildcards; without this mirror the UI
  // hides surfaces the backend actually allows (and vice versa).
  function permissionMatches(required: string, granted: string): boolean {
    if (granted === '*') return true
    if (granted.endsWith('.*')) {
      const prefix = granted.slice(0, -1) // keep trailing dot
      return required.startsWith(prefix)
    }
    return granted === required
  }

  function can(permission: string): boolean {
    return permissions.value.some(granted => permissionMatches(permission, granted))
  }

  function canAny(perms: string[]): boolean {
    return perms.some(p => permissions.value.some(granted => permissionMatches(p, granted)))
  }

  function canAll(perms: string[]): boolean {
    return perms.every(p => permissions.value.some(granted => permissionMatches(p, granted)))
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
