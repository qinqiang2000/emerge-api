import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import SchemaQuickLook from '../../src/components/QuickLook/SchemaQuickLook'
import { useQuickLook } from '../../src/stores/quicklook'
import { useProjects } from '../../src/stores/projects'
import { useSchema } from '../../src/stores/schema'

describe('SchemaQuickLook', () => {
  beforeEach(() => {
    useQuickLook.getState().close()
    useProjects.setState({ selectedId: 'p_test', projects: [
      { project_id: 'p_test', name: 'us-invoice', active_version_id: 'v6' } as any,
    ] })
    useSchema.setState({ byProject: { p_test: [
      { name: 'invoice_number', type: 'string', description: 'the id', required: true } as any,
    ] } })
  })

  it('renders nothing when target is null', () => {
    const { container } = render(<SchemaQuickLook />)
    expect(container.firstChild).toBeNull()
  })

  it('opens with fields tab by default', () => {
    useQuickLook.getState().openSchema('p_test')
    render(<SchemaQuickLook />)
    expect(screen.getByText('schema.json')).toBeInTheDocument()
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
    await userEvent.click(screen.getByText('schema.json'))
    expect(useQuickLook.getState().target).not.toBeNull()
  })

  it('switching project closes the sheet', () => {
    useQuickLook.getState().openSchema('p_test')
    render(<SchemaQuickLook />)
    useProjects.setState({ selectedId: 'p_other' })
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
