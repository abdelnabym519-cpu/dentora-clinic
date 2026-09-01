import { expect, test } from './_fixtures'

test.describe('Dentora Voice', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      class FakeMediaRecorder {
        static isTypeSupported() {
          return true
        }

        state = 'inactive'
        ondataavailable: ((event: { data: Blob }) => void) | null = null
        onstop: (() => void) | null = null

        start() {
          this.state = 'recording'
        }

        stop() {
          this.state = 'inactive'
          this.ondataavailable?.({ data: new Blob(['synthetic-e2e-audio'], { type: 'audio/webm' }) })
          this.onstop?.()
        }
      }

      Object.defineProperty(window, 'MediaRecorder', {
        configurable: true,
        value: FakeMediaRecorder
      })
      Object.defineProperty(navigator, 'mediaDevices', {
        configurable: true,
        value: {
          getUserMedia: async () => ({
            getTracks: () => [{ stop: () => undefined }]
          })
        }
      })
    })

    await page.route('http://127.0.0.1:8765/transcribe', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          text: 'Open patient Ahmed',
          language: 'en',
          duration_seconds: 1.2
        })
      })
    })

    await page.route('**/voice/execute', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          data: {
            state: 'success',
            context: {
              route: '/patients/11111111-1111-4111-8111-111111111111',
              viewer_open: false,
              implant_planner_open: false
            },
            steps: [
              {
                command: 'OPEN_PATIENT',
                ok: true,
                confidence: 0.98,
                clarification_required: false,
                confirmation_required: false,
                ui_action: {
                  action: 'navigate',
                  payload: {
                    route: '/patients/11111111-1111-4111-8111-111111111111'
                  }
                }
              }
            ]
          }
        })
      })
    })
  })

  test('uses mocked local STT and applies audited navigation action', async ({ loggedIn: page }) => {
    await expect(page.getByTestId('dentora-voice-launcher')).toBeVisible()
    await page.getByTestId('dentora-voice-launcher').click()
    await expect(page.getByTestId('dentora-voice-panel')).toBeVisible()

    await page.getByTestId('dentora-voice-start').click()
    await expect(page.getByTestId('dentora-voice-stop')).toBeVisible()
    await page.getByTestId('dentora-voice-stop').click()

    await expect(page.getByTestId('dentora-voice-transcript')).toContainText('Open patient Ahmed')
    await page.waitForURL(/\/patients\/11111111-1111-4111-8111-111111111111$/)
  })
})
