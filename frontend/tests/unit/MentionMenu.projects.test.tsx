// frontend/tests/unit/MentionMenu.projects.test.tsx
//
// Coverage for the projects category that lives at the top of the `@` mention
// menu (slug-transparency milestone). When the user types `@` (no slash yet)
// inside the composer, the projects list filters by slug prefix + name
// substring; selecting an entry inserts `@<slug> ` so the agent can see the
// folder name verbatim. Once the user types a slash (`@docs/`, etc.) the
// projects category disappears and only the tree entries section remains.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// Tree fetcher mock — kept tiny so the projects category dominates and the
// activeIdx math stays deterministic.
const TREE_ROOT: Array<{ name: string; kind: 'file' | 'dir'; path: string }> = [
  { name: 'docs', kind: 'dir', path: 'docs' },
  { name: 'README.md', kind: 'file', path: 'README.md' },
]
const listProjectTreeMock = vi.fn(async (_slug: string, dir: string = '') => {
  if (dir === '') return TREE_ROOT
  throw new Error('listProjectTree 404')
})
vi.mock('../../src/lib/api', () => ({
  listProjectTree: (slug: string, dir?: string) => listProjectTreeMock(slug, dir),
}))

// Seed the projects store with two slug-named projects: one ASCII, one CJK.
import { useProjects } from '../../src/stores/projects'
import Composer from '../../src/components/Chat/Composer'

const PLACEHOLDER = 'say something to the agent, or type / for a command…'

function seedProjects() {
  useProjects.setState({
    projects: [
      { project_id: 'p_111111111111', slug: 'us-invoice', name: 'US Invoice',
        project_type: 'extraction', active_version_id: 'v1' },
      // Distinct slug + name to exercise both prefix-on-slug and
      // substring-on-name matching paths without ambiguity in querySelector.
      { project_id: 'p_222222222222', slug: '美国发票项目', name: 'CN Invoice',
        project_type: 'extraction', active_version_id: null },
      { project_id: 'p_333333333333', slug: 'invoices-de', name: 'DE Invoices',
        project_type: 'extraction', active_version_id: null },
    ],
    selectedSlug: 'us-invoice',
    loading: false,
  })
}

describe('Composer @ mention — projects category', () => {
  beforeEach(() => {
    listProjectTreeMock.mockClear()
    seedProjects()
  })
  afterEach(() => {
    useProjects.setState({ projects: [], selectedSlug: null, loading: false })
  })

  it('typing @ shows projects section at the top', async () => {
    const { container } = render(
      <Composer disabled={false} pending={[]} projectId="us-invoice" onAttach={() => {}} onSubmit={() => {}} />,
    )
    const input = screen.getByPlaceholderText(PLACEHOLDER)
    await userEvent.type(input, '@')
    await waitFor(() => {
      expect(container.querySelector('.mentionmenu')).not.toBeNull()
    })
    // All three projects are listed when query is empty.
    expect(screen.getByText('US Invoice')).toBeInTheDocument()
    expect(screen.getByText('CN Invoice')).toBeInTheDocument()
    expect(screen.getByText('DE Invoices')).toBeInTheDocument()
    // The CJK slug is surfaced in the right-aligned slug-hint
    expect(container.querySelector('.slug-hint')?.textContent).toMatch(/us-invoice|美国发票项目|invoices-de/)
    // Section label visible
    const labels = container.querySelectorAll('.section-label')
    expect(labels.length).toBeGreaterThan(0)
  })

  it('@inv filters projects by slug prefix and name substring', async () => {
    const { container } = render(
      <Composer disabled={false} pending={[]} projectId="us-invoice" onAttach={() => {}} onSubmit={() => {}} />,
    )
    const input = screen.getByPlaceholderText(PLACEHOLDER)
    await userEvent.type(input, '@inv')
    await waitFor(() => {
      expect(container.querySelector('.mentionmenu')).not.toBeNull()
    })
    // `invoices-de` matches by slug prefix; `US Invoice` matches by name
    // substring ("Invoice" includes "inv"); `CN Invoice` matches by name
    // substring too.
    expect(screen.getByText('DE Invoices')).toBeInTheDocument()
    expect(screen.getByText('US Invoice')).toBeInTheDocument()
    expect(screen.getByText('CN Invoice')).toBeInTheDocument()
  })

  it('@美 matches the CJK-named project via slug prefix', async () => {
    const { container } = render(
      <Composer disabled={false} pending={[]} projectId="us-invoice" onAttach={() => {}} onSubmit={() => {}} />,
    )
    const input = screen.getByPlaceholderText(PLACEHOLDER)
    await userEvent.type(input, '@美')
    await waitFor(() => {
      expect(container.querySelector('.mentionmenu')).not.toBeNull()
    })
    // Only the CJK-slug project matches: `美国发票项目` → slug prefix match.
    expect(screen.getByText('CN Invoice')).toBeInTheDocument()
    expect(screen.queryByText('US Invoice')).toBeNull()
    expect(screen.queryByText('DE Invoices')).toBeNull()
  })

  it('selecting a project inserts @<slug> verbatim and closes the menu', async () => {
    const { container } = render(
      <Composer disabled={false} pending={[]} projectId="us-invoice" onAttach={() => {}} onSubmit={() => {}} />,
    )
    const input = screen.getByPlaceholderText(PLACEHOLDER) as HTMLTextAreaElement
    await userEvent.type(input, '@美')
    await waitFor(() => {
      expect(container.querySelector('.mentionmenu')).not.toBeNull()
    })
    // The first (and only) match is auto-selected; Enter inserts.
    await userEvent.keyboard('{Enter}')
    expect(input.value).toBe('@美国发票项目 ')
    await waitFor(() => {
      expect(container.querySelector('.mentionmenu')).toBeNull()
    })
  })

  it('once the user types <name>/ the projects category disappears', async () => {
    const { container } = render(
      <Composer disabled={false} pending={[]} projectId="us-invoice" onAttach={() => {}} onSubmit={() => {}} />,
    )
    const input = screen.getByPlaceholderText(PLACEHOLDER)
    await userEvent.type(input, '@docs/')
    await waitFor(() => {
      expect(container.querySelector('.mentionmenu')).not.toBeNull()
    })
    // No projects visible inside a dir context — tree entries only.
    expect(screen.queryByText('US Invoice')).toBeNull()
    expect(screen.queryByText('美国发票项目')).toBeNull()
    expect(screen.queryByText('DE Invoices')).toBeNull()
  })

  it('empty hero (no projectId) — typing @ still surfaces the projects section', async () => {
    // Regression: a prior gate (`!projectId`) suppressed the entire menu when
    // no project was selected, breaking the digital-colleague entry path
    // where the user picks a project by `@<slug>` before any other context.
    const { container } = render(
      <Composer disabled={false} pending={[]} onAttach={() => {}} onSubmit={() => {}} />,
    )
    const input = screen.getByPlaceholderText(PLACEHOLDER)
    await userEvent.type(input, '@')
    await waitFor(() => {
      expect(container.querySelector('.mentionmenu')).not.toBeNull()
    })
    expect(screen.getByText('US Invoice')).toBeInTheDocument()
    expect(screen.getByText('CN Invoice')).toBeInTheDocument()
    expect(screen.getByText('DE Invoices')).toBeInTheDocument()
    // No tree-side affordances in projects-only mode.
    expect(container.querySelector('.mentionmenu .crumb')).toBeNull()
    expect(listProjectTreeMock).not.toHaveBeenCalled()
  })

  it('empty hero — selecting a project inserts @<slug> without touching selectedSlug', async () => {
    // The mention is a textual handle for the agent, not a UI navigation
    // action; selecting a project from the menu must not implicitly switch
    // the currently-selected project (composer stays in p_unset until the
    // user clicks the sidebar or sends the message).
    const { container } = render(
      <Composer disabled={false} pending={[]} onAttach={() => {}} onSubmit={() => {}} />,
    )
    const input = screen.getByPlaceholderText(PLACEHOLDER) as HTMLTextAreaElement
    const selectedBefore = useProjects.getState().selectedSlug
    await userEvent.type(input, '@美')
    await waitFor(() => {
      expect(container.querySelector('.mentionmenu')).not.toBeNull()
    })
    await userEvent.keyboard('{Enter}')
    expect(input.value).toBe('@美国发票项目 ')
    expect(useProjects.getState().selectedSlug).toBe(selectedBefore)
  })
})
