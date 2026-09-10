export declare function resolveLayerDir(
  raw: string,
  opts?: { modulesRoot?: string }
): { ok: true; dir: string; via: 'direct' | 'mapped' } | { ok: false; reason: string }

export declare function loadModuleLayers(opts?: {
  modulesJsonPath?: string
  modulesRoot?: string
  readFileSyncImpl?: (path: string, encoding: string) => string
  warn?: (...args: unknown[]) => void
}): { layers: string[]; dropped: Array<{ path: string; reason: string }> }
