import { expect, test } from '@playwright/test'

const PATIENT_WITHOUT_MESH = 'ddeebc99-9c0b-4ef8-bb6d-6bb9bd380a4d'
const PATIENT_WITH_MESH = 'd8eebc99-9c0b-4ef8-bb6d-6bb9bd380a48'

function binaryStl(): Buffer {
  const buffer = Buffer.alloc(84 + 50)
  buffer.writeUInt32LE(1, 80)

  let offset = 84
  const writeFloat = (value: number) => {
    buffer.writeFloatLE(value, offset)
    offset += 4
  }

  // normal
  writeFloat(0)
  writeFloat(0)
  writeFloat(1)
  // triangle vertices (millimetres)
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

test.describe('dental 3D — patient summary card', () => {
  test('card fails closed without registered patient-space geometry', async ({
    page,
  }) => {
    await page.goto(`/patients/${PATIENT_WITHOUT_MESH}?tab=summary`)

    const card = page.getByTestId('dental3d-card')
    await expect(card).toBeVisible()
    await expect(page.getByTestId('dental3d-canvas')).toHaveCount(0)
    await expect(page.getByTestId('dental3d-webgl-fallback')).toHaveCount(0)
    await expect(
      card.getByText(
        /No registered patient-space clinical geometry is available\. Synthetic geometry is not shown\./i,
      ),
    ).toBeVisible()
    await expect(card.getByText(/Patient alignment: not available/i)).toBeVisible()
    await expect(
      card.getByText(/Only dentist-accepted IOS→DICOM patient transforms are rendered/i),
    ).toBeVisible()
  })
})

test.describe('dental 3D — real mesh ingestion', () => {
  test('uploaded STL remains fail-closed until patient-space alignment is accepted', async ({
    page,
  }) => {
    await page.goto(`/patients/${PATIENT_WITH_MESH}?tab=summary`)
    const card = page.getByTestId('dental3d-card')
    await expect(card).toBeVisible()

    const fileInput = page.getByTestId('dental3d-scan-input')
    await fileInput.setInputFiles({
      name: 'scan-e2e.stl',
      mimeType: 'model/stl',
      buffer: binaryStl(),
    })

    await expect(page.getByText('scan-e2e.stl')).toBeVisible({ timeout: 15_000 })
    await expect(page.getByTestId('dental3d-canvas')).toHaveCount(0)
    await expect(page.getByTestId('dental3d-webgl-fallback')).toHaveCount(0)
    await expect(
      card.getByText(
        /No registered patient-space clinical geometry is available\. Synthetic geometry is not shown\./i,
      ),
    ).toBeVisible()
    await expect(card.getByText(/Patient alignment: not available/i)).toBeVisible()
    await expect(
      card.getByText(/Only dentist-accepted IOS→DICOM patient transforms are rendered/i),
    ).toBeVisible()
  })

  test('invalid mesh upload fails closed without render derivation', async ({
    page,
  }) => {
    let renderRequests = 0
    page.on('request', (request) => {
      if (
        request.method() === 'POST'
        && new URL(request.url()).pathname === '/api/ai/dental3d/renders'
      ) {
        renderRequests += 1
      }
    })

    await page.goto(`/patients/${PATIENT_WITH_MESH}?tab=summary`)
    await expect(page.getByTestId('dental3d-card')).toBeVisible()

    const scanResponsePromise = page.waitForResponse((response) => {
      const url = new URL(response.url())
      return (
        response.request().method() === 'POST'
        && url.pathname === '/api/ai/dental3d/scans'
      )
    })

    await page.getByTestId('dental3d-scan-input').setInputFiles({
      name: 'invalid-e2e.stl',
      mimeType: 'model/stl',
      buffer: Buffer.from('not-a-valid-stl'),
    })

    const scanResponse = await scanResponsePromise
    expect([400, 422]).toContain(scanResponse.status())
    await expect(page.getByText(/Mesh validation failed|Upload failed/i)).toBeVisible()
    await page.waitForTimeout(250)
    expect(renderRequests).toBe(0)
  })
})
