import { test, expect, type Page } from './_fixtures'

/**
 * Dental 3D guardrail: module cards must surface through the patient
 * Summary for roles with `dental_3d.read`, remain hidden otherwise,
 * and never render unregistered IOS/synthetic geometry in the clinical
 * ThreeUI path.
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

  test('cards surface and fail closed without registered patient geometry', async ({ loggedIn }) => {
    const patientId = await getPatientId(loggedIn)
    await loggedIn.goto(`/patients/${patientId}`, { waitUntil: 'domcontentloaded' })
    await loggedIn.waitForURL(/\/patients\/[0-9a-f-]+/, { timeout: 20_000 })

    const card = loggedIn.locator('[data-testid="dental3d-card"]')
    await expect(card).toBeVisible({ timeout: 15_000 })

    await expect(
      loggedIn.locator('[data-testid="dental3d-clinical-scene-empty"]').first()
    ).toBeVisible({ timeout: 15_000 })
    await expect(
      loggedIn.getByText(/synthetic geometry is not shown/i).first()
    ).toBeVisible()
    await expect(loggedIn.locator('[data-testid="dental3d-tres-canvas"]')).toHaveCount(0)

    await expect(
      loggedIn.locator('[data-testid="dental3d-implant-planning"]')
    ).toBeVisible({ timeout: 15_000 })
    await expect(
      loggedIn.locator('[data-testid="implant-planning-alignment-required"]')
    ).toBeVisible()
  })
})

test.describe('dental 3D — real mesh ingestion', () => {
  test.use({ role: 'admin' })

  test('uploaded STL remains unrendered until patient-space registration is accepted', async ({ loggedIn }) => {
    const patientId = await getPatientId(loggedIn, 1)

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

    const content = await loggedIn.context().request.get(`${API_BASE}${mesh.url}`, {
      headers: await authHeaders(loggedIn)
    })
    expect(content.ok(), `mesh download failed: ${content.status()}`).toBeTruthy()

    await loggedIn.goto(`/patients/${patientId}`, { waitUntil: 'domcontentloaded' })
    await loggedIn.waitForURL(/\/patients\/[0-9a-f-]+/, { timeout: 20_000 })

    await expect(loggedIn.locator('[data-testid="dental3d-card"]')).toBeVisible({ timeout: 15_000 })
    await expect(loggedIn.locator('[data-testid="dental3d-mesh-count"]')).toBeVisible({
      timeout: 15_000
    })
    await expect(
      loggedIn.locator('[data-testid="dental3d-clinical-scene-empty"]').first()
    ).toBeVisible({ timeout: 15_000 })
    await expect(loggedIn.locator('[data-testid="dental3d-tres-canvas"]')).toHaveCount(0)
    await expect(loggedIn.locator('[data-testid="dental3d-mesh-error"]')).toHaveCount(0)
  })

  test('invalid mesh uploads are rejected by the API', async ({ loggedIn }) => {
    const patientId = await getPatientId(loggedIn)
    const rejection = await loggedIn.context().request.post(
      `${API_BASE}/api/v1/dental_3d/patients/${patientId}/meshes`,
      {
        headers: await authHeaders(loggedIn),
        multipart: {
          file: {
            name: 'not-a-mesh.fbx',
            mimeType: 'application/octet-stream',
            buffer: Buffer.from('nope')
          }
        }
      }
    )
    expect(rejection.status()).toBe(400)
  })
})

test.describe('dental 3D — receptionist permission boundary', () => {
  test.use({ role: 'receptionist' })

  test('dental 3D cards are hidden for receptionists', async ({ loggedIn }) => {
    const patientId = await getPatientId(loggedIn)
    await loggedIn.goto(`/patients/${patientId}`, { waitUntil: 'domcontentloaded' })
    await loggedIn.waitForURL(/\/patients\/[0-9a-f-]+/, { timeout: 20_000 })

    await expect(loggedIn.locator('[data-testid="dental3d-card"]')).toHaveCount(0)
    await expect(loggedIn.locator('[data-testid="dental3d-implant-planning"]')).toHaveCount(0)
  })
})
