import { expect, test, type Page } from './_fixtures'

const API_BASE = process.env.E2E_API_BASE || 'http://localhost:8000'

async function getPatientId(page: Page, pick: number = 0): Promise<string> {
  const token = (await page.context().cookies()).find(c => c.name === 'access_token')?.value
  const response = await page.context().request.get(
    `${API_BASE}/api/v1/patients?page=1&page_size=5`,
    { headers: token ? { Authorization: `Bearer ${token}` } : {} }
  )
  if (!response.ok()) throw new Error(`patient list failed: ${response.status()}`)
  const body = (await response.json()) as { data: Array<{ id: string }> }
  const id = body.data[pick]?.id
  if (!id) throw new Error(`no seeded patient at index ${pick} available`)
  return id
}

async function authHeaders(page: Page): Promise<Record<string, string>> {
  const token = (await page.context().cookies()).find(c => c.name === 'access_token')?.value
  return token ? { Authorization: `Bearer ${token}` } : {}
}

function binaryStl(): Buffer {
  const buffer = Buffer.alloc(84 + 50)
  buffer.writeUInt32LE(1, 80)

  let offset = 84
  const writeFloat = (value: number) => {
    buffer.writeFloatLE(value, offset)
    offset += 4
  }

  writeFloat(0)
  writeFloat(0)
  writeFloat(1)
  writeFloat(0)
  writeFloat(0)
  writeFloat(0)
  writeFloat(10)
  writeFloat(0)
  writeFloat(0)
  writeFloat(0)
  writeFloat(10)
  writeFloat(0)
  buffer.writeUInt16LE(0, offset)
  return buffer
}

async function sceneMeshCount(page: Page, patientId: string): Promise<number> {
  const response = await page.context().request.get(
    `${API_BASE}/api/v1/dental_3d/patients/${patientId}/scene`,
    { headers: await authHeaders(page) }
  )
  expect(response.ok(), `scene request failed: ${response.status()}`).toBeTruthy()
  const body = (await response.json()) as { data: { meshes: unknown[] } }
  return body.data.meshes.length
}

test.describe('dental 3D — patient summary card', () => {
  test.use({ role: 'admin' })

  test('card fails closed without registered patient-space geometry', async ({ loggedIn }) => {
    const patientId = await getPatientId(loggedIn)
    await loggedIn.goto(`/patients/${patientId}`, { waitUntil: 'domcontentloaded' })
    await loggedIn.waitForURL(/\/patients\/[0-9a-f-]+/, { timeout: 20_000 })

    const card = loggedIn.getByTestId('dental3d-card')
    await expect(card).toBeVisible({ timeout: 15_000 })
    await expect(loggedIn.getByTestId('dental3d-clinical-scene-empty').first()).toBeVisible({
      timeout: 15_000
    })
    await expect(card.getByText(/synthetic geometry is not shown/i).first()).toBeVisible()
    await expect(loggedIn.getByTestId('dental3d-tres-canvas')).toHaveCount(0)
    await expect(loggedIn.getByTestId('implant-planning-alignment-required')).toBeVisible()
  })
})

test.describe('dental 3D — real mesh ingestion', () => {
  test.use({ role: 'admin' })

  test('uploaded STL remains fail-closed until patient-space alignment is accepted', async ({
    loggedIn
  }) => {
    const patientId = await getPatientId(loggedIn, 1)
    const upload = await loggedIn.context().request.post(
      `${API_BASE}/api/v1/dental_3d/patients/${patientId}/meshes`,
      {
        headers: await authHeaders(loggedIn),
        multipart: {
          file: { name: 'scan-e2e.stl', mimeType: 'model/stl', buffer: binaryStl() }
        }
      }
    )
    expect(upload.ok(), `mesh upload failed: ${upload.status()}`).toBeTruthy()

    await loggedIn.goto(`/patients/${patientId}`, { waitUntil: 'domcontentloaded' })
    await loggedIn.waitForURL(/\/patients\/[0-9a-f-]+/, { timeout: 20_000 })

    const card = loggedIn.getByTestId('dental3d-card')
    await expect(card).toBeVisible({ timeout: 15_000 })
    await expect(loggedIn.getByTestId('dental3d-mesh-count')).toBeVisible({ timeout: 15_000 })
    await expect(loggedIn.getByTestId('dental3d-clinical-scene-empty').first()).toBeVisible({
      timeout: 15_000
    })
    await expect(loggedIn.getByTestId('dental3d-tres-canvas')).toHaveCount(0)
    await expect(card.getByText(/synthetic geometry is not shown/i).first()).toBeVisible()
  })

  test('invalid mesh upload fails closed without mutating the scene', async ({ loggedIn }) => {
    const patientId = await getPatientId(loggedIn)
    const before = await sceneMeshCount(loggedIn, patientId)

    const response = await loggedIn.context().request.post(
      `${API_BASE}/api/v1/dental_3d/patients/${patientId}/meshes`,
      {
        headers: await authHeaders(loggedIn),
        multipart: {
          file: {
            name: 'invalid-e2e.stl',
            mimeType: 'model/stl',
            buffer: Buffer.from('not-a-valid-stl')
          }
        }
      }
    )

    expect(response.status()).toBe(400)
    expect(await sceneMeshCount(loggedIn, patientId)).toBe(before)

    await loggedIn.goto(`/patients/${patientId}`, { waitUntil: 'domcontentloaded' })
    await loggedIn.waitForURL(/\/patients\/[0-9a-f-]+/, { timeout: 20_000 })
    await expect(loggedIn.getByTestId('dental3d-clinical-scene-empty').first()).toBeVisible({
      timeout: 15_000
    })
    await expect(loggedIn.getByTestId('dental3d-tres-canvas')).toHaveCount(0)
  })
})
