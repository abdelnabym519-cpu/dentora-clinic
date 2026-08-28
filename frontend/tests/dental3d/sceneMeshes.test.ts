import { describe, expect, it } from 'vitest'
import {
  meshOverlay,
  pickActiveMesh,
  toSceneMeshes,
  type DentalMeshPayload
} from '../../module_layers/dental_3d/frontend/lib/sceneMeshes'

function mesh(overrides: Partial<DentalMeshPayload> = {}): DentalMeshPayload {
  return {
    source: 'intraoral_scan',
    format: 'stl',
    document_id: 'doc-1',
    label: 'Upper arch',
    file_size: 1024,
    uploaded_at: '2026-08-23T08:00:00Z',
    url: '/api/v1/media/documents/doc-1/download',
    ...overrides
  }
}

describe('toSceneMeshes', () => {
  it('maps real mesh references to surface renderables', () => {
    const refs = toSceneMeshes({ meshes: [mesh()] })
    expect(refs).toHaveLength(1)
    expect(refs[0]).toEqual({
      id: 'doc-1',
      kind: 'surface',
      source: 'intraoral_scan',
      format: 'stl',
      label: 'Upper arch',
      url: '/api/v1/media/documents/doc-1/download',
      documentId: 'doc-1',
      fileSize: 1024
    })
  })

  it('drops synthetic/procedural descriptors', () => {
    const refs = toSceneMeshes({
      meshes: [mesh({ source: 'synthetic', format: 'procedural', document_id: null, url: null })]
    })
    expect(refs).toEqual([])
  })

  it('drops partial references that cannot be rendered', () => {
    expect(toSceneMeshes({ meshes: [mesh({ document_id: null })] })).toEqual([])
    expect(toSceneMeshes({ meshes: [mesh({ url: null })] })).toEqual([])
    expect(toSceneMeshes({ meshes: [mesh({ format: 'gltf' })] })).toEqual([])
  })

  it('accepts validated PLY mesh references', () => {
    expect(toSceneMeshes({ meshes: [mesh({ format: 'ply' })] })[0]?.format).toBe('ply')
  })

  it('degrades to an empty list without a scene or meshes', () => {
    expect(toSceneMeshes(null)).toEqual([])
    expect(toSceneMeshes({})).toEqual([])
    expect(toSceneMeshes({ meshes: null })).toEqual([])
  })
})

describe('pickActiveMesh', () => {
  it('selects the first (newest) mesh — the future selection point', () => {
    const refs = toSceneMeshes({
      meshes: [mesh({ document_id: 'newest', url: '/api/v1/media/documents/newest/download' }), mesh()]
    })
    expect(pickActiveMesh(refs)?.id).toBe('newest')
  })

  it('returns null without meshes (pure Phase 1 fallback)', () => {
    expect(pickActiveMesh([])).toBeNull()
  })
})

describe('meshOverlay — loading / error / fallback state machine', () => {
  const refs = toSceneMeshes({ meshes: [mesh()] })

  it('no meshes → pure synthetic rendering, no overlays', () => {
    expect(meshOverlay([], 'idle')).toEqual({
      renderSynthetic: true,
      showLoading: false,
      showError: false,
      showBadge: false
    })
  })

  it('loading → synthetic stays visible (no blank flash) plus loading chip', () => {
    expect(meshOverlay(refs, 'loading')).toEqual({
      renderSynthetic: true,
      showLoading: true,
      showError: false,
      showBadge: false
    })
  })

  it('ready → real geometry replaces the synthetic arch, badge shown', () => {
    expect(meshOverlay(refs, 'ready')).toEqual({
      renderSynthetic: false,
      showLoading: false,
      showError: false,
      showBadge: true
    })
  })

  it('error → explicit error chip with synthetic fallback', () => {
    expect(meshOverlay(refs, 'error')).toEqual({
      renderSynthetic: true,
      showLoading: false,
      showError: true,
      showBadge: false
    })
  })
})
