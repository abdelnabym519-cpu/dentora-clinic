// Module layer resolution for the Nuxt app.
//
// `frontend/modules.json` declares the Nuxt layers installed by the
// backend (`manifest.frontend.layer_path`). Entries are absolute paths
// under the `/module_layers` mount: docker-compose binds
// `./backend/app/modules` there for the dev server and
// `frontend/Dockerfile.prod` COPYs it into the production build.
//
// The same file is also read on hosts where that mount does not exist
// (e.g. `npm run dev` straight from a Windows checkout, or the frontend
// image build stage, which runs before any mount exists). On Windows a
// plain checkout additionally turns the tracked `frontend/module_layers`
// symlink into a regular text file, so walking `frontend/module_layers/…`
// crashes with `ENOTDIR: not a directory, lstat '/app/module_layers/…'`
// instead of a readable message.
//
// Resolution rules (single source of truth stays `modules.json`):
//   1. use the entry as given (absolute), or resolved against `frontend/`
//      when relative;
//   2. if (and only if) that candidate is unusable and the path contains a
//      `module_layers` segment, map the remainder onto the real module
//      source at `<repo>/backend/app/modules/…`;
//   3. report and skip entries that still cannot be resolved as a
//      directory, so one stale entry can never brick the whole build.

import { readFileSync, statSync } from 'node:fs'
import { dirname, isAbsolute, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const currentDir = dirname(fileURLToPath(import.meta.url))

const MOUNT_SEGMENT = 'module_layers'

function isReadableDirectory(candidate) {
  try {
    return statSync(candidate).isDirectory()
  } catch {
    // ENOENT (missing) and ENOTDIR (a path component is a file, e.g. the
    // Windows-converted `module_layers` symlink) are both "unusable here".
    return false
  }
}

function candidatePaths(raw, modulesRoot) {
  const candidates = [isAbsolute(raw) ? raw : resolve(currentDir, raw)]
  const segments = candidates[0].split(/[\\/]/)
  const mountIndex = segments.lastIndexOf(MOUNT_SEGMENT)
  if (mountIndex !== -1) {
    const remainder = segments.slice(mountIndex + 1).join('/')
    candidates.push(resolve(modulesRoot, remainder))
  }
  return candidates
}

/**
 * Resolve one `modules.json` layer entry to a real directory.
 * Returns `{ dir, via }` or `null` with a reason for diagnostics.
 */
export function resolveLayerDir(raw, { modulesRoot = resolve(currentDir, '..', 'backend', 'app', 'modules') } = {}) {
  if (typeof raw !== 'string' || raw.trim() === '') {
    return { ok: false, reason: 'empty_entry' }
  }
  for (const candidate of candidatePaths(raw, modulesRoot)) {
    if (isReadableDirectory(candidate)) {
      return {
        ok: true,
        dir: candidate,
        via: candidate === raw ? 'direct' : 'mapped'
      }
    }
  }
  const lastError = (() => {
    try {
      const st = statSync(isAbsolute(raw) ? raw : resolve(currentDir, raw))
      return st.isDirectory() ? 'not_found' : 'not_a_directory'
    } catch (err) {
      return err && err.code === 'ENOTDIR' ? 'not_a_directory' : 'not_found'
    }
  })()
  return { ok: false, reason: lastError }
}

/**
 * Load + resolve the module layer list from `modules.json`.
 * Never throws for content problems: malformed/missing files resolve to
 * an empty layer list (with a warning), and unresolvable entries are
 * reported through `dropped` so callers can warn with specifics.
 */
export function loadModuleLayers({
  modulesJsonPath = join(currentDir, 'modules.json'),
  modulesRoot,
  readFileSyncImpl,
  warn = () => {}
} = {}) {
  let entries
  try {
    const readFile = readFileSyncImpl ?? readFileSync
    const raw = readFile(modulesJsonPath, 'utf-8')
    const payload = JSON.parse(raw)
    entries = Array.isArray(payload?.layers) ? payload.layers : []
    if (!Array.isArray(payload?.layers)) {
      warn(`[nuxt.config] ${modulesJsonPath} has no "layers" array; continuing with no module layers`)
    }
  } catch (err) {
    if (err && err.code === 'ENOENT') {
      // Fresh checkout without community modules: nothing to extend.
      return { layers: [], dropped: [] }
    }
    warn(`[nuxt.config] ${modulesJsonPath} is unreadable/malformed, continuing with no module layers:`, err)
    return { layers: [], dropped: [] }
  }

  const layers = []
  const dropped = []
  for (const raw of entries) {
    const resolved = resolveLayerDir(raw, { modulesRoot })
    if (resolved.ok) {
      layers.push(resolved.dir)
    } else {
      dropped.push({ path: raw, reason: resolved.reason })
      warn(
        `[nuxt.config] dropping module layer "${raw}" (${resolved.reason}); ` +
        'the app will build without it. Check the module install / modules.json.'
      )
    }
  }
  return { layers, dropped }
}
