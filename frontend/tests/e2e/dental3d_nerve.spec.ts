import { test, expect, type Page } from './_fixtures'

/**
 * Dental 3D nerve detection foundation (Phase 4, ADR 0022).
 *
 * Exercises the full AI-assisted / simulated workflow through the
 * product UI: run the canonical-model analysis from the patient
 * summary card, see the pathway summary and AI-estimated proximities,
 * review it as a dentist, and verify the RBAC boundary — write actions
 * are denied for read-only roles at both the UI and API layers.
 *
 * Preconditions: demo users seeded (admin@demo.clinic / demo1234) and
 * the dental_3d layer loaded (CI regenerates modules.json).
 *
 * Note: the WebGL canvas itself is environment-blocked in this sandbox
 * (no GPU/SwiftShader WebGL context) — pathway *rendering* is covered
 * by the nerveView unit tests; this spec covers the workflow, API
 * contract and permissions.
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

test.describe('dental 3D — nerve detection foundation', () => {
  test.use({ role: 'admin' })

  test('run → proximity evidence → dentist review workflow', async ({ loggedIn }) => {
    const patientId = await getPatientId(loggedIn, 2)
    await loggedIn.goto(`/patients/${patientId}`, { waitUntil: 'domcontentloaded' })
    await loggedIn.waitForURL(/\/patients\/[0-9a-f-]+/, { timeout: 20_000 })

    // 1. The nerve section surfaces on the card.
    const section = loggedIn.locator('[data-testid="dental3d-nerve"]')
    await expect(section).toBeVisible({ timeout: 15_000 })

    // 2. Run the (AI-assisted / simulated) analysis.
    await loggedIn.locator('[data-testid="dental3d-nerve-run"]').click()
    const counts = loggedIn.locator('[data-testid="dental3d-nerve-counts"]')
    await expect(counts).toBeVisible({ timeout: 15_000 })
    await expect(counts).toContainText('2 pathways')
    await expect(counts).toContainText('4 near')
    await expect(counts).toContainText('6 watch')

    // 3. Safety wording is fixed: simulated + requires verification.
    await expect(section).toContainText('requires dentist verification')

    // 4. Proximity evidence: near FDI teeth, explicitly AI-estimated.
    const near = loggedIn.locator('[data-testid="dental3d-nerve-near"]')
    await expect(near).toBeVisible()
    await expect(near).toContainText('37, 38, 47, 48')
    await expect(near).toContainText('AI-estimated proximity')

    // 5. The overlay toggle is available once an analysis exists.
    await expect(loggedIn.locator('[data-testid="dental3d-nerve-toggle"]')).toBeVisible()

    // 6. Dentist review: accept, then the decision is terminal.
    await loggedIn.locator('[data-testid="dental3d-nerve-accept"]').click()
    const reviewState = loggedIn.locator('[data-testid="dental3d-nerve-review-state"]')
    await expect(reviewState).toBeVisible({ timeout: 10_000 })
    await expect(reviewState).toContainText('verified — accepted')
    await expect(loggedIn.locator('[data-testid="dental3d-nerve-accept"]')).toHaveCount(0)
  })

  test('scene API reports the reviewed nerve summary', async ({ loggedIn }) => {
    const patientId = await getPatientId(loggedIn, 2)
    const headers = await authHeaders(loggedIn)
    const res = await loggedIn.context().request.get(
      `${API_BASE}/api/v1/dental_3d/patients/${patientId}/scene`,
      { headers }
    )
    expect(res.ok()).toBeTruthy()
    const body = (await res.json()) as {
      data: {
        nerve_detection: {
          status: string
          provider: string
          review_status: string
          pathway_count: number
          near_count: number
          non_clinical: boolean
        }
      }
    }
    expect(body.data.nerve_detection.status).toBe('completed')
    expect(body.data.nerve_detection.provider).toBe('canonical-mandible')
    expect(body.data.nerve_detection.review_status).toBe('accepted')
    expect(body.data.nerve_detection.pathway_count).toBe(2)
    expect(body.data.nerve_detection.near_count).toBe(4)
    expect(body.data.nerve_detection.non_clinical).toBe(true)
  })
})

test.describe('dental 3D — nerve RBAC boundary (assistant, read-only)', () => {
  test.use({ role: 'assistant' })

  test('read-only role sees status but cannot run or review', async ({ loggedIn }) => {
    const patientId = await getPatientId(loggedIn, 2)
    await loggedIn.goto(`/patients/${patientId}`, { waitUntil: 'domcontentloaded' })
    await loggedIn.waitForURL(/\/patients\/[0-9a-f-]+/, { timeout: 20_000 })

    // The card + nerve section are visible for readers…
    await expect(loggedIn.locator('[data-testid="dental3d-nerve"]')).toBeVisible({
      timeout: 15_000
    })
    // …but write affordances never render.
    await expect(loggedIn.locator('[data-testid="dental3d-nerve-run"]')).toHaveCount(0)
    await expect(loggedIn.locator('[data-testid="dental3d-nerve-accept"]')).toHaveCount(0)

    // …and the API refuses write actions outright.
    const headers = await authHeaders(loggedIn)
    const run = await loggedIn.context().request.post(
      `${API_BASE}/api/v1/dental_3d/patients/${patientId}/nerve-detection`,
      { headers }
    )
    expect(run.status()).toBe(403)
  })
})

test.describe('dental 3D — nerve RBAC boundary (receptionist, no access)', () => {
  test.use({ role: 'receptionist' })

  test('role without dental_3d.read gets no card and API 403', async ({ loggedIn }) => {
    const patientId = await getPatientId(loggedIn, 0)
    await loggedIn.goto(`/patients/${patientId}`, { waitUntil: 'domcontentloaded' })
    await loggedIn.waitForURL(/\/patients\/[0-9a-f-]+/, { timeout: 20_000 })

    await expect(loggedIn.locator('[data-testid="dental3d-card"]')).toHaveCount(0)

    const headers = await authHeaders(loggedIn)
    const read = await loggedIn.context().request.get(
      `${API_BASE}/api/v1/dental_3d/patients/${patientId}/nerve-detection`,
      { headers }
    )
    expect(read.status()).toBe(403)
    const write = await loggedIn.context().request.post(
      `${API_BASE}/api/v1/dental_3d/patients/${patientId}/nerve-detection`,
      { headers }
    )
    expect(write.status()).toBe(403)
  })
})
