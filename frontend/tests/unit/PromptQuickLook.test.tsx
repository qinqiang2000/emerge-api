import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import PromptQuickLook from '../../src/components/QuickLook/PromptQuickLook'
import { useQuickLook } from '../../src/stores/quicklook'
import { useProjects } from '../../src/stores/projects'
import { useSchema } from '../../src/stores/schema'
import { usePrompts } from '../../src/stores/prompts'

describe('PromptQuickLook', () => {
  beforeEach(() => {
    useQuickLook.getState().close()
    // Slug = 'p_test' here only because the original fixture used `p_test` as
    // the QuickLook target's `pid`; FSSpine and QuickLook now both treat that
    // field as a slug. Keeping the literal verbatim minimises test churn.
    useProjects.setState({ selectedSlug: 'p_test', projects: [
      { project_id: 'p_internal', slug: 'p_test', name: 'us-invoice', active_version_id: 'v6' } as any,
    ] })
    useSchema.setState({ byProject: { p_test: [
      { name: 'invoice_number', type: 'string', description: 'the id', required: true } as any,
    ] } })
    usePrompts.setState({
      list: { p_test: [] },
      activeByProject: { p_test: { prompt_id: 'pr_baseline', label: 'Baseline', schema: [], global_notes: '', derived_from: null, created_at: 'x', updated_at: 'x' } as any },
      loading: {},
    })
  })

  it('renders nothing when target is null', () => {
    const { container } = render(<PromptQuickLook />)
    expect(container.firstChild).toBeNull()
  })

  it('opens with prompt tab by default', () => {
    useQuickLook.getState().openPrompt('p_test')
    render(<PromptQuickLook />)
    expect(screen.getByText('prompts/active')).toBeInTheDocument()
    expect(screen.getByText('invoice_number')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^prompt$/i })).toHaveClass('ql-tab--active')
  })

  it('Esc key closes the sheet', async () => {
    useQuickLook.getState().openPrompt('p_test')
    render(<PromptQuickLook />)
    await userEvent.keyboard('{Escape}')
    expect(useQuickLook.getState().target).toBeNull()
  })

  it('scrim click closes the sheet', async () => {
    useQuickLook.getState().openPrompt('p_test')
    render(<PromptQuickLook />)
    await userEvent.click(screen.getByTestId('ql-scrim'))
    expect(useQuickLook.getState().target).toBeNull()
  })

  it('click on sheet body does not close', async () => {
    useQuickLook.getState().openPrompt('p_test')
    render(<PromptQuickLook />)
    await userEvent.click(screen.getByText('prompts/active'))
    expect(useQuickLook.getState().target).not.toBeNull()
  })

  it('switching project closes the sheet', () => {
    useQuickLook.getState().openPrompt('p_test')
    render(<PromptQuickLook />)
    useProjects.setState({ selectedSlug: 'p_other' })
    expect(useQuickLook.getState().target).toBeNull()
  })

  it('tab click switches between prompt and raw json', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response(JSON.stringify({ prompt_id: 'pr_baseline', schema: [], global_notes: '' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    useQuickLook.getState().openPrompt('p_test')
    render(<PromptQuickLook />)
    await userEvent.click(screen.getByRole('button', { name: /raw json/i }))
    expect(screen.getByRole('button', { name: /raw json/i })).toHaveClass('ql-tab--active')
  })

  it('footer renders the notes-vs-review hint', () => {
    useQuickLook.getState().openPrompt('p_test')
    render(<PromptQuickLook />)
    expect(screen.getByText(/notes \+ field descriptions go into the prompt/i)).toBeInTheDocument()
    expect(screen.getByText(/feed AutoResearch/i)).toBeInTheDocument()
  })

  it('renders notes textarea pre-populated from activePrompt', () => {
    usePrompts.setState({
      list: { p_test: [] },
      activeByProject: { p_test: { prompt_id: 'pr_baseline', label: 'Baseline', schema: [], global_notes: 'be terse', derived_from: null, created_at: 'x', updated_at: 'x' } as any },
      loading: {},
    })
    useQuickLook.getState().openPrompt('p_test')
    render(<PromptQuickLook />)
    const ta = screen.getByPlaceholderText(/Overall instructions/i) as HTMLTextAreaElement
    expect(ta.value).toBe('be terse')
  })

  it('blur on notes textarea dispatches saveActive(slug, fields, notes)', async () => {
    const saveSpy = vi.spyOn(useSchema.getState(), 'saveActive').mockResolvedValue(null)
    useQuickLook.getState().openPrompt('p_test')
    render(<PromptQuickLook />)
    const ta = screen.getByPlaceholderText(/Overall instructions/i) as HTMLTextAreaElement
    await userEvent.click(ta)
    await userEvent.type(ta, 'new notes')
    ta.blur()
    await waitFor(() => expect(saveSpy).toHaveBeenCalled())
    const fields = useSchema.getState().byProject['p_test']
    expect(saveSpy).toHaveBeenCalledWith('p_test', fields, 'new notes')
    saveSpy.mockRestore()
  })
})
