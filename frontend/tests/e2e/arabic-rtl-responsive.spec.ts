import { test, expect } from './_fixtures'

async function enableArabic(page: import('@playwright/test').Page) {
  await page.evaluate(() => {
    window.localStorage.setItem('dentora:locale', 'ar')
  })
  await page.reload({ waitUntil: 'domcontentloaded' })
  await expect(page.locator('html')).toHaveAttribute('lang', 'ar')
  await expect(page.locator('html')).toHaveAttribute('dir', 'rtl')
}

async function expectNoViewportOverflow(page: import('@playwright/test').Page) {
  const overflow = await page.evaluate(() => {
    const root = document.documentElement
    return root.scrollWidth - root.clientWidth
  })
  expect(overflow).toBeLessThanOrEqual(1)
}

test.describe('Arabic RTL responsive smoke', () => {
  test.use({ role: 'dentist' })

  test('desktop shell renders Arabic in RTL without horizontal overflow', async ({ loggedIn: page }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    await enableArabic(page)

    await expect(page.getByText('الرئيسية', { exact: true }).first()).toBeVisible()
    await expectNoViewportOverflow(page)
  })

  test('mobile electronic prescription stays Arabic, RTL and responsive', async ({ loggedIn: page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await enableArabic(page)
    await page.goto('/prescriptions', { waitUntil: 'domcontentloaded' })

    await expect(page.getByTestId('prescriptions-page')).toBeVisible()
    await expect(page.getByRole('heading', { name: 'الوصفات الإلكترونية' })).toBeVisible()
    await expect(page.getByPlaceholder('ابحث عن مريض')).toBeVisible()
    await expectNoViewportOverflow(page)
  })
})
