import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { basename, dirname, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

type Messages = Record<string, unknown>

type LocalePair = {
  moduleName: string
  englishPath: string
  arabicPath: string
  configPath: string
}

const frontendRoot = resolve(process.cwd())
const modulesRoot = resolve(frontendRoot, '../backend/app/modules')
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

function moduleLocalePairs(): LocalePair[] {
  return readdirSync(modulesRoot, { withFileTypes: true })
    .filter(entry => entry.isDirectory())
    .flatMap((entry) => {
      const moduleRoot = resolve(modulesRoot, entry.name)
      const configPath = resolve(moduleRoot, 'frontend/nuxt.config.ts')
      const localeDirs = [
        resolve(moduleRoot, 'frontend/i18n/locales'),
        resolve(moduleRoot, 'frontend/locales')
      ]

      return localeDirs.flatMap((localeDir) => {
        if (!existsSync(localeDir)) return []

        return readdirSync(localeDir)
          .filter(file => file === 'en.json' || file.endsWith('-en.json'))
          .map((englishFile): LocalePair => {
            const arabicFile = englishFile === 'en.json'
              ? 'ar.json'
              : englishFile.replace(/-en\.json$/, '-ar.json')
            return {
              moduleName: entry.name,
              englishPath: resolve(localeDir, englishFile),
              arabicPath: resolve(localeDir, arabicFile),
              configPath
            }
          })
      })
    })
}

describe('Arabic localization and RTL contracts', () => {
  it('keeps Arabic structurally complete against the English UI catalog', () => {
    const arabicKeys = new Set(flattenKeys(arabic))
    const missing = flattenKeys(english).filter(key => !arabicKeys.has(key))

    expect(missing, `Missing Arabic message keys:\n${missing.join('\n')}`).toEqual([])
  })

  it('keeps every module English locale covered by a registered Arabic locale', () => {
    const failures: string[] = []

    for (const pair of moduleLocalePairs()) {
      if (!existsSync(pair.arabicPath)) {
        failures.push(`${pair.moduleName}: missing ${basename(pair.arabicPath)}`)
        continue
      }

      const moduleEnglish = JSON.parse(readFileSync(pair.englishPath, 'utf8')) as Messages
      const moduleArabic = JSON.parse(readFileSync(pair.arabicPath, 'utf8')) as Messages
      const arabicKeys = new Set(flattenKeys(moduleArabic))
      const missingKeys = flattenKeys(moduleEnglish).filter(key => !arabicKeys.has(key))
      if (missingKeys.length) {
        failures.push(`${pair.moduleName}: missing keys ${missingKeys.join(', ')}`)
      }

      if (!existsSync(pair.configPath)) {
        failures.push(`${pair.moduleName}: locale catalog has no frontend/nuxt.config.ts`)
        continue
      }

      const config = readFileSync(pair.configPath, 'utf8')
      const arabicFile = basename(pair.arabicPath)
      if (!config.includes('code: \'ar\'') || !config.includes(`file: '${arabicFile}'`)) {
        failures.push(`${pair.moduleName}: ${arabicFile} is not registered in ${dirname(pair.configPath)}/nuxt.config.ts`)
      }
    }

    expect(failures, `Incomplete module Arabic coverage:\n${failures.join('\n')}`).toEqual([])
  })

  it('maps Arabic into Nuxt UI and exposes document direction at SSR level', () => {
    expect(appSource).toContain('import { ar, en, es, fr, pt } from \'@nuxt/ui/locale\'')
    expect(appSource).toContain('locale.value === \'ar\' ? \'rtl\' : \'ltr\'')
    expect(appSource).toContain('dir: documentDirection.value')
  })

  it('mirrors the application shell for RTL instead of pinning it to the left', () => {
    expect(layoutSource).toContain('isRtl.value ? \'right-0\' : \'left-0\'')
    expect(layoutSource).toContain('isRtl.value ? \'md:mr-16\' : \'md:ml-16\'')
    expect(layoutSource).toContain(':side="isRtl ? \'right\' : \'left\'"')
    expect(layoutSource).toContain('i-lucide-panel-right-open')
    expect(layoutSource).toContain('i-lucide-panel-right-close')
  })
})
