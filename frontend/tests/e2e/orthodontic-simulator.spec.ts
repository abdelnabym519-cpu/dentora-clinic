import { test, expect, type Page } from './_fixtures'

const API_BASE = process.env.E2E_API_BASE || 'http://localhost:8000'

async function getPatientId(page: Page): Promise<string> {
  const token = (await page.context().cookies()).find(cookie => cookie.name === 'access_token')?.value
  const response = await page.context().request.get(`${API_BASE}/api/v1/patients?page=1&page_size=5`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {}
  })
  if (!response.ok()) throw new Error(`patient list failed: ${response.status()}`)
  const body = (await response.json()) as { data: Array<{ id: string }> }
  const patientId = body.data[0]?.id
  if (!patientId) throw new Error('no seeded patient available')
  return patientId
}

async function authHeaders(page: Page): Promise<Record<string, string>> {
  const token = (await page.context().cookies()).find(cookie => cookie.name === 'access_token')?.value
  return token ? { Authorization: `Bearer ${token}` } : {}
}

test.describe('orthodontic simulator — fail-closed patient UI', () => {
  test.use({ role: 'admin' })

  test('surfaces the independent card and locks patient movement without reviewed per-tooth geometry', async ({ loggedIn }) => {
    const patientId = await getPatientId(loggedIn)
    await loggedIn.goto(`/patients/${patientId}`, { waitUntil: 'domcontentloaded' })
    await loggedIn.waitForURL(/\/patients\/[0-9a-f-]+/, { timeout: 20_000 })

    const card = loggedIn.locator('[data-testid="orthodontic-simulator-card"]')
    await expect(card).toBeVisible({ timeout: 15_000 })
    await expect(loggedIn.locator('[data-testid="orthodontic-simulator-headline"]')).toContainText(/geometry safety gate|checking patient geometry/i)

    // Patient movement controls fail closed. Selection/navigation remains available.
    await expect(loggedIn.locator('[data-testid="ortho-x"]')).toBeDisabled()
    await expect(loggedIn.locator('[data-testid="ortho-y"]')).toBeDisabled()
    await expect(loggedIn.locator('[data-testid="ortho-z"]')).toBeDisabled()
    await expect(loggedIn.locator('[data-testid="ortho-tip"]')).toBeDisabled()
    await expect(loggedIn.locator('[data-testid="ortho-torque"]')).toBeDisabled()
    await expect(loggedIn.locator('[data-testid="ortho-rotation"]')).toBeDisabled()
    await expect(loggedIn.locator('[data-testid="ortho-run"]')).toBeDisabled()
    await expect(loggedIn.locator('[data-testid="ortho-play"]')).toBeDisabled()
    await expect(loggedIn.locator('[data-testid="ortho-stage-slider"]')).toBeDisabled()
    await expect(loggedIn.locator('[data-testid="ortho-mode-after"]')).toBeDisabled()
    await expect(loggedIn.locator('[data-testid="ortho-mode-overlay"]')).toBeDisabled()

    await expect(loggedIn.locator('[data-testid="ortho-selected-fdi"]')).toContainText('11')
    await loggedIn.locator('[data-testid="ortho-lower-jaw"]').click()
    await expect(loggedIn.locator('[data-testid="ortho-selected-fdi"]')).toContainText('41')

    await expect(card.getByText(/schematic navigation only/i)).toBeVisible()
    await expect(card.getByText(/not a clinical prediction/i)).toBeVisible()
  })

  test('capability API is explicitly non-clinical and simulation cannot bypass server-owned geometry', async ({ loggedIn }) => {
    const patientId = await getPatientId(loggedIn)
    const headers = await authHeaders(loggedIn)

    const capabilityResponse = await loggedIn.context().request.get(
      `${API_BASE}/api/v1/orthodontic_simulator/patients/${patientId}/capability`,
      { headers }
    )
    expect(capabilityResponse.ok(), `capability failed: ${capabilityResponse.status()}`).toBeTruthy()
    const capability = ((await capabilityResponse.json()) as {
      data: {
        translation_eligible: boolean
        rotation_eligible: boolean
        clinical_prediction: boolean
        treatment_approval: boolean
      }
    }).data
    expect(capability.translation_eligible).toBe(false)
    expect(capability.rotation_eligible).toBe(false)
    expect(capability.clinical_prediction).toBe(false)
    expect(capability.treatment_approval).toBe(false)

    const simulation = await loggedIn.context().request.post(
      `${API_BASE}/api/v1/orthodontic_simulator/patients/${patientId}/simulate`,
      {
        headers,
        data: {
          movements: [{
            tooth: { value: '11', system: 'FDI' },
            translate_x_mm: 0.1,
            translate_y_mm: 0,
            translate_z_mm: 0,
            rotate_tip_deg: 0,
            rotate_torque_deg: 0,
            rotate_rotation_deg: 0
          }]
        }
      }
    )
    expect(simulation.status()).toBe(409)
    expect((await simulation.json()).message).toMatch(/reviewed per-tooth geometry/i)
  })
})

test.describe('orthodontic simulator — receptionist boundary', () => {
  test.use({ role: 'receptionist' })

  test('card is not exposed without orthodontic_simulator.read', async ({ loggedIn }) => {
    const patientId = await getPatientId(loggedIn)
    await loggedIn.goto(`/patients/${patientId}`, { waitUntil: 'domcontentloaded' })
    await loggedIn.waitForURL(/\/patients\/[0-9a-f-]+/, { timeout: 20_000 })
    await expect(loggedIn.locator('[data-testid="orthodontic-simulator-card"]')).toHaveCount(0)
  })
})
