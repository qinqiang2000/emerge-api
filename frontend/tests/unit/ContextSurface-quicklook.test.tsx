import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ContextSurface from '../../src/components/Context/ContextSurface'
import { useProjects } from '../../src/stores/projects'
import { useSchema } from '../../src/stores/schema'
import { useQuickLook } from '../../src/stores/quicklook'
import { usePrompts } from '../../src/stores/prompts'
import { useModels } from '../../src/stores/models'

const TEN_FIELDS = Array.from({ length: 10 }, (_, i) => ({
  name: `f_${i}`,
  type: 'string' as const,
  description: '',
}))

describe('ContextSurface → QuickLook wiring', () => {
  beforeEach(() => {
    useProjects.setState({
      selectedId: 'p_test',
      projects: [{ project_id: 'p_test', name: 'x', active_version_id: 'v6' } as any],
    })
    useSchema.setState({ byProject: { p_test: TEN_FIELDS } })
    useQuickLook.getState().close()
    usePrompts.setState({
      list: { p_test: [{ prompt_id: 'pr_baseline', label: 'Baseline', derived_from: null, is_active: true, created_at: 'x', updated_at: 'x' }] },
      activeByProject: { p_test: { prompt_id: 'pr_baseline', label: 'Baseline', schema: [], global_notes: '', derived_from: null, created_at: 'x', updated_at: 'x' } as any },
      loading: {},
    })
    useModels.setState({
      list: { p_test: [{ model_id: 'm_default', label: 'Default', provider: 'google', provider_model_id: 'gemini-2.0-flash', is_active: true, created_at: 'x' }] },
      activeByProject: { p_test: { model_id: 'm_default', label: 'Default', provider: 'google', provider_model_id: 'gemini-2.0-flash', params: {}, created_at: 'x' } as any },
      loading: {},
    })
  })

  it('clicking Prompt card title opens QuickLook', async () => {
    render(<ContextSurface />)
    await userEvent.click(screen.getByText(/Prompt:.*pr_baseline/))
    expect(useQuickLook.getState().target).toEqual({ kind: 'schema', pid: 'p_test' })
  })

  it('clicking "+ N more" row opens QuickLook', async () => {
    render(<ContextSurface />)
    await userEvent.click(screen.getByText(/\+ 3 more/))
    expect(useQuickLook.getState().target).toEqual({ kind: 'schema', pid: 'p_test' })
  })

  it('renders Prompt card with active prompt id + field count', () => {
    render(<ContextSurface />)
    expect(screen.getByText(/Prompt:.*pr_baseline/)).toBeInTheDocument()
    expect(screen.getByText(/10 fields/)).toBeInTheDocument()
  })

  it('renders Model card with active model label + provider_model_id', () => {
    render(<ContextSurface />)
    expect(screen.getAllByText(/Default/).length).toBeGreaterThan(0)
    expect(screen.getAllByText('gemini-2.0-flash').length).toBeGreaterThan(0)
  })
})
