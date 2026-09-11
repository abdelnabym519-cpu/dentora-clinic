import { describe, expect, it } from 'vitest'
import { apiOperationContext } from '~/utils/apiContext'

/**
 * The shared error layer reports failures by *operation*. These labels are
 * what keep a Veri*Factu denial from reading as "patients are forbidden",
 * so the derivation itself is under test.
 */
describe('apiOperationContext', () => {
  it('names the module and action of a compliance probe', () => {
    const ctx = apiOperationContext('/api/v1/verifactu/health')
    expect(ctx.module).toBe('verifactu')
    expect(ctx.action).toBe('health')
    expect(ctx.key).toBe('verifactu/health')
    expect(ctx.label).toBe('Verifactu Health')
  })

  it('ignores record ids when picking the action', () => {
    const uuid = '3f2b8c1e-6d4a-4b7e-9c2f-1a5d8e7b4c60'
    expect(apiOperationContext(`/api/v1/patients/${uuid}/extended`).label)
      .toBe('Patients Extended')
    expect(apiOperationContext(`/api/v1/verifactu/queue/${uuid}/retry`).key)
      .toBe('verifactu/retry')
    expect(apiOperationContext('/api/v1/dental_3d/patients/42/implant-planning').label)
      .toBe('Dental 3D Implant Planning')
  })

  it('falls back to the module for bare collections and strips query strings', () => {
    expect(apiOperationContext('/api/v1/patients?page=2&search=ana').label).toBe('Patients')
    expect(apiOperationContext('/api/v1/verifactu/records?invoice_id=x&page_size=1').key)
      .toBe('verifactu/records')
  })

  it('keeps unrelated modules distinguishable', () => {
    const verifactu = apiOperationContext('/api/v1/verifactu/settings')
    const patients = apiOperationContext('/api/v1/patients')
    expect(verifactu.key).not.toBe(patients.key)
    expect(verifactu.label).not.toContain('Patients')
    expect(patients.label).not.toContain('Verifactu')
  })

  it('handles paths that do not follow the /api/v1 convention', () => {
    expect(apiOperationContext('/modules/-/active').label).toBe('Modules Active')
    expect(apiOperationContext('/').module).toBe('app')
  })
})
