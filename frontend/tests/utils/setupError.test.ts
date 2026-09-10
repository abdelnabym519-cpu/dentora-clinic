import { describe, expect, it } from 'vitest'
import { mapSetupError, type SetupErrorShape } from '../../app/utils/setupError'

// Regression coverage for the setup-page error mapping: every backend
// failure shape AND the CORS/network shape must produce a specific,
// actionable message instead of the opaque generic fallback.

function shaped(partial: SetupErrorShape): SetupErrorShape {
  return partial
}

describe('mapSetupError', () => {
  it('maps 409 to the already-initialized key', () => {
    const r = mapSetupError(shaped({ statusCode: 409, data: { message: 'System already initialized' } }))
    expect(r).toEqual({ key: 'setup.alreadyInitialized' })
  })

  it('maps a CORS/network outage (no statusCode) to the network key', () => {
    const r = mapSetupError(shaped({}))
    expect(r).toEqual({ key: 'setup.networkError' })
  })

  it('maps a pydantic 422 detail ARRAY to the first field message', () => {
    const r = mapSetupError(
      shaped({
        statusCode: 422,
        data: {
          detail: [
            {
              type: 'missing',
              loc: ['body', 'clinic_tax_id'],
              msg: 'Field required',
              input: {}
            }
          ]
        }
      })
    )
    expect(r).toEqual({ text: 'clinic_tax_id: Field required' })
  })

  it('strips the pydantic validator wrapper and skips body-level loc', () => {
    const r = mapSetupError(
      shaped({
        statusCode: 422,
        data: {
          detail: [
            {
              type: 'value_error',
              loc: ['body', 'admin_email'],
              msg: 'Value error, value is not a valid email address: reserved name',
              input: 'admin@dentora.local'
            }
          ]
        }
      })
    )
    expect(r).toEqual({ text: 'admin_email: value is not a valid email address: reserved name' })
  })

  it('maps a string detail verbatim', () => {
    const r = mapSetupError(shaped({ statusCode: 422, data: { detail: 'plain string detail' } }))
    expect(r).toEqual({ text: 'plain string detail' })
  })

  it('maps the HTTPException envelope (message, no detail key) to its message', () => {
    const r = mapSetupError(
      shaped({ statusCode: 422, data: { data: null, message: 'Password must contain at least one letter and one number', errors: ['Password must contain at least one letter and one number'] } })
    )
    expect(r).toEqual({ text: 'Password must contain at least one letter and one number' })
  })

  it('falls back to the envelope errors[0] when message is absent', () => {
    const r = mapSetupError(shaped({ statusCode: 402, data: { errors: ['Dentora license activation required'] } }))
    expect(r).toEqual({ text: 'Dentora license activation required' })
  })

  it('falls back to the generic key for an opaque 500', () => {
    const r = mapSetupError(shaped({ statusCode: 500 }))
    expect(r).toEqual({ key: 'setup.error' })
  })
})
