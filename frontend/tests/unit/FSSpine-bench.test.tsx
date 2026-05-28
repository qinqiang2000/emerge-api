// T8 — FSSpine `experiments/` group header gains a small ↗ icon button that
// opens the Bench leaderboard (`?bench=1`). The icon must NOT replace the
// existing toggleDir behaviour (arrow / group-name click still expands/
// collapses) and must NOT appear on any other group.
import { render, screen, fireEvent } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import FSSpine from '../../src/components/Spine/FSSpine'
import { useDocs } from '../../src/stores/docs'
import { useExperiments } from '../../src/stores/experiments'
import { useModels } from '../../src/stores/models'
import { useProjects } from '../../src/stores/projects'
import { usePrompts } from '../../src/stores/prompts'
import { useSchema } from '../../src/stores/schema'

const SLUG = 'demo'

function seedAll(slug: string | null = SLUG) {
  if (slug) {
    useProjects.setState({
      projects: [{
        project_id: 'p_x', slug, name: slug,
        project_type: 'extraction', active_version_id: 'v1',
        status: 'live' as const,
      }],
      selectedSlug: slug,
    } as any)
    useDocs.setState({ byProject: { [slug]: [] } } as any)
    useSchema.setState({ byProject: { [slug]: [] } } as any)
    usePrompts.setState({ list: { [slug]: [] }, activeByProject: {}, loading: {} } as any)
    useModels.setState({ list: { [slug]: [] }, activeByProject: {}, loading: {} } as any)
    useExperiments.setState({
      list: { [slug]: [
        { experiment_id: 'ex_a', label: 'try gemma', prompt_id: 'pr', model_id: 'm',
          status: 'ran', created_at: '2026-05-13', score: 0.91 },
      ] },
      loading: {},
    } as any)
  } else {
    useProjects.setState({ projects: [], selectedSlug: null } as any)
  }
}

describe('FSSpine experiments/ → bench ↗ entry', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => [],
    }))
    // Reset history search before each test so popstate-driven assertions
    // are unambiguous across cases.
    window.history.replaceState(null, '', '/p/' + SLUG)
    seedAll(SLUG)
  })

  it('renders a ↗ icon button on the experiments/ group header (and not on others)', () => {
    render(<FSSpine />)
    // The ↗ button uses an accessible name we can find with getByRole. Other
    // groups (docs/, prompts/, models/, metrics/, versions/) must NOT expose
    // an "open bench" button.
    const buttons = screen.getAllByRole('button', { name: /open bench/i })
    expect(buttons).toHaveLength(1)
  })

  it('clicking the ↗ icon pushes ?bench=1 into the URL', () => {
    render(<FSSpine />)
    const btn = screen.getByRole('button', { name: /open bench/i })
    fireEvent.click(btn)
    expect(window.location.search.includes('bench=1')).toBe(true)
  })

  it('clicking the ↗ icon does not toggle the experiments/ group open', () => {
    render(<FSSpine />)
    // Pre-condition — experiments/ is closed by default so its child row
    // ("try gemma") is NOT in the DOM.
    expect(screen.queryByText('try gemma')).not.toBeInTheDocument()

    const btn = screen.getByRole('button', { name: /open bench/i })
    fireEvent.click(btn)

    // Post — still closed: click stopPropagation prevented toggleDir.
    expect(screen.queryByText('try gemma')).not.toBeInTheDocument()
  })

  it('hides (or disables) the ↗ icon when no project is selected', () => {
    seedAll(null)
    render(<FSSpine />)
    // No active project ⇒ no experiments/ group, no ↗ button.
    const btn = screen.queryByRole('button', { name: /open bench/i })
    if (btn) {
      expect(btn).toBeDisabled()
    } else {
      expect(btn).toBeNull()
    }
  })
})
