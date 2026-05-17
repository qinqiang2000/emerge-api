import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import RawJsonTab from '../../src/components/QuickLook/RawJsonTab'
import { useQuickLook } from '../../src/stores/quicklook'
import { usePrompts } from '../../src/stores/prompts'

const PID = 'p_test'

function seedActive(overrides: Partial<{ schema: any[]; global_notes: string }> = {}) {
  usePrompts.setState({
    list: { [PID]: [] },
    activeByProject: {
      [PID]: {
        prompt_id: 'pr_baseline',
        label: 'Baseline',
        schema: overrides.schema ?? [{ name: 'amount', type: 'string', description: 'total', required: false, enum: null, children: null }],
        global_notes: overrides.global_notes ?? 'be terse',
        derived_from: null,
        created_at: 'x',
        updated_at: 'x',
      } as any,
    },
    loading: {},
  })
}

describe('RawJsonTab (active prompt)', () => {
  beforeEach(() => {
    useQuickLook.setState({
      target: { kind: 'prompt', pid: PID },
      rawJson: { value: null, loading: false, error: null },
      rawDirty: false,
    })
    seedActive()
  })

  it('shows loading when active prompt is not yet in cache', () => {
    usePrompts.setState({ list: {}, activeByProject: {}, loading: {} })
    // Stub load() so it doesn't actually fetch
    vi.spyOn(usePrompts.getState(), 'load').mockResolvedValue()
    render(<RawJsonTab />)
    expect(screen.getByText(/loading/i)).toBeInTheDocument()
  })

  it('renders the serialized prompt JSON from usePrompts', async () => {
    render(<RawJsonTab />)
    // CodeMirror renders the source verbatim in the editor surface — assert
    // on a substring of the serialized form (global_notes is hoisted next
    // to schema).
    await waitFor(() => {
      const fragments = screen.getAllByText(/global_notes/i)
      expect(fragments.length).toBeGreaterThan(0)
    })
  })

  it('copy button writes the current buffer to clipboard', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    render(<RawJsonTab />)
    await userEvent.click(screen.getByRole('button', { name: /copy/i }))
    expect(writeText).toHaveBeenCalled()
    expect(writeText.mock.calls[0][0]).toContain('global_notes')
  })

  it('save button is disabled when buffer matches persisted', () => {
    render(<RawJsonTab />)
    expect(screen.getByRole('button', { name: /^save$/i })).toBeDisabled()
  })
})

describe('RawJsonTab (variant prompt — read-only)', () => {
  beforeEach(() => {
    useQuickLook.setState({
      target: { kind: 'prompt', pid: PID, promptId: 'pr_variant' },
      rawJson: { value: null, loading: false, error: null },
      rawDirty: false,
    })
  })

  it('shows loading then renders fetched value, no save button', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response(JSON.stringify({ prompt_id: 'pr_variant', schema: [{ name: 'x' }], global_notes: '' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    render(<RawJsonTab />)
    expect(screen.getByText(/loading/i)).toBeInTheDocument()
    await waitFor(() => expect(screen.getAllByText(/schema/i).length).toBeGreaterThan(0))
    expect(screen.queryByRole('button', { name: /^save$/i })).not.toBeInTheDocument()
  })

  it('shows error message and retry link on failure', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response('{"detail":{"error_code":"prompt_not_found"}}', { status: 404 }),
    )
    render(<RawJsonTab />)
    await waitFor(() => expect(screen.getByText(/prompt_not_found/i)).toBeInTheDocument())
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument()
  })
})
