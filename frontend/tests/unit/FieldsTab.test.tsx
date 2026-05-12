import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import FieldsTab from '../../src/components/QuickLook/FieldsTab'
import { useSchema } from '../../src/stores/schema'

describe('FieldsTab', () => {
  beforeEach(() => {
    useSchema.setState({ byProject: {} })
  })

  it('renders empty placeholder when project has no fields (schema kind)', () => {
    useSchema.setState({ byProject: { p_test: [] } })
    render(<FieldsTab target={{ kind: 'schema', pid: 'p_test' }} />)
    expect(screen.getByText(/no schema yet/i)).toBeInTheDocument()
  })

  it('shows loading state when byProject has no entry for the pid yet (deep-link safety net)', async () => {
    // No setState for byProject[p_unloaded] — simulates a deep-link path where Quick-look
    // opens before any other surface pre-warmed useSchema. The component must call load()
    // itself rather than show "no schema yet — type /init in the chat" misleadingly.
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response(JSON.stringify([{ name: 'late_field', type: 'string', description: '' }]), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    render(<FieldsTab target={{ kind: 'schema', pid: 'p_unloaded' }} />)
    expect(screen.getByText(/loading/i)).toBeInTheDocument()
    expect(fetchSpy).toHaveBeenCalledWith('/lab/projects/p_unloaded/schema')
    await waitFor(() => expect(screen.getByText('late_field')).toBeInTheDocument())
    fetchSpy.mockRestore()
  })

  it('renders all fields with no truncation (schema kind)', () => {
    const fields = Array.from({ length: 12 }, (_, i) => ({
      name: `field_${i}`,
      type: 'string' as const,
      description: '',
    }))
    useSchema.setState({ byProject: { p_test: fields } })
    render(<FieldsTab target={{ kind: 'schema', pid: 'p_test' }} />)
    for (let i = 0; i < 12; i++) {
      expect(screen.getByText(`field_${i}`)).toBeInTheDocument()
    }
  })

  it('fetches version fields on mount for version kind', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response(
        JSON.stringify({ fields: [{ name: 'frozen_field', type: 'string', description: '' }] }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      ),
    )
    render(<FieldsTab target={{ kind: 'version', pid: 'p_test', versionId: 'v6' }} />)
    await waitFor(() => expect(screen.getByText('frozen_field')).toBeInTheDocument())
    expect(fetchSpy).toHaveBeenCalledWith('/lab/projects/p_test/versions/v6/raw?shape=fields')
    fetchSpy.mockRestore()
  })

  it('renders error message when version fetch fails', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response('{"detail":{"error_code":"version_not_found"}}', { status: 404 }),
    )
    render(<FieldsTab target={{ kind: 'version', pid: 'p_test', versionId: 'v99' }} />)
    await waitFor(() => expect(screen.getByText(/version_not_found/i)).toBeInTheDocument())
    fetchSpy.mockRestore()
  })
})
