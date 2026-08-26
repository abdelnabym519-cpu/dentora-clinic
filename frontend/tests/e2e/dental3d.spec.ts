import { test, expect, type Page } from './_fixtures'

/**
 * Dental 3D guardrail: the module's card must surface through the
 * patient Summary (its intended UI location) for roles that hold
 * `dental_3d.read`, and must stay hidden for roles that do not.
 *
 * Preconditions (same as the periodontogram spec): demo users seeded
 * (`admin@demo.clinic` / `demo1234`) and the dental_3d layer loaded —
 * the CI e2e job regenerates `modules.json` with every module layer.
 * The router is mounted for every discovered module, so the scene API
 * answers regardless of install state.
 */

const API_BASE = process.env.E2E_API_BASE || 'http://localhost:8000'

async function getPatientId(page: Page, pick: number = 0): Promise<string> {
  const ctx = page.context()
  const cookies = await ctx.cookies()
  const token = cookies.find(c => c.name === 'access_token')?.value
  const res = await ctx.request.get(`${API_BASE}/api/v1/patients?page=1&page_size=5`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {}
  })
  if (!res.ok()) throw new Error(`patient list failed: ${res.status()}`)
  const body = (await res.json()) as { data: Array<{ id: string }> }
  const id = body.data[pick]?.id
  if (!id) throw new Error(`no seeded patient at index ${pick} available`)
  return id
}

async function authHeaders(page: Page): Promise<Record<string, string>> {
  const token = (await page.context().cookies()).find(c => c.name === 'access_token')?.value
  return token ? { Authorization: `Bearer ${token}` } : {}
}

/** Minimal valid binary STL (80-byte header + triangle count + facets). */
function binaryStl(triangles = 4): Buffer {
  const header = Buffer.alloc(80, 0)
  header.write('dental3d-e2e-scan', 0, 'ascii')
  const count = Buffer.alloc(4)
  count.writeUInt32LE(triangles, 0)
  return Buffer.concat([header, count, Buffer.alloc(50 * triangles, 0)])
}

test.describe('dental 3D — patient summary card', () => {
  test.use({ role: 'admin' })

  test('card + viewer surface on the patient summary', async ({ loggedIn }) => {
    const patientId = await getPatientId(loggedIn)
    await loggedIn.goto(`/patients/${patientId}`, { waitUntil: 'domcontentloaded' })
    await loggedIn.waitForURL(/\/patients\/[0-9a-f-]+/, { timeout: 20_000 })

    // 1. The card renders in the summary grid.
    const card = loggedIn.locator('[data-testid="dental3d-card"]')
    await expect(card).toBeVisible({ timeout: 15_000 })

    // 2. The viewer mounts client-side: either the WebGL canvas or the
    //    explicit WebGL-unavailable fallback (deterministic either way).
    const canvas = loggedIn.locator('[data-testid="dental3d-canvas"]')
    const fallback = loggedIn.locator('[data-testid="dental3d-webgl-fallback"]')
    await expect(canvas.or(fallback)).toBeVisible({ timeout: 15_000 })

    // 3. The synthetic-geometry disclaimer stays visible by design.
    await expect(
      loggedIn.getByText(/synthetic demo geometry|geometría sintética/i).first()
    ).toBeVisible()
  })
})

test.describe('dental 3D — real mesh ingestion', () => {
  test.use({ role: 'admin' })

  test('uploaded STL renders as scan geometry with a synthetic fallback contract', async ({ loggedIn }) => {
    // Second seeded patient: uploads persist across runs, and the
    // synthetic-disclaimer test above must keep seeing a mesh-free
    // first patient.
    const patientId = await getPatientId(loggedIn, 1)

    // 1. Ingest a real mesh through the module API (storage via media).
    const upload = await loggedIn.context().request.post(
      `${API_BASE}/api/v1/dental_3d/patients/${patientId}/meshes`,
      {
        headers: await authHeaders(loggedIn),
        multipart: {
          file: { name: 'e2e-scan.stl', mimeType: 'model/stl', buffer: binaryStl() }
        }
      }
    )
    expect(upload.ok(), `mesh upload failed: ${upload.status()}`).toBeTruthy()
    const mesh = ((await upload.json()) as { data: { document_id: string, url: string } }).data
    expect(mesh.url).toContain(`/api/v1/media/documents/${mesh.document_id}/download`)

    // 2. The mesh content downloads through media's authorized route.
    const content = await loggedIn.context().request.get(`${API_BASE}${mesh.url}`, {
      headers: await authHeaders(loggedIn)
    })
    expect(content.ok(), `mesh download failed: ${content.status()}`).toBeTruthy()

    // 3. The card surfaces scan geometry: mesh count + viewer badge
    //    (WebGL canvas — swiftshader in CI) and the scan disclaimer.
    await loggedIn.goto(`/patients/${patientId}`, { waitUntil: 'domcontentloaded' })
    await loggedIn.waitForURL(/\/patients\/[0-9a-f-]+/, { timeout: 20_000 })

    await expect(loggedIn.locator('[data-testid="dental3d-card"]')).toBeVisible({ timeout: 15_000 })
    await expect(loggedIn.locator('[data-testid="dental3d-mesh-count"]')).toBeVisible({
      timeout: 15_000
    })
    await expect(loggedIn.locator('[data-testid="dental3d-canvas"]')).toBeVisible({
      timeout: 15_000
    })
    await expect(loggedIn.locator('[data-testid="dental3d-mesh-badge"]')).toBeVisible({
      timeout: 15_000
    })

    // 4. Loading must have settled without the error state.
    await expect(loggedIn.locator('[data-testid="dental3d-mesh-error"]')).toHaveCount(0)
    await expect(
      loggedIn.getByText(/scan geometry for visualization|geometr.de escaneo/i).first()
    ).toBeVisible()
  })

  test('invalid mesh uploads are rejected by the API', async ({ loggedIn }) => {
    const patientId = await getPatientId(loggedIn)
    const rejection = await loggedIn.context().request.post(
      `${API_BASE}/api/v1/dental_3d/patients/${patientId}/meshes`,
      {
        headers: await authHeaders(loggedIn),
        multipart: {
          file: { name: 'not-a-mesh.ply', mimeType: 'application/octet-stream', buffer: Buffer.from('nope') }
        }
      }
    )
    expect(rejection.status()).toBe(400)
  })
})

test.describe('dental 3D — receptionist permission boundary', () => {
  test.use({ role: 'receptionist' })

  test('card is hidden for receptionists', async ({ loggedIn }) => {
    const patientId = await getPatientId(loggedIn)
    await loggedIn.goto(`/patients/${patientId}`, { waitUntil: 'domcontentloaded' })
    await loggedIn.waitForURL(/\/patients\/[0-9a-f-]+/, { timeout: 20_000 })

    // No dental_3d.read grant → the slot resolves to zero entries.
    await expect(loggedIn.locator('[data-testid="dental3d-card"]')).toHaveCount(0)
  })
})
