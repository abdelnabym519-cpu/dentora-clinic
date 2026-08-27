import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

type Messages = Record<string, unknown>

const frontendRoot = resolve(process.cwd())
const appSource = readFileSync(resolve(frontendRoot, 'app/app.vue'), 'utf8')
const layoutSource = readFileSync(resolve(frontendRoot, 'app/layouts/default.vue'), 'utf8')
const english = JSON.parse(readFileSync(resolve(frontendRoot, 'i18n/locales/en.json'), 'utf8')) as Messages
const arabic = JSON.parse(readFileSync(resolve(frontendRoot, 'i18n/locales/ar.json'), 'utf8')) as Messages

function flattenKeys(value: unknown, prefix = ''): string[] {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return []

  return Object.entries(value as Messages).flatMap(([key, child]) => {
    const path = prefix ? `${prefix}.${key}` : key
    if (child && typeof child === 'object' && !Array.isArray(child)) {
      return flattenKeys(child, path)
    }
    return [path]
  })
}

describe('Arabic localization and RTL contracts', () => {
  it('keeps Arabic structurally complete against the English UI catalog', () => {
    const arabicKeys = new Set(flattenKeys(arabic))
    const missing = flattenKeys(english).filter(key => !arabicKeys.has(key))

    expect(missing, `Missing Arabic message keys:\n${missing.join('\n')}`).toEqual([])
  })

  it('maps Arabic into Nuxt UI and exposes document direction at SSR level', () => {
    expect(appSource).toContain("import { ar, en, es, fr, pt } from '@nuxt/ui/locale'")
    expect(appSource).toContain("locale.value === 'ar' ? 'rtl' : 'ltr'")
    expect(appSource).toContain('dir: documentDirection.value')
  })

  it('mirrors the application shell for RTL instead of pinning it to the left', () => {
    expect(layoutSource).toContain("isRtl.value ? 'right-0' : 'left-0'")
    expect(layoutSource).toContain("isRtl.value ? 'md:mr-16' : 'md:ml-16'")
    expect(layoutSource).toContain(":side=\"isRtl ? 'right' : 'left'\"")
    expect(layoutSource).toContain('i-lucide-panel-right-open')
    expect(layoutSource).toContain('i-lucide-panel-right-close')
  })
})
