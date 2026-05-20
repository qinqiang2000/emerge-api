import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import PromptTab from '../../src/components/QuickLook/PromptTab'
import { useSchema } from '../../src/stores/schema'
import { usePrompts } from '../../src/stores/prompts'

describe('PromptTab', () => {
  beforeEach(() => {
    useSchema.setState({ byProject: {} })
    usePrompts.setState({
      list: { p_test: [] },
      activeByProject: { p_test: { prompt_id: 'pr_baseline', label: 'Baseline', schema: [], global_notes: '', derived_from: null, created_at: 'x', updated_at: 'x' } as any },
      loading: {},
    })
  })

  it('renders editor empty state with add affordance when project has no fields (active prompt)', () => {
    useSchema.setState({ byProject: { p_test: [] } })
    render(<PromptTab target={{ kind: 'prompt', pid: 'p_test' }} />)
    expect(screen.getByText(/仅 notes 也能工作/i)).toBeInTheDocument()
    // Empty-state CTA was compacted from "+ add fields" to just "+" with
    // aria-label="add field"; the visible glyph lives in the title/aria-label now.
    expect(screen.getByRole('button', { name: /add field/i })).toBeInTheDocument()
  })

  it('shows loading state when byProject has no entry for the pid yet (deep-link safety net)', async () => {
    // No setState for byProject[p_unloaded] — simulates a deep-link path where Quick-look
    // opens before any other surface pre-warmed useSchema. The component must call load()
    // itself rather than show the empty state misleadingly.
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify([{ name: 'late_field', type: 'string', description: '' }]), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    usePrompts.setState({
      list: { p_unloaded: [] },
      activeByProject: { p_unloaded: { prompt_id: 'pr', label: 'pr', schema: [], global_notes: '', derived_from: null, created_at: 'x', updated_at: 'x' } as any },
      loading: {},
    })
    render(<PromptTab target={{ kind: 'prompt', pid: 'p_unloaded' }} />)
    expect(screen.getByText(/loading/i)).toBeInTheDocument()
    expect(fetchSpy).toHaveBeenCalledWith('/lab/projects/p_unloaded/schema')
    await waitFor(() => expect(screen.getByText('late_field')).toBeInTheDocument())
    fetchSpy.mockRestore()
  })

  it('renders all fields with no truncation (active prompt)', () => {
    const fields = Array.from({ length: 12 }, (_, i) => ({
      name: `field_${i}`,
      type: 'string' as const,
      description: '',
    }))
    useSchema.setState({ byProject: { p_test: fields } })
    render(<PromptTab target={{ kind: 'prompt', pid: 'p_test' }} />)
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
    render(<PromptTab target={{ kind: 'version', pid: 'p_test', versionId: 'v6' }} />)
    await waitFor(() => expect(screen.getByText('frozen_field')).toBeInTheDocument())
    expect(fetchSpy).toHaveBeenCalledWith('/lab/projects/p_test/versions/v6/raw?shape=fields')
    fetchSpy.mockRestore()
  })

  it('renders error message when version fetch fails', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response('{"detail":{"error_code":"version_not_found"}}', { status: 404 }),
    )
    render(<PromptTab target={{ kind: 'version', pid: 'p_test', versionId: 'v99' }} />)
    await waitFor(() => expect(screen.getByText(/version_not_found/i)).toBeInTheDocument())
    fetchSpy.mockRestore()
  })

  it('fetches variant blob and renders notes read-only for variant kind', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response(
        JSON.stringify({ schema: [{ name: 'vf', type: 'string', description: '' }], global_notes: 'frozen notes' }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      ),
    )
    render(<PromptTab target={{ kind: 'prompt', pid: 'p_test', promptId: 'pr_alt' }} />)
    await waitFor(() => expect(screen.getByText('vf')).toBeInTheDocument())
    expect(screen.getByText('frozen notes')).toBeInTheDocument()
    expect(fetchSpy).toHaveBeenCalledWith('/lab/projects/p_test/prompts/pr_alt')
    // No editable textarea in read-only mode
    expect(screen.queryByPlaceholderText(/给模型的整体说明/)).not.toBeInTheDocument()
    fetchSpy.mockRestore()
  })
})
