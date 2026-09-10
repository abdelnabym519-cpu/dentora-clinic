import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { describe, expect, it, vi } from 'vitest'
import { loadModuleLayers, resolveLayerDir } from '../../module-layers.mjs'

// Regression coverage for module-layer resolution (frontend/modules.json).
// Root cause class: on Windows the tracked `frontend/module_layers` symlink
// materializes as a plain file, so walking `<mount>/patients/frontend/...`
// threw `ENOTDIR` and bricked the build. Resolution must validate paths,
// fall back to the real `backend/app/modules` source, and skip — never
// throw — for entries that genuinely cannot be resolved.

function makeTempTree(): string {
  return mkdtempSync(join(tmpdir(), 'dentora-layers-'))
}

describe('resolveLayerDir', () => {
  it('resolves a direct directory hit', () => {
    const root = makeTempTree()
    try {
      const layer = join(root, 'patients', 'frontend')
      mkdirSync(layer, { recursive: true })
      const result = resolveLayerDir(layer)
      expect(result.ok).toBe(true)
      if (result.ok) {
        expect(result.dir).toBe(layer)
        expect(result.via).toBe('direct')
      }
    } finally {
      rmSync(root, { recursive: true, force: true })
    }
  })

  it('maps a container-style mount path onto the real backend module source', () => {
    const root = makeTempTree()
    try {
      const modulesRoot = join(root, 'backend', 'app', 'modules')
      // Unique module name: must not exist under a real /module_layers mount
      // on the host, so the direct candidate always misses and the mapped
      // fallback is exercised deterministically.
      const moduleName = 'layermap-probe-module'
      mkdirSync(join(modulesRoot, moduleName, 'frontend'), { recursive: true })
      const result = resolveLayerDir(`/module_layers/${moduleName}/frontend`, { modulesRoot })
      expect(result.ok).toBe(true)
      if (result.ok) {
        expect(result.via).toBe('mapped')
        expect(result.dir).toBe(join(modulesRoot, moduleName, 'frontend'))
      }
    } finally {
      rmSync(root, { recursive: true, force: true })
    }
  })

  it('classifies a file where a directory is required as not_a_directory (ENOTDIR class)', () => {
    const root = makeTempTree()
    try {
      // Simulates the Windows checkout: frontend/module_layers is a FILE.
      writeFileSync(join(root, 'module_layers'), '../backend/app/modules')
      const broken = join(root, 'module_layers', 'patients', 'frontend')
      const emptyModulesRoot = join(root, 'empty-modules')
      mkdirSync(emptyModulesRoot, { recursive: true })
      // With no real module source behind the mount, the entry is dropped…
      const dropped = resolveLayerDir(broken, { modulesRoot: emptyModulesRoot })
      expect(dropped.ok).toBe(false)
      if (!dropped.ok) {
        expect(dropped.reason).toBe('not_a_directory')
      }
      // …but against the real repository it heals onto backend/app/modules
      // instead of throwing ENOTDIR (the original production failure).
      const healed = resolveLayerDir(broken)
      expect(healed.ok).toBe(true)
      if (healed.ok) {
        expect(healed.via).toBe('mapped')
        expect(healed.dir).toMatch(/backend[\/]app[\/]modules[\/]patients[\/]frontend$/)
      }
    } finally {
      rmSync(root, { recursive: true, force: true })
    }
  })

  it('classifies a plain missing path as not_found', () => {
    const result = resolveLayerDir(join(tmpdir(), 'dentora-does-not-exist-xyz', 'frontend'))
    expect(result.ok).toBe(false)
    if (!result.ok) {
      expect(result.reason).toBe('not_found')
    }
  })

  it('rejects empty entries', () => {
    expect(resolveLayerDir('')).toEqual({ ok: false, reason: 'empty_entry' })
  })
})

describe('loadModuleLayers', () => {
  it('resolves valid + mappable entries and drops the rest with reasons', () => {
    const root = makeTempTree()
    try {
      const frontendDir = join(root, 'frontend')
      const modulesRoot = join(root, 'backend', 'app', 'modules')
      mkdirSync(join(frontendDir, 'voice', 'frontend'), { recursive: true })
      // Unique name so the mapped candidate cannot be shadowed by a real
      // /module_layers mount on the host (see resolveLayerDir test above).
      const mappedModule = 'layerdrop-probe-module'
      mkdirSync(join(modulesRoot, mappedModule, 'frontend'), { recursive: true })
      const fileLayerDir = join(root, 'broken_mount')
      writeFileSync(fileLayerDir, 'not a directory')
      writeFileSync(
        join(frontendDir, 'modules.json'),
        JSON.stringify({
          layers: [
            join(frontendDir, 'voice', 'frontend'),
            `/module_layers/${mappedModule}/frontend`,
            '/module_layers/ghost/frontend',
            join(fileLayerDir, 'x', 'frontend')
          ]
        })
      )
      const warn = vi.fn()
      const result = loadModuleLayers({
        modulesJsonPath: join(frontendDir, 'modules.json'),
        modulesRoot,
        warn
      })
      expect(result.layers).toEqual([
        join(frontendDir, 'voice', 'frontend'),
        join(modulesRoot, mappedModule, 'frontend')
      ])
      expect(result.dropped).toEqual([
        { path: '/module_layers/ghost/frontend', reason: 'not_found' },
        { path: join(fileLayerDir, 'x', 'frontend'), reason: 'not_a_directory' }
      ])
      expect(warn).toHaveBeenCalledTimes(2)
    } finally {
      rmSync(root, { recursive: true, force: true })
    }
  })

  it('returns an empty layer list without warnings when modules.json is absent', () => {
    const warn = vi.fn()
    const result = loadModuleLayers({
      modulesJsonPath: join(tmpdir(), 'dentora-no-modules-json', 'modules.json'),
      warn
    })
    expect(result.layers).toEqual([])
    expect(result.dropped).toEqual([])
    expect(warn).not.toHaveBeenCalled()
  })

  it('warns and continues when modules.json is malformed', () => {
    const root = makeTempTree()
    try {
      const modulesJsonPath = join(root, 'modules.json')
      writeFileSync(modulesJsonPath, '{ not json')
      const warn = vi.fn()
      const result = loadModuleLayers({ modulesJsonPath, warn })
      expect(result.layers).toEqual([])
      expect(warn).toHaveBeenCalled()
    } finally {
      rmSync(root, { recursive: true, force: true })
    }
  })

  it('resolves every layer of the canonical modules.json in this repository', () => {
    // Repo invariant: every entry the backend ships must resolve against
    // the real module source — no stale entries, nothing dropped.
    const modulesJsonPath = resolve(__dirname, '../../modules.json')
    const warn = vi.fn()
    const result = loadModuleLayers({ modulesJsonPath, warn })
    expect(result.dropped).toEqual([])
    expect(warn).not.toHaveBeenCalled()
    expect(result.layers.length).toBeGreaterThanOrEqual(20)
    for (const layer of result.layers) {
      // Layers resolve either to the /module_layers mount (container, or a
      // host that happens to have one) or to the mapped backend source.
      expect(layer).toMatch(/(backend[\\/]app[\\/]modules|module_layers)[\\/].+[\\/]frontend$/)
    }
  })
})
