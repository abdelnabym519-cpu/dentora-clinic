import { test, expect, type Page } from './_fixtures'

/**
 * Dental 3D segmentation foundation (Phase 3, ADR 0021).
 *
 * Exercises the full non-clinical workflow through the product UI:
 * run the analysis from the patient summary card, see the per-tooth
 * evidence (counts + uncertain FDI numbers), review it as a dentist,
 * and verify the RBAC boundary — write actions are denied for
 * read-only roles at both the UI and API layers.
 *
 * Preconditions: demo users seeded (admin@demo.clinic / demo1234) and
 * the dental_3d layer loaded (CI regenerates modules.json).
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

function authHeaders(page: Page): Promise<Record<string, string>> {
  return page.context().cookies().then((cookies) => {
    const token = cookies.find(c => c.name === 'access_token')?.value
    return token ? { Authorization: `Bearer ${token}` } : {}
  })
}

test.describe('dental 3D — segmentation foundation', () => {
  test.use({ role: 'admin' })

  test('run → evidence → dentist review workflow', async ({ loggedIn }) => {
    // Third seeded patient: keep the mesh-ingestion spec's patients
    // independent of segmentation state.
    const patientId = await getPatientId(loggedIn, 2)
    await loggedIn.goto(`/patients/${patientId}`, { waitUntil: 'domcontentloaded' })
    await loggedIn.waitForURL(/\/patients\/[0-9a-f-]+/, { timeout: 20_000 })

    // 1. The segmentation section surfaces on the card.
    const section = loggedIn.locator('[data-testid="dental3d-segmentation"]')
    await expect(section).toBeVisible({ timeout: 15_000 })

    // 2. Run the analysis (server-side provider) and see the evidence:
    //    counts over the full dentition + the non-clinical labelling.
    await loggedIn.locator('[data-testid="dental3d-segmentation-run"]').click()
    const counts = loggedIn.locator('[data-testid="dental3d-segmentation-counts"]')
    await expect(counts).toBeVisible({ timeout: 15_000 })
    await expect(counts).toContainText(/32 segmented/i)
    await expect(section).toContainText(/non-clinical decision support/i)

    // 3. Review state: pending → accept → reviewed.
    await expect(
      loggedIn.locator('[data-testid="dental3d-segmentation-accept"]')
    ).toBeVisible()
    await loggedIn.locator('[data-testid="dental3d-segmentation-accept"]').click()
    const reviewState = loggedIn.locator('[data-testid="dental3d-segmentation-review-state"]')
    await expect(reviewState).toBeVisible({ timeout: 10_000 })
    await expect(reviewState).toContainText(/accepted/i)
    // Decided analyses offer no further review actions.
    await expect(
      loggedIn.locator('[data-testid="dental3d-segmentation-accept"]')
    ).toHaveCount(0)
  })

  test('scene API reports the reviewed segmentation summary', async ({ loggedIn }) => {
    const patientId = await getPatientId(loggedIn, 2)
    const res = await loggedIn.context().request.get(
      `${API_BASE}/api/v1/dental_3d/patients/${patientId}/scene`,
      { headers: await authHeaders(loggedIn) }
    )
    expect(res.ok()).toBeTruthy()
    const scene = (await res.json()) as {
      data: {
        segmentation: {
          status: string
          provider: string
          review_status: string
          segmented_count: number
          non_clinical: boolean
        }
      }
    }
    expect(scene.data.segmentation.status).toBe('completed')
    expect(scene.data.segmentation.provider).toBe('arch-partition')
    expect(scene.data.segmentation.review_status).toBe('accepted')
    expect(scene.data.segmentation.segmented_count).toBe(32)
    expect(scene.data.segmentation.non_clinical).toBe(true)
  })
})

test.describe('dental 3D — segmentation RBAC boundary (assistant, read-only)', () => {
  test.use({ role: 'assistant' })

  test('read-only role sees status but cannot run or review', async ({ loggedIn }) => {
    const patientId = await getPatientId(loggedIn, 0)
    await loggedIn.goto(`/patients/${patientId}`, { waitUntil: 'domcontentloaded' })
    await loggedIn.waitForURL(/\/patients\/[0-9a-f-]+/, { timeout: 20_000 })

    const section = loggedIn.locator('[data-testid="dental3d-segmentation"]')
    await expect(section).toBeVisible({ timeout: 15_000 })
    // No Run button, no review actions for read-only roles.
    await expect(loggedIn.locator('[data-testid="dental3d-segmentation-run"]')).toHaveCount(0)
    await expect(loggedIn.locator('[data-testid="dental3d-segmentation-accept"]')).toHaveCount(0)

    // The API layer enforces the same boundary (403, not just hidden UI).
    const headers = await authHeaders(loggedIn)
    const run = await loggedIn.context().request.post(
      `${API_BASE}/api/v1/dental_3d/patients/${patientId}/segmentation`,
      { headers }
    )
    expect(run.status()).toBe(403)
  })
})

test.describe('dental 3D — segmentation RBAC boundary (receptionist, no access)', () => {
  test.use({ role: 'receptionist' })

  test('role without dental_3d.read gets no card and API 403', async ({ loggedIn }) => {
    const patientId = await getPatientId(loggedIn, 0)
    await loggedIn.goto(`/patients/${patientId}`, { waitUntil: 'domcontentloaded' })
    await loggedIn.waitForURL(/\/patients\/[0-9a-f-]+/, { timeout: 20_000 })

    await expect(loggedIn.locator('[data-testid="dental3d-card"]')).toHaveCount(0)
    const headers = await authHeaders(loggedIn)
    const list = await loggedIn.context().request.get(
      `${API_BASE}/api/v1/dental_3d/patients/${patientId}/segmentation`,
      { headers }
    )
    expect(list.status()).toBe(403)
    const run = await loggedIn.context().request.post(
      `${API_BASE}/api/v1/dental_3d/patients/${patientId}/segmentation`,
      { headers }
    )
    expect(run.status()).toBe(403)
  })
})
