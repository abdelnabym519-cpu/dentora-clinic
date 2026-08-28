/**
 * The user's currently selected clinic id.
 *
 * Persisted in a cookie so it survives reloads and is available during
 * SSR (the API plugin reads it to set the X-Clinic-Id header). The
 * backend resolves the effective clinic + role/permissions from this
 * selection, which is what makes a multi-clinic user see the right data
 * after switching.
 *
 * The auth flow owns *validating* the id against `/auth/me`: on login
 * it defaults to the first membership, and `set()` is called by the
 * clinic switcher / login response.
 */
export function useSelectedClinicId() {
  const clinicId = useCookie<string | null>('clinic_id', {
    maxAge: 60 * 60 * 24 * 30,
    sameSite: 'lax',
    secure: import.meta.env.PROD
  })
  return clinicId
}
