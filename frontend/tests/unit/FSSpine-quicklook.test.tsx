import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import FSSpine from '../../src/components/Spine/FSSpine'
import { useProjects } from '../../src/stores/projects'
import { useSchema } from '../../src/stores/schema'
import { useQuickLook } from '../../src/stores/quicklook'
import { usePrompts } from '../../src/stores/prompts'
import { useModels } from '../../src/stores/models'

describe('FSSpine → QuickLook wiring', () => {
  beforeEach(() => {
    useProjects.setState({
      selectedId: 'p_test',
      projects: [{ project_id: 'p_test', name: 'us-invoice', active_version_id: 'v6' } as any],
    })
    useSchema.setState({ byProject: { p_test: [{ name: 'x', type: 'string', description: '' } as any] } })
    useQuickLook.getState().close()
    usePrompts.setState({
      list: { p_test: [
        { prompt_id: 'pr_baseline', label: 'Baseline', derived_from: null, is_active: true, created_at: 'x', updated_at: 'x' },
      ] },
      activeByProject: { p_test: { prompt_id: 'pr_baseline', label: 'Baseline', schema: [], global_notes: '', derived_from: null, created_at: 'x', updated_at: 'x' } as any },
      loading: {},
    })
    useModels.setState({
      list: { p_test: [
        { model_id: 'm_default', label: 'Default', provider: 'google', provider_model_id: 'gemini-2.0-flash', is_active: true, created_at: 'x' },
      ] },
      activeByProject: { p_test: { model_id: 'm_default', label: 'Default', provider: 'google', provider_model_id: 'gemini-2.0-flash', params: {}, created_at: 'x' } as any },
      loading: {},
    })
  })

  it('schema.json row no longer rendered', () => {
    render(<FSSpine />)
    expect(screen.queryByText('schema.json')).not.toBeInTheDocument()
    expect(screen.getByText('prompts/')).toBeInTheDocument()
    expect(screen.getByText('models/')).toBeInTheDocument()
  })

  it('clicking the active prompt row opens schema QuickLook', async () => {
    render(<FSSpine />)
    await userEvent.click(screen.getByText('prompts/'))
    await userEvent.click(screen.getByText('Baseline'))
    expect(useQuickLook.getState().target).toEqual({ kind: 'schema', pid: 'p_test' })
  })

  it('clicking a versions/vN leaf opens version QuickLook', async () => {
    render(<FSSpine />)
    // Need to expand versions/ first; default state only opens docs/.
    await userEvent.click(screen.getByText('versions/'))
    const v6 = screen.getByText('v6')
    await userEvent.click(v6)
    expect(useQuickLook.getState().target).toEqual({ kind: 'version', pid: 'p_test', versionId: 'v6' })
  })

  it('clicking docs/ folder header does not open QuickLook', async () => {
    render(<FSSpine />)
    const docsRow = screen.queryByText('docs/')
    if (docsRow) await userEvent.click(docsRow)
    expect(useQuickLook.getState().target).toBeNull()
  })
})
