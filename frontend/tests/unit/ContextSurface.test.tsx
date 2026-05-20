import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

import ContextSurface from '../../src/components/Context/ContextSurface'
import { useProjects } from '../../src/stores/projects'
import { useSchema } from '../../src/stores/schema'
import { useDocs } from '../../src/stores/docs'
import { useEval } from '../../src/stores/eval'

const PID = 'p_aaaaaaaaaaaa'
// Slug is the FE handle now; PID stays as the immutable internal anchor.
const SLUG = 'test'

beforeEach(() => {
  useProjects.setState({
    selectedSlug: SLUG,
    projects: [{ project_id: PID, slug: SLUG, name: 'test', project_type: 'extraction', active_version_id: 'v1' }],
  })
  useSchema.setState({ byProject: { [SLUG]: [{ name: 'x', type: 'string', description: '' }] }, loading: {} })
  useDocs.setState({ byProject: { [SLUG]: [] }, loading: false })
  // Stub fetch so the effect's loadEval call resolves immediately.
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({}) }))
  useEval.getState().reset()
})

describe('ContextSurface metrics section', () => {
  it('renders "no eval yet" when useEval slice is null', async () => {
    useEval.setState({ byProject: { [SLUG]: null }, loading: {} })
    render(<ContextSurface />)
    expect(await screen.findByText(/no eval yet/i)).toBeInTheDocument()
    expect(screen.queryByText('0.94')).not.toBeInTheDocument()  // placeholder gone
  })

  it('renders field accuracy / doc accuracy / coverage from snapshot', () => {
    useEval.setState({
      byProject: {
        [SLUG]: {
          n_docs: 5, n_reviewed: 5,
          field_accuracy_macro: 0.9,
          macro_f1: null,
          doc_accuracy: 0.8,
          errors: [],
          ts: '2026-05-11T07-04-00Z', schema_field_count: 2,
          per_field: [
            {
              field: 'a', accuracy: 1.0, correct: 5, total: 5,
              n_absent_both: 0, not_applicable: false,
            },
            {
              field: 'b', accuracy: 0.8, correct: 4, total: 5,
              n_absent_both: 0, not_applicable: false,
            },
          ],
        },
      },
      loading: {},
    })
    render(<ContextSurface />)
    // field accuracy: 90.0%
    expect(screen.getByText('90.0%')).toBeInTheDocument()
    // doc accuracy: 80.0%
    expect(screen.getByText('80.0%')).toBeInTheDocument()
    // coverage: 5/5 = 100%
    expect(screen.getByText('100%')).toBeInTheDocument()
    // header hint: "90.0% · 5 reviewed"
    expect(screen.getByText(/90\.0% · 5 reviewed/i)).toBeInTheDocument()
  })

  it('does not log the placeholder-deferred message', () => {
    const logSpy = vi.spyOn(console, 'log').mockImplementation(() => {})
    useEval.setState({ byProject: { [SLUG]: null }, loading: {} })
    render(<ContextSurface />)
    expect(logSpy).not.toHaveBeenCalledWith(expect.stringMatching(/placeholder/))
    logSpy.mockRestore()
  })
})
