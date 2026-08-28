import { nextTick } from 'vue'
import { describe, expect, it } from 'vitest'

describe('useSelectedClinicId', () => {
  it('shares a single cookie-backed selection across callers', async () => {
    const { useSelectedClinicId } = await import('~/composables/useSelectedClinicId')
    const a = useSelectedClinicId()
    a.value = 'clinic-shared'
    await nextTick()
    const b = useSelectedClinicId()
    expect(b.value).toBe('clinic-shared')
    a.value = null
    await nextTick()
  })
})
