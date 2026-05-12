import { describe, it, expect, beforeEach, vi } from 'vitest'
import { useQuickLook } from '../../src/stores/quicklook'

describe('useQuickLook store', () => {
  beforeEach(() => {
    useQuickLook.getState().close()
  })

  it('opens schema target', () => {
    useQuickLook.getState().openSchema('p_test')
    expect(useQuickLook.getState().target).toEqual({ kind: 'schema', pid: 'p_test' })
    expect(useQuickLook.getState().rawJson).toEqual({ value: null, loading: false, error: null })
  })

  it('opens version target', () => {
    useQuickLook.getState().openVersion('p_test', 'v6')
    expect(useQuickLook.getState().target).toEqual({ kind: 'version', pid: 'p_test', versionId: 'v6' })
  })

  it('close clears target and rawJson', () => {
    useQuickLook.getState().openSchema('p_test')
    useQuickLook.getState().close()
    expect(useQuickLook.getState().target).toBeNull()
    expect(useQuickLook.getState().rawJson.value).toBeNull()
  })

  it('opening a different target resets rawJson cache', () => {
    useQuickLook.getState().openSchema('p_a')
    // Simulate a loaded raw value:
    useQuickLook.setState({ rawJson: { value: '[]', loading: false, error: null } })
    useQuickLook.getState().openSchema('p_b')
    expect(useQuickLook.getState().rawJson.value).toBeNull()
  })

  it('loadRaw fetches schema/raw and stores text on success', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response('[\n  "x"\n]', { status: 200, headers: { 'content-type': 'text/plain' } }),
    )
    useQuickLook.getState().openSchema('p_test')
    await useQuickLook.getState().loadRaw()
    expect(fetchSpy).toHaveBeenCalledWith('/lab/projects/p_test/schema/raw')
    expect(useQuickLook.getState().rawJson).toEqual({ value: '[\n  "x"\n]', loading: false, error: null })
    fetchSpy.mockRestore()
  })

  it('loadRaw fetches versions/{vid}/raw for version target', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response('{}', { status: 200, headers: { 'content-type': 'text/plain' } }),
    )
    useQuickLook.getState().openVersion('p_test', 'v6')
    await useQuickLook.getState().loadRaw()
    expect(fetchSpy).toHaveBeenCalledWith('/lab/projects/p_test/versions/v6/raw')
    fetchSpy.mockRestore()
  })

  it('loadRaw records error on non-2xx', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response('{"detail":{"error_code":"schema_not_found"}}', {
        status: 404,
        headers: { 'content-type': 'application/json' },
      }),
    )
    useQuickLook.getState().openSchema('p_test')
    await useQuickLook.getState().loadRaw()
    expect(useQuickLook.getState().rawJson.error).toBe('schema_not_found')
    expect(useQuickLook.getState().rawJson.value).toBeNull()
    fetchSpy.mockRestore()
  })
})
