import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

import ContextSurface from '../../src/components/Context/ContextSurface'
import { useProjects } from '../../src/stores/projects'
import { useSchema } from '../../src/stores/schema'
import { useDocs } from '../../src/stores/docs'
import { useEval } from '../../src/stores/eval'

const PID = 'p_aaaaaaaaaaaa'

beforeEach(() => {
  useProjects.setState({
    selectedId: PID,
    projects: [{ project_id: PID, name: 'test', project_type: 'extraction', active_version_id: 'v1' }],
  })
  useSchema.setState({ byProject: { [PID]: [{ name: 'x', type: 'string', description: '' }] }, loading: {} })
  useDocs.setState({ byProject: { [PID]: [] }, loading: false })
  // Stub fetch so the effect's loadEval call resolves immediately.
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({}) }))
  useEval.getState().reset()
})

describe('ContextSurface metrics section', () => {
  it('renders "no eval yet" when useEval slice is null', async () => {
    useEval.setState({ byProject: { [PID]: null }, loading: {} })
    render(<ContextSurface />)
    expect(await screen.findByText(/no eval yet/i)).toBeInTheDocument()
    expect(screen.queryByText('0.94')).not.toBeInTheDocument()  // placeholder gone
  })

  it('renders macro precision / recall / f1 / coverage from snapshot', () => {
    useEval.setState({
      byProject: {
        [PID]: {
          n_docs: 5, n_reviewed: 5, macro_f1: 0.92, errors: [],
          ts: '2026-05-11T07-04-00Z', schema_field_count: 2,
          per_field: [
            { field: 'a', tp: 5, fp: 0, fn: 0, support: 5, precision: 1.0, recall: 1.0, f1: 1.0 },
            { field: 'b', tp: 4, fp: 1, fn: 1, support: 5, precision: 0.8, recall: 0.8, f1: 0.8 },
          ],
        },
      },
      loading: {},
    })
    render(<ContextSurface />)
    // precision row: (1.0 + 0.8) / 2 = 0.90  (recall also 0.90 — same mean)
    expect(screen.getAllByText('0.90')).toHaveLength(2)
    // f1: macro_f1 from backend
    expect(screen.getByText('0.92')).toBeInTheDocument()
    // coverage: 5/5 = 100%
    expect(screen.getByText('100%')).toBeInTheDocument()
    // header hint: "macro 0.92 · 5 reviewed"
    expect(screen.getByText(/macro 0\.92 · 5 reviewed/i)).toBeInTheDocument()
  })

  it('does not log the placeholder-deferred message', () => {
    const logSpy = vi.spyOn(console, 'log').mockImplementation(() => {})
    useEval.setState({ byProject: { [PID]: null }, loading: {} })
    render(<ContextSurface />)
    expect(logSpy).not.toHaveBeenCalledWith(expect.stringMatching(/placeholder/))
    logSpy.mockRestore()
  })
})
