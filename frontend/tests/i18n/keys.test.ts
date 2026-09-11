import { readdirSync, readFileSync, existsSync, statSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

/**
 * Every static ``t('some.key')`` in the host app and in every module layer
 * must resolve in every shipped locale.
 *
 * Why this is a test and not a lint rule: a missing key does not throw, it
 * renders the *raw key* — a button labelled ``actions.back``, a toast titled
 * ``errors.updateFailed``, an entire legal-guardian form whose labels read
 * ``patients.legalGuardian.name``. The screen still "works", so nothing else
 * catches it. 36 such keys were found and fixed; this pins them down.
 *
 * Dynamic keys (``t(`x.${y}`)``) are out of scope — they cannot be resolved
 * statically — so only quoted literals without ``$`` are collected.
 */

const here = dirname(fileURLToPath(import.meta.url))
const repoRoot = resolve(here, '../../..')
const frontendRoot = resolve(repoRoot, 'frontend')
const modulesRoot = resolve(repoRoot, 'backend/app/modules')

const LANGS = ['en', 'es', 'fr', 'pt', 'ar']

type Messages = Record<string, unknown>

function merge(dst: Messages, src: Messages): void {
  for (const [key, value] of Object.entries(src)) {
    const existing = dst[key]
    if (value && typeof value === 'object' && !Array.isArray(value)
      && existing && typeof existing === 'object' && !Array.isArray(existing)) {
      merge(existing as Messages, value as Messages)
    } else {
      dst[key] = value
    }
  }
}

/** Locale directories that Nuxt i18n merges: host + every module layer. */
function localeDirs(): string[] {
  const dirs = [join(frontendRoot, 'i18n/locales')]
  for (const mod of readdirSync(modulesRoot)) {
    const layer = join(modulesRoot, mod, 'frontend')
    if (!existsSync(layer) || !statSync(layer).isDirectory()) continue
    // v9/v10 layout first; the voice layer keeps the legacy `locales/` dir
    // and points `langDir` at it from its own nuxt.config.ts.
    for (const sub of ['i18n/locales', 'locales']) {
      const candidate = join(layer, sub)
      if (existsSync(candidate)) dirs.push(candidate)
    }
  }
  return dirs
}

function catalogFor(lang: string): Messages {
  const messages: Messages = {}
  for (const dir of localeDirs()) {
    const candidates = [
      join(dir, `${lang}.json`),
      ...readdirSync(dir).filter(f => f.endsWith(`-${lang}.json`)).map(f => join(dir, f))
    ]
    for (const file of candidates) {
      if (!existsSync(file)) continue
      merge(messages, JSON.parse(readFileSync(file, 'utf-8')) as Messages)
    }
  }
  return messages
}

function resolveKey(messages: Messages, key: string): unknown {
  let cursor: unknown = messages
  for (const part of key.split('.')) {
    if (cursor && typeof cursor === 'object' && part in (cursor as Messages)) {
      cursor = (cursor as Messages)[part]
    } else {
      return undefined
    }
  }
  return typeof cursor === 'object' ? undefined : cursor
}

function sourceFiles(): string[] {
  const roots = [join(frontendRoot, 'app')]
  for (const mod of readdirSync(modulesRoot)) {
    const layer = join(modulesRoot, mod, 'frontend')
    if (existsSync(layer)) roots.push(layer)
  }
  const out: string[] = []
  const walk = (dir: string): void => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (entry.name === 'node_modules') continue
      const full = join(dir, entry.name)
      if (entry.isDirectory()) walk(full)
      else if (entry.name.endsWith('.vue') || entry.name.endsWith('.ts')) out.push(full)
    }
  }
  for (const root of roots) {
    if (existsSync(root)) walk(root)
  }
  return out
}

/** Static, non-interpolated ``t('…')`` keys. */
function usedKeys(): Map<string, string[]> {
  const pattern = /\bt\(\s*'([^'$]+)'/g
  const keys = new Map<string, string[]>()
  for (const file of sourceFiles()) {
    const src = readFileSync(file, 'utf-8')
    for (const match of src.matchAll(pattern)) {
      const key = match[1]!
      const seen = keys.get(key) ?? []
      seen.push(file.replace(`${repoRoot}/`, ''))
      keys.set(key, seen)
    }
  }
  return keys
}

describe('i18n coverage — no key renders as a raw key', () => {
  const keys = usedKeys()

  it('collects a meaningful set of keys (guard against a broken scan)', () => {
    expect(keys.size).toBeGreaterThan(1500)
    expect(keys.has('common.retry')).toBe(true)
  })

  for (const lang of LANGS) {
    it(`every used key resolves in "${lang}"`, () => {
      const messages = catalogFor(lang)
      const missing: string[] = []
      for (const [key, files] of keys) {
        if (resolveKey(messages, key) === undefined) missing.push(`${key} (${files[0]})`)
      }
      expect(missing, `Missing translations for locale "${lang}"`).toEqual([])
    })
  }

  it('ships no message that vue-i18n cannot compile', () => {
    // A single unescaped `@` (the linked-message operator) or a stray brace
    // makes vue-i18n reject the WHOLE locale file: every t() in that language
    // then silently renders raw keys. This bit us once via an email
    // placeholder (`guardian@example.com`) — cheap to guard, brutal to debug.
    const offenders: string[] = []

    for (const lang of LANGS) {
      const walk = (node: unknown, path: string[]): void => {
        if (typeof node === 'string') {
          // `{'@'}` / `{'|'}` are the documented literal escapes, `{name}` is
          // interpolation; any other special character is a compile error.
          const stripped = node
            .replace(/\{'[^']*'\}/g, '')
            .replace(/\{[a-zA-Z_][a-zA-Z0-9_]*\}/g, '')
          if (stripped.includes('@')) offenders.push(`${lang}: ${path.join('.')} → ${node} (unescaped @)`)
          if (stripped.includes('{') || stripped.includes('}')) {
            offenders.push(`${lang}: ${path.join('.')} → ${node} (unbalanced brace)`)
          }
        } else if (node && typeof node === 'object') {
          for (const [key, value] of Object.entries(node as Messages)) walk(value, [...path, key])
        }
      }
      walk(catalogFor(lang), [])
    }

    expect(offenders).toEqual([])
  })

  it('keeps the keys that used to render raw (regression anchors)', () => {
    const en = catalogFor('en')
    const anchors = [
      'errors.loadFailed',
      'errors.createFailed',
      'errors.updateFailed',
      'errors.deleteFailed',
      'actions.back',
      'actions.change',
      'common.download',
      'common.view',
      'common.status',
      'common.default',
      'common.more',
      'catalog.loadFailed',
      'selector.loadFailed',
      'selector.searchFailed',
      'treatmentPlans.pendingLoadFailed',
      'invoice.status.title',
      'invoice.messages.paymentRecorded',
      'invoice.messages.creditNoteCreated',
      'patients.editLegalGuardian',
      'patients.legalGuardian.title',
      'patients.legalGuardian.relationships.parent',
      'clinical.diagnosis.openNotes'
    ]
    for (const key of anchors) {
      expect(resolveKey(en, key), `${key} must exist`).not.toBeUndefined()
    }

    // The escaped placeholder must still render as an email-looking hint.
    expect(resolveKey(en, 'patients.legalGuardian.emailPlaceholder'))
      .toContain('@')
  })
})
