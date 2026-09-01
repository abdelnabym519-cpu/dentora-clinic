import { test, expect, type Page } from './_fixtures'

/**
 * Dental 3D nerve detection safety contract (Phase 5.2).
 *
 * Exercises the real CBCT-provider boundary without invoking a model:
 * seeded patients intentionally have no validated CBCT series, so the
 * product must persist and display an explicit non-reviewable failure,
 * never substitute demo anatomy or fabricate tooth proximity. RBAC
 * boundaries remain covered at both the UI and API layers.
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

test.describe('dental 3D — nerve detection Phase 5.2 safety contract', () => {
  test.use({ role: 'admin' })

  test('run without validated CBCT fails safely without anatomy or review', async ({ loggedIn }) => {
    const patientId = await getPatientId(loggedIn, 2)
    await loggedIn.goto(`/patients/${patientId}`, { waitUntil: 'domcontentloaded' })
    await loggedIn.waitForURL(/\/patients\/[0-9a-f-]+/, { timeout: 20_000 })

    const section = loggedIn.locator('[data-testid="dental3d-nerve"]')
    await expect(section).toBeVisible({ timeout: 15_000 })

    await loggedIn.locator('[data-testid="dental3d-nerve-run"]').click()

    const failure = loggedIn.locator(
      '[data-testid="dental3d-nerve-model-failure"]'
    )
    await expect(failure).toBeVisible({ timeout: 15_000 })
    await expect(failure).toContainText(
      'No validated CBCT series is available for this patient'
    )

    const counts = loggedIn.locator('[data-testid="dental3d-nerve-counts"]')
    await expect(counts).toContainText('0 pathways')
    await expect(counts).toContainText('0 near')
    await expect(counts).toContainText('0 watch')

    // A failed operation contains no anatomical finding and is not reviewable.
    await expect(loggedIn.locator('[data-testid="dental3d-nerve-near"]')).toHaveCount(0)
    await expect(loggedIn.locator('[data-testid="dental3d-nerve-watch"]')).toHaveCount(0)
    await expect(loggedIn.locator('[data-testid="dental3d-nerve-accept"]')).toHaveCount(0)
    await expect(loggedIn.locator('[data-testid="dental3d-nerve-reject"]')).toHaveCount(0)
    await expect(loggedIn.locator('[data-testid="dental3d-nerve-review-state"]')).toHaveCount(0)

    // Do not misrepresent not_applicable as dentist rejection.
    await expect(
      loggedIn.locator('[data-testid="dental3d-nerve-status"]')
    ).toContainText('Nerve detection could not run right now.')
  })

  test('API persists the no-CBCT result as a non-reviewable failure', async ({ loggedIn }) => {
    const patientId = await getPatientId(loggedIn, 2)
    const headers = await authHeaders(loggedIn)

    const run = await loggedIn.context().request.post(
      `${API_BASE}/api/v1/dental_3d/patients/${patientId}/nerve-detection`,
      { headers }
    )

    expect(run.status()).toBe(201)

    const runBody = (await run.json()) as {
      data: {
        status: string
        provider: string
        method: string
        input_kind: string
        requires_review: boolean
        review_status: string
        pathway_count: number
        near_count: number
        watch_count: number
        failure: {
          code: string
          message: string
        } | null
      }
    }

    expect(runBody.data.status).toBe('failed')
    expect(runBody.data.provider).toBe('cbct-model-service')
    expect(runBody.data.method).toBe('dentora-cbct-http-v1')
    expect(runBody.data.input_kind).toBe('cbct_series')
    expect(runBody.data.requires_review).toBe(false)
    expect(runBody.data.review_status).toBe('not_applicable')
    expect(runBody.data.pathway_count).toBe(0)
    expect(runBody.data.near_count).toBe(0)
    expect(runBody.data.watch_count).toBe(0)
    expect(runBody.data.failure?.code).toBe('invalid_input')
    expect(runBody.data.failure?.message).toBe(
      'No validated CBCT series is available for this patient'
    )

    // The scene summary must persist the same safe outcome.
    const scene = await loggedIn.context().request.get(
      `${API_BASE}/api/v1/dental_3d/patients/${patientId}/scene`,
      { headers }
    )

    expect(scene.ok()).toBeTruthy()

    const sceneBody = (await scene.json()) as {
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

    expect(sceneBody.data.nerve_detection.status).toBe('failed')
    expect(sceneBody.data.nerve_detection.provider).toBe('cbct-model-service')
    expect(sceneBody.data.nerve_detection.review_status).toBe('not_applicable')
    expect(sceneBody.data.nerve_detection.pathway_count).toBe(0)
    expect(sceneBody.data.nerve_detection.near_count).toBe(0)
    expect(sceneBody.data.nerve_detection.non_clinical).toBe(true)
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
