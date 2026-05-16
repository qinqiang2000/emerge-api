import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import SchemaQuickLook from '../../src/components/QuickLook/SchemaQuickLook'
import { useQuickLook } from '../../src/stores/quicklook'
import { useProjects } from '../../src/stores/projects'
import { useSchema } from '../../src/stores/schema'
import { usePrompts } from '../../src/stores/prompts'

describe('SchemaQuickLook', () => {
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
    const { container } = render(<SchemaQuickLook />)
    expect(container.firstChild).toBeNull()
  })

  it('opens with fields tab by default', () => {
    useQuickLook.getState().openSchema('p_test')
    render(<SchemaQuickLook />)
    expect(screen.getByText('prompts/active')).toBeInTheDocument()
    expect(screen.getByText('invoice_number')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /fields/i })).toHaveClass('ql-tab--active')
  })

  it('Esc key closes the sheet', async () => {
    useQuickLook.getState().openSchema('p_test')
    render(<SchemaQuickLook />)
    await userEvent.keyboard('{Escape}')
    expect(useQuickLook.getState().target).toBeNull()
  })

  it('scrim click closes the sheet', async () => {
    useQuickLook.getState().openSchema('p_test')
    render(<SchemaQuickLook />)
    await userEvent.click(screen.getByTestId('ql-scrim'))
    expect(useQuickLook.getState().target).toBeNull()
  })

  it('click on sheet body does not close', async () => {
    useQuickLook.getState().openSchema('p_test')
    render(<SchemaQuickLook />)
    await userEvent.click(screen.getByText('prompts/active'))
    expect(useQuickLook.getState().target).not.toBeNull()
  })

  it('switching project closes the sheet', () => {
    useQuickLook.getState().openSchema('p_test')
    render(<SchemaQuickLook />)
    useProjects.setState({ selectedSlug: 'p_other' })
    expect(useQuickLook.getState().target).toBeNull()
  })

  it('tab click switches between fields and raw json', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response('[]', { status: 200, headers: { 'content-type': 'text/plain' } }),
    )
    useQuickLook.getState().openSchema('p_test')
    render(<SchemaQuickLook />)
    await userEvent.click(screen.getByRole('button', { name: /raw json/i }))
    expect(screen.getByRole('button', { name: /raw json/i })).toHaveClass('ql-tab--active')
  })

  it('footer renders the description-vs-notes hint', () => {
    useQuickLook.getState().openSchema('p_test')
    render(<SchemaQuickLook />)
    expect(screen.getByText(/description goes into the prompt/i)).toBeInTheDocument()
    expect(screen.getByText(/feed AutoResearch/i)).toBeInTheDocument()
  })
})
