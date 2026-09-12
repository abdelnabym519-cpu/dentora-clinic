import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import ts from 'typescript'

/**
 * Static gate for Nuxt context misuse — the two defect classes that took the
 * app down on SSR.
 *
 *  1. **Composables after an `await`.** Nuxt does not keep the app instance
 *     across `await` boundaries in route middleware or plugin code unless
 *     `experimental.asyncContext` is on (it is not). `useRuntimeConfig()` /
 *     `useAuth()` after `await getCommercialLicenseStatus()` threw
 *     `NUXT_E1001: A composable that requires access to the Nuxt instance was
 *     called outside of a plugin, Nuxt hook, Nuxt middleware, or Vue setup
 *     function.` — fixed in `app/middleware/auth.global.ts` by hoisting every
 *     acquisition above the first `await`. The same applies to functions a
 *     composable defines and hands out (`useApi`'s `$api`, `useAuth`'s
 *     deferred refresh): those run long after setup, so they must read values
 *     captured during setup instead of re-acquiring.
 *
 *  2. **Component-instance-bound APIs in plugin-reachable code.** vue-i18n's
 *     `useI18n()` resolves the current *component* instance and throws
 *     `Must be called at the top of a 'setup' function` when a plugin calls
 *     it. `app/plugins/settings.registry.ts` -> `useClinic()` -> `useApi()`
 *     did exactly that, so every SSR render 500'd and the browser only saw the
 *     downstream symptoms ("Failed to fetch clinic", "Patients connection
 *     error"). Fixed with `useGlobalT()` (`app/utils/i18nScope.ts`), which
 *     reads the global scope from the Nuxt app instead.
 *
 * Both were invisible to unit tests that mount components (a component
 * supplies both instances) and to the browser console on the client (the
 * instance is retained there), which is why they are enforced here, over the
 * real source, instead.
 */

const FRONTEND_ROOT = resolve(__dirname, '../..')

/** Need the Nuxt app instance — illegal after an `await` in middleware/plugins. */
const NUXT_INSTANCE_COMPOSABLES = new Set([
  'useState', 'useCookie', 'useRequestEvent', 'useRequestHeaders', 'useRequestURL',
  'useRuntimeConfig', 'useNuxtApp', 'useRoute', 'useRouter', 'useFetch', 'useLazyFetch',
  'useAsyncData', 'useLazyAsyncData', 'useHead', 'useSeoMeta', 'useCallOnce',
  'useRequestFetch', 'useGlobalT',
  // App wrappers that acquire the above during their own setup.
  'useAuth', 'useApi', 'useClinic', 'useModules', 'usePermissions', 'useToast',
  'useSelectedClinicId', 'useSettingsRegistry'
])

/** Need a *component* instance — illegal anywhere a plugin/middleware can reach. */
const COMPONENT_INSTANCE_APIS = new Set([
  'useI18n', 'getCurrentInstance', 'useAttrs', 'useSlots', 'useTemplateRef',
  'onMounted', 'onBeforeMount', 'onUnmounted', 'onBeforeUnmount'
])

interface SourceFileEntry {
  path: string
  rel: string
  source: ts.SourceFile
}

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    const stat = statSync(full)
    if (stat.isDirectory()) walk(full, out)
    else if (name.endsWith('.ts') && !name.endsWith('.d.ts')) out.push(full)
  }
  return out
}

function collectSourceFiles(): SourceFileEntry[] {
  const dirs = [
    join(FRONTEND_ROOT, 'app/composables'),
    join(FRONTEND_ROOT, 'app/utils'),
    join(FRONTEND_ROOT, 'app/plugins'),
    join(FRONTEND_ROOT, 'app/middleware')
  ]
  const layersRoot = join(FRONTEND_ROOT, 'module_layers')
  for (const layer of readdirSync(layersRoot)) {
    for (const sub of ['composables', 'utils', 'plugins', 'middleware']) {
      const dir = join(layersRoot, layer, 'frontend', sub)
      try {
        if (statSync(dir).isDirectory()) dirs.push(dir)
      } catch { /* layer without that directory */ }
    }
  }

  const files: SourceFileEntry[] = []
  for (const dir of dirs) {
    for (const path of walk(dir)) {
      const text = readFileSync(path, 'utf8')
      files.push({
        path,
        rel: relative(FRONTEND_ROOT, path),
        source: ts.createSourceFile(path, text, ts.ScriptTarget.Latest, true)
      })
    }
  }
  return files
}

/** Names this file's code calls — auto-import means edges need no import statement. */
function calledNames(node: ts.Node, out: Set<string> = new Set()): Set<string> {
  const visit = (child: ts.Node) => {
    if (ts.isCallExpression(child) && ts.isIdentifier(child.expression)) {
      out.add(child.expression.text)
    }
    ts.forEachChild(child, visit)
  }
  visit(node)
  return out
}

describe('Nuxt context safety (static gate)', () => {
  const entries = collectSourceFiles()
  const roots = entries.filter(e => e.rel.includes('/plugins/') || e.rel.includes('/middleware/'))

  it('found the source tree it is supposed to police', () => {
    // Guards against the test silently passing because paths moved.
    expect(entries.length).toBeGreaterThan(50)
    expect(roots.length).toBeGreaterThan(0)
    expect(entries.some(e => e.rel.endsWith('app/composables/useApi.ts'))).toBe(true)
    expect(entries.some(e => e.rel.endsWith('app/middleware/auth.global.ts'))).toBe(true)
  })

  it('keeps component-instance APIs out of plugin/middleware-reachable code', () => {
    // Function-level reachability, not file-level: a plugin that imports
    // `registerSettingsPage` from a composable file does not thereby call every
    // other function in it. Nuxt auto-imports composables/utils, so a call to
    // `useClinic()` is an edge to that function wherever it is declared.
    interface FnNode {
      name: string
      rel: string
      node: ts.Node
      source: ts.SourceFile
    }
    const functions = new Map<string, FnNode[]>()
    const register = (fn: FnNode) => {
      const list = functions.get(fn.name) ?? []
      list.push(fn)
      functions.set(fn.name, list)
    }

    for (const entry of entries) {
      for (const statement of entry.source.statements) {
        if (ts.isFunctionDeclaration(statement) && statement.name) {
          register({ name: statement.name.text, rel: entry.rel, node: statement, source: entry.source })
        } else if (ts.isVariableStatement(statement)) {
          for (const decl of statement.declarationList.declarations) {
            if (ts.isIdentifier(decl.name) && decl.initializer
              && (ts.isArrowFunction(decl.initializer) || ts.isFunctionExpression(decl.initializer))) {
              register({ name: decl.name.text, rel: entry.rel, node: decl.initializer, source: entry.source })
            }
          }
        }
      }
    }

    // Roots: the plugin/middleware module itself, including the callback passed
    // to `defineNuxtPlugin` / `defineNuxtRouteMiddleware`.
    const reachable = new Set<FnNode>()
    interface Scope { rel: string, source: ts.SourceFile, node: ts.Node }
    const rootScopes: Scope[] = roots.map(e => ({ rel: e.rel, source: e.source, node: e.source as ts.Node }))
    const queue: Scope[] = [...rootScopes]

    while (queue.length) {
      const scope = queue.pop() as Scope
      for (const called of calledNames(scope.node)) {
        for (const fn of functions.get(called) ?? []) {
          if (reachable.has(fn)) continue
          reachable.add(fn)
          queue.push({ rel: fn.rel, source: fn.source, node: fn.node })
        }
      }
    }

    // `settings.registry.ts` must still reach `useApi`, otherwise this rule is
    // vacuous and would pass for the wrong reason.
    const reached = (rel: string) => [...reachable].some(fn => fn.rel.endsWith(rel))
    expect(reached('app/composables/useClinic.ts')).toBe(true)
    expect(reached('app/composables/useApi.ts')).toBe(true)

    const violations: string[] = []
    const scopes: Scope[] = [
      ...rootScopes,
      ...[...reachable].map(fn => ({ rel: fn.rel, source: fn.source, node: fn.node }))
    ]
    for (const scope of scopes) {
      const visit = (node: ts.Node) => {
        if (ts.isCallExpression(node) && ts.isIdentifier(node.expression)) {
          const name = node.expression.text
          if (COMPONENT_INSTANCE_APIS.has(name)) {
            const { line } = scope.source.getLineAndCharacterOfPosition(node.getStart())
            violations.push(`${scope.rel}:${line + 1} ${name}() — needs a component instance; use the Nuxt-app equivalent (see app/utils/i18nScope.ts)`)
          }
        }
        ts.forEachChild(node, visit)
      }
      visit(scope.node)
    }

    expect([...new Set(violations)]).toEqual([])
  })

  it('acquires Nuxt-instance composables before the first await in async functions', () => {
    const violations: string[] = []

    for (const entry of entries) {
      const visit = (node: ts.Node) => {
        const isAsyncFn = (ts.isFunctionDeclaration(node) || ts.isMethodDeclaration(node)
          || ts.isArrowFunction(node) || ts.isFunctionExpression(node))
        && Boolean(node.modifiers?.some(m => m.kind === ts.SyntaxKind.AsyncKeyword))

        if (isAsyncFn && node.body && ts.isBlock(node.body)) {
          let seenAwait = false
          for (const statement of node.body.statements) {
            if (!seenAwait) {
              // Any await anywhere in this statement flips the switch for the
              // statements that follow it.
              let hasAwait = false
              const scan = (child: ts.Node) => {
                if (child.kind === ts.SyntaxKind.AwaitExpression) hasAwait = true
                ts.forEachChild(child, scan)
              }
              scan(statement)
              const before = hasAwait
              // Composables in this same statement are still pre-await-safe only
              // if the statement itself does not await before calling them.
              if (before) {
                let firstAwaitPos = Number.MAX_SAFE_INTEGER
                let callPos: { name: string, pos: number }[] = []
                const ordered = (child: ts.Node) => {
                  if (child.kind === ts.SyntaxKind.AwaitExpression) {
                    firstAwaitPos = Math.min(firstAwaitPos, child.getStart())
                  }
                  if (ts.isCallExpression(child) && ts.isIdentifier(child.expression)
                    && NUXT_INSTANCE_COMPOSABLES.has(child.expression.text)) {
                    callPos.push({ name: child.expression.text, pos: child.getStart() })
                  }
                  ts.forEachChild(child, ordered)
                }
                ordered(statement)
                callPos = callPos.filter(c => c.pos > firstAwaitPos)
                for (const call of callPos) {
                  const { line } = entry.source.getLineAndCharacterOfPosition(call.pos)
                  violations.push(`${entry.rel}:${line + 1} ${call.name}() runs after an await in the same statement`)
                }
              }
              if (hasAwait) seenAwait = true
              continue
            }
            for (const called of calledNames(statement)) {
              if (NUXT_INSTANCE_COMPOSABLES.has(called)) {
                const { line } = entry.source.getLineAndCharacterOfPosition(statement.getStart())
                violations.push(`${entry.rel}:${line + 1} ${called}() is acquired after an await — hoist it above the first await`)
              }
            }
          }
        }
        ts.forEachChild(node, visit)
      }
      visit(entry.source)
    }

    expect(violations).toEqual([])
  })

  it('does not re-acquire Nuxt-instance composables inside deferred helper functions', () => {
    // A composable that returns a function (an API client, a token refresher)
    // hands that function to callers who invoke it from watchers, timers and
    // event handlers — long after setup. Re-acquiring inside it is the
    // `useApi.ts` / `useAuth.ts` defect.
    const violations: string[] = []

    for (const entry of entries) {
      if (entry.rel.includes('/middleware/')) continue // middleware bodies are covered above
      const isComposableFile = entry.rel.includes('/composables/') || entry.rel.includes('/utils/')
      if (!isComposableFile) continue

      const visit = (node: ts.Node) => {
        // Top-level exported composable: `export function useX()` / `export const useX = () => …`
        const isExportedComposable = ts.isFunctionDeclaration(node)
          && Boolean(node.name && /^use[A-Z]/.test(node.name.text))
          && Boolean(node.modifiers?.some(m => m.kind === ts.SyntaxKind.ExportKeyword))

        if (isExportedComposable && node.body) {
          const inner = (child: ts.Node) => {
            const nested = (ts.isFunctionDeclaration(child) && child.name
              && !child.modifiers?.some(m => m.kind === ts.SyntaxKind.ExportKeyword))
            || ts.isArrowFunction(child) || ts.isFunctionExpression(child)
            if (nested && child !== node) {
              for (const called of calledNames(child)) {
                if (NUXT_INSTANCE_COMPOSABLES.has(called)) {
                  const { line } = entry.source.getLineAndCharacterOfPosition(child.getStart())
                  violations.push(`${entry.rel}:${line + 1} deferred function inside ${(node as ts.FunctionDeclaration).name?.text}() re-acquires ${called}() — capture it during setup`)
                }
              }
              return // Do not descend further; the nested function is the unit.
            }
            ts.forEachChild(child, inner)
          }
          ts.forEachChild(node.body, inner)
        }
        ts.forEachChild(node, visit)
      }
      visit(entry.source)
    }

    expect(violations).toEqual([])
  })
})
