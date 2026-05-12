import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import FSSpine from '../../src/components/Spine/FSSpine'
import { useProjects } from '../../src/stores/projects'
import { useSchema } from '../../src/stores/schema'
import { useQuickLook } from '../../src/stores/quicklook'

describe('FSSpine → QuickLook wiring', () => {
  beforeEach(() => {
    useProjects.setState({
      selectedId: 'p_test',
      projects: [{ project_id: 'p_test', name: 'us-invoice', active_version_id: 'v6' } as any],
    })
    useSchema.setState({ byProject: { p_test: [{ name: 'x', type: 'string', description: '' } as any] } })
    useQuickLook.getState().close()
  })

  it('clicking schema.json row opens schema QuickLook', async () => {
    render(<FSSpine />)
    await userEvent.click(screen.getByText('schema.json'))
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
