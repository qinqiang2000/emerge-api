import { render, screen, fireEvent } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import FSSpine from '../../src/components/Spine/FSSpine'
import { useDocs } from '../../src/stores/docs'
import { useExperiments } from '../../src/stores/experiments'
import { useModels } from '../../src/stores/models'
import { useProjects } from '../../src/stores/projects'
import { usePrompts } from '../../src/stores/prompts'
import { useSchema } from '../../src/stores/schema'

// Post-slug-transparency: stores are keyed by slug, not pid. We pick `demo`
// as both the slug and the display name to mirror the typical agent-created
// case (slug derived from name).
const SLUG = 'demo'

function seedAll() {
  useProjects.setState({
    projects: [{
      project_id: 'p_x', slug: SLUG, name: 'demo',
      project_type: 'extraction', active_version_id: 'v1',
      status: 'live' as const,
    }],
    selectedSlug: SLUG,
  })
  useDocs.setState({ byProject: { [SLUG]: [] } })
  useSchema.setState({ byProject: { [SLUG]: [] } })
  usePrompts.setState({ list: { [SLUG]: [] }, activeByProject: {}, loading: {} })
  useModels.setState({ list: { [SLUG]: [] }, activeByProject: {}, loading: {} })
  useExperiments.setState({
    list: { [SLUG]: [
      { experiment_id: 'ex_a', label: 'try gemma', prompt_id: 'pr', model_id: 'm',
        status: 'ran', created_at: '2026-05-13', score: 0.91 },
      { experiment_id: 'ex_b', label: 'try notes', prompt_id: 'pr', model_id: 'm',
        status: 'draft', created_at: '2026-05-13', score: null },
    ] },
    loading: {},
  })
}

describe('FSSpine experiments/ group', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => [],
    }))
    seedAll()
  })

  it('renders the experiments/ group with experiment rows', () => {
    render(<FSSpine />)
    // The group exists (closed by default — like prompts/ and models/)
    expect(screen.getByText('experiments/')).toBeInTheDocument()
    // Expand it
    fireEvent.click(screen.getByText('experiments/'))
    // Both experiment rows appear
    expect(screen.getByText('try gemma')).toBeInTheDocument()
    expect(screen.getByText('try notes')).toBeInTheDocument()
  })

  it('shows score for ran experiments and status stamp', () => {
    render(<FSSpine />)
    fireEvent.click(screen.getByText('experiments/'))
    // The ran experiment shows a score in its stamp area; the draft has no score
    expect(screen.getByText(/0\.91/)).toBeInTheDocument()
    // status indicators visible (could be inline text like 'ran' / 'draft' depending on impl)
    expect(screen.getByText(/ran/i)).toBeInTheDocument()
  })

  it('shows (none yet) when project has no experiments', () => {
    useExperiments.setState({ list: { [SLUG]: [] }, loading: {} })
    render(<FSSpine />)
    fireEvent.click(screen.getByText('experiments/'))
    expect(screen.getByText('(none yet)')).toBeInTheDocument()
  })

  it('archived experiments are still listed in the experiments/ group', () => {
    // T12's useExperiments.list does NOT include archived by default — but if
    // they ever appear, FSSpine should still render them. Confirm this is wired
    // by injecting an archived row directly.
    useExperiments.setState({
      list: { [SLUG]: [
        { experiment_id: 'ex_arc', label: 'old try', prompt_id: 'pr', model_id: 'm',
          status: 'archived', created_at: '2026-05-13', score: null },
      ] },
      loading: {},
    })
    render(<FSSpine />)
    fireEvent.click(screen.getByText('experiments/'))
    // If your impl filters archived OUT, this assertion will fail —
    // remove this test if you've decided to filter at the FSSpine layer
    expect(screen.getByText('old try')).toBeInTheDocument()
  })
})
