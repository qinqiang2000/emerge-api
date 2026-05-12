import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ContextSurface from '../../src/components/Context/ContextSurface'
import { useProjects } from '../../src/stores/projects'
import { useSchema } from '../../src/stores/schema'
import { useQuickLook } from '../../src/stores/quicklook'

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
  })

  it('clicking schema.json card title opens QuickLook', async () => {
    render(<ContextSurface />)
    await userEvent.click(screen.getByText('schema.json'))
    expect(useQuickLook.getState().target).toEqual({ kind: 'schema', pid: 'p_test' })
  })

  it('clicking "+ N more" row opens QuickLook', async () => {
    render(<ContextSurface />)
    await userEvent.click(screen.getByText(/\+ 3 more/))
    expect(useQuickLook.getState().target).toEqual({ kind: 'schema', pid: 'p_test' })
  })
})
