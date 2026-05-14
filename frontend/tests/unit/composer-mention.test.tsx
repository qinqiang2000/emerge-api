import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// Mock the api module's listProjectTree so the mention menu's lazy fetch is
// deterministic and synchronous from the test's perspective. We must mock
// *before* importing Composer so the in-flight module-level import picks it up.
const ROOT: Array<{ name: string; kind: 'file' | 'dir'; path: string }> = [
  { name: 'docs', kind: 'dir', path: 'docs' },
  { name: 'versions', kind: 'dir', path: 'versions' },
  { name: 'schema.json', kind: 'file', path: 'schema.json' },
]
const DOCS: Array<{ name: string; kind: 'file' | 'dir'; path: string }> = [
  { name: 'invoice.pdf', kind: 'file', path: 'docs/invoice.pdf' },
]

const listProjectTreeMock = vi.fn(async (_pid: string, dir: string = '') => {
  if (dir === '') return ROOT
  if (dir === 'docs') return DOCS
  throw new Error('listProjectTree 404')
})

vi.mock('../../src/lib/api', () => ({
  listProjectTree: (pid: string, dir?: string) => listProjectTreeMock(pid, dir),
}))

import Composer from '../../src/components/Chat/Composer'

const PLACEHOLDER = 'say something to the agent, or type / for a command…'

describe('Composer @ mention', () => {
  beforeEach(() => {
    listProjectTreeMock.mockClear()
  })
  afterEach(() => {
    // No-op; mock state reset above.
  })

  it('typing @ opens the mention menu populated with root entries', async () => {
    const { container } = render(
      <Composer disabled={false} pending={[]} projectId="p_abc" onAttach={() => {}} onSubmit={() => {}} />,
    )
    const input = screen.getByPlaceholderText(PLACEHOLDER)
    await userEvent.type(input, '@')
    await waitFor(() => {
      expect(container.querySelector('.mentionmenu')).not.toBeNull()
    })
    await waitFor(() => {
      expect(screen.getByText(/schema\.json/)).toBeInTheDocument()
    })
    expect(screen.getByText(/docs/)).toBeInTheDocument()
  })

  it('typing @s filters to schema.json and Enter inserts "@schema.json "', async () => {
    const { container } = render(
      <Composer disabled={false} pending={[]} projectId="p_abc" onAttach={() => {}} onSubmit={() => {}} />,
    )
    const input = screen.getByPlaceholderText(PLACEHOLDER) as HTMLTextAreaElement
    await userEvent.type(input, '@s')
    await waitFor(() => {
      expect(container.querySelector('.mentionmenu')).not.toBeNull()
    })
    await waitFor(() => {
      expect(screen.getByText(/schema\.json/)).toBeInTheDocument()
    })
    // versions starts with 'v' so it must be filtered out; only schema.json remains.
    expect(screen.queryByText(/versions/)).toBeNull()

    await userEvent.keyboard('{Enter}')
    expect(input.value).toBe('@schema.json ')
    await waitFor(() => {
      expect(container.querySelector('.mentionmenu')).toBeNull()
    })
  })

  it('typing @docs/ drills into the dir and shows invoice.pdf', async () => {
    const { container } = render(
      <Composer disabled={false} pending={[]} projectId="p_abc" onAttach={() => {}} onSubmit={() => {}} />,
    )
    const input = screen.getByPlaceholderText(PLACEHOLDER)
    await userEvent.type(input, '@docs/')
    await waitFor(() => {
      expect(container.querySelector('.mentionmenu')).not.toBeNull()
    })
    await waitFor(() => {
      expect(screen.getByText(/invoice\.pdf/)).toBeInTheDocument()
    })
    // The breadcrumb shows the active dir.
    expect(container.querySelector('.mentionmenu .crumb')?.textContent).toBe('docs/')
  })

  it('email@example does NOT open the mention menu (@ not at token start)', async () => {
    const { container } = render(
      <Composer disabled={false} pending={[]} projectId="p_abc" onAttach={() => {}} onSubmit={() => {}} />,
    )
    const input = screen.getByPlaceholderText(PLACEHOLDER)
    await userEvent.type(input, 'email@x')
    // Give any pending effects a chance to flush.
    await new Promise(r => setTimeout(r, 10))
    expect(container.querySelector('.mentionmenu')).toBeNull()
  })

  it('without a projectId, typing @ opens the menu (projects-only, no tree fetch)', async () => {
    const { container } = render(
      <Composer disabled={false} pending={[]} onAttach={() => {}} onSubmit={() => {}} />,
    )
    const input = screen.getByPlaceholderText(PLACEHOLDER)
    await userEvent.type(input, '@')
    await waitFor(() => {
      expect(container.querySelector('.mentionmenu')).not.toBeNull()
    })
    // No tree fetch — there is no project to fetch from.
    expect(listProjectTreeMock).not.toHaveBeenCalled()
    // Crumb is suppressed in projects-only mode.
    expect(container.querySelector('.mentionmenu .crumb')).toBeNull()
  })

  it('projectId p_unset is treated as no-project: menu opens, tree fetch skipped', async () => {
    const { container } = render(
      <Composer disabled={false} pending={[]} projectId="p_unset" onAttach={() => {}} onSubmit={() => {}} />,
    )
    const input = screen.getByPlaceholderText(PLACEHOLDER)
    await userEvent.type(input, '@')
    await waitFor(() => {
      expect(container.querySelector('.mentionmenu')).not.toBeNull()
    })
    expect(listProjectTreeMock).not.toHaveBeenCalled()
    expect(container.querySelector('.mentionmenu .crumb')).toBeNull()
  })

  it('Esc closes the menu but leaves the text intact; reopens on a new @', async () => {
    const { container } = render(
      <Composer disabled={false} pending={[]} projectId="p_abc" onAttach={() => {}} onSubmit={() => {}} />,
    )
    const input = screen.getByPlaceholderText(PLACEHOLDER) as HTMLTextAreaElement
    await userEvent.type(input, '@s')
    await waitFor(() => {
      expect(container.querySelector('.mentionmenu')).not.toBeNull()
    })
    await userEvent.keyboard('{Escape}')
    expect(container.querySelector('.mentionmenu')).toBeNull()
    // Text untouched — the `@s` token is still there verbatim.
    expect(input.value).toBe('@s')
    // A fresh `@` later in the text starts a new token, menu reopens.
    await userEvent.type(input, ' @')
    await waitFor(() => {
      expect(container.querySelector('.mentionmenu')).not.toBeNull()
    })
    expect(input.value).toBe('@s @')
  })
})
