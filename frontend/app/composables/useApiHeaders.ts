/**
 * Headers for the requests that cannot go through `useApi` — blob and
 * array-buffer downloads, SSE streams, `<img>` thumbnails fetched as blobs.
 *
 * They still have to carry the clinic selection. Without `X-Clinic-Id` the
 * backend falls back to the user's alphabetically-first membership, so a
 * multi-clinic user silently resolves *another* clinic's context: the role —
 * and therefore the permission check — comes from a clinic they are not
 * working in, and a document generated per clinic (invoice/budget PDF,
 * accounting export) is rendered with the wrong letterhead.
 *
 * Pass any additional headers (`Content-Type`, `Accept`) as `extra`.
 */
export function useApiHeaders() {
  const auth = useAuth()
  const selectedClinicId = useSelectedClinicId()

  return function apiHeaders(extra: Record<string, string> = {}): Record<string, string> {
    const headers: Record<string, string> = { ...extra }
    if (auth.accessToken.value) {
      headers.Authorization = `Bearer ${auth.accessToken.value}`
    }
    if (selectedClinicId.value) {
      headers['X-Clinic-Id'] = selectedClinicId.value
    }
    return headers
  }
}
