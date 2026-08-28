import { test, expect } from './_fixtures'

const API_BASE = process.env.E2E_API_BASE || 'http://127.0.0.1:8000'

test.use({ role: 'dentist' })

test('dentist creates and issues an immutable electronic prescription', async ({ loggedIn: page }) => {
  const token = (await page.context().cookies()).find(cookie => cookie.name === 'access_token')?.value
  expect(token).toBeTruthy()
  const response = await page.request.get(`${API_BASE}/api/v1/patients?page_size=1`, {
    headers: { Authorization: `Bearer ${token}` }
  })
  expect(response.ok()).toBeTruthy()
  const body = await response.json() as { data: Array<{ id: string, first_name: string, last_name: string }> }
  expect(body.data.length).toBeGreaterThan(0)
  const patient = body.data[0]

  await page.goto('/prescriptions')
  const prescriptionsPage = page.getByTestId('prescriptions-page')
  await expect(prescriptionsPage).toBeVisible()
  await expect(prescriptionsPage).toHaveAttribute('data-hydrated', 'true')
  await page.getByTestId('prescription-patient-search').fill(patient.first_name)
  await page.getByTestId(`prescription-patient-${patient.id}`).click()
  await page.getByTestId('medication-name-0').fill('Amoxicillin')
  await page.getByTestId('dose-0').fill('500 mg')
  await page.getByTestId('frequency-0').fill('every 8 hours')
  await page.getByTestId('duration-0').fill('5 days')
  await page.getByTestId('route-0').fill('oral')
  await page.getByTestId('quantity-0').fill('15')
  await page.getByTestId('create-prescription').click()

  const rx = page.locator('[data-testid^="prescription-"]').filter({ hasText: 'Amoxicillin' }).first()
  await expect(rx).toBeVisible()
  const issueButton = rx.locator('[data-testid^="issue-"]')
  await expect(issueButton).toBeVisible()
  await issueButton.click()
  await expect(rx).toContainText('issued')
  await expect(rx).toContainText('immutable')
  await expect(issueButton).toHaveCount(0)
})
