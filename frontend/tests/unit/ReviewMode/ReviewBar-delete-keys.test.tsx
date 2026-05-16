// Title chip, two-step delete trigger, and ←/→ keyboard nav for review mode.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ReviewOverlay from '../../../src/components/ReviewMode/ReviewOverlay'
import { useDocs } from '../../../src/stores/docs'
import { useExperiments } from '../../../src/stores/experiments'
import { useModels } from '../../../src/stores/models'
import { useReview } from '../../../src/stores/review'
import { useSchema } from '../../../src/stores/schema'
import type { DocSummary } from '../../../src/types/review'

const SCHEMA = [{ name: 'supplier', type: 'string', description: 'supplier name' }]

function makeDoc(filename: string, has_reviewed = false): DocSummary {
  return {
    filename,
    ext: 'pdf',
    page_count: 1,
    sha256: filename,
    uploaded_at: '2026-05-16',
    original_name: filename,
    has_prediction: false,
    has_reviewed,
  }
}

function seedAt(active: string, docs: DocSummary[]) {
  useSchema.setState({ byProject: { 'p_x': SCHEMA as never } })
  useDocs.setState({ byProject: { 'p_x': docs } })
  useExperiments.setState({ list: { 'p_x': [] }, loading: {} })
  useModels.setState({ list: { 'p_x': [] }, activeByProject: {}, loading: {} })
  useReview.setState({
    activeProjectId: 'p_x', activeFilename: active,
    entities: [{ supplier: 'X' }], evidence: null, notes: {},
    activeTabKey: 'active', predictionsByExp: {},
    loading: false, saving: false, err: null, page: 1, pageCount: 1,
  })
}

describe('ReviewBar title + delete + keyboard', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => [],
    }))
  })

  it('renders "reviewing <filename> <status>" matching the design copy', () => {
    seedAt('2024-Q4-soylent.pdf', [makeDoc('2024-Q4-soylent.pdf', false)])
    render(<ReviewOverlay onBack={() => {}} />)
    const title = document.querySelector('.rev-bar .title') as HTMLElement
    expect(title).toBeTruthy()
    expect(title.textContent).toContain('reviewing')
    // chip carries the bare filename — no `docs/` prefix
    expect(title.querySelector('.doc')?.textContent).toBe('2024-Q4-soylent.pdf')
    expect(title.querySelector('.status')?.textContent).toBe('pending')
  })

  it('status pill flips to "reviewed" when has_reviewed is true', () => {
    seedAt('done.pdf', [makeDoc('done.pdf', true)])
    render(<ReviewOverlay onBack={() => {}} />)
    const status = document.querySelector('.rev-bar .title .status')
    expect(status?.textContent).toBe('reviewed')
  })

  it('right-arrow key advances to the next doc', () => {
    seedAt('a.pdf', [makeDoc('a.pdf'), makeDoc('b.pdf'), makeDoc('c.pdf')])
    const openSpy = vi.fn(async () => {})
    useReview.setState({ open: openSpy } as never)
    render(<ReviewOverlay onBack={() => {}} />)
    fireEvent.keyDown(window, { key: 'ArrowRight' })
    expect(openSpy).toHaveBeenCalledWith('p_x', 'b.pdf')
  })

  it('left-arrow key steps back', () => {
    seedAt('b.pdf', [makeDoc('a.pdf'), makeDoc('b.pdf')])
    const openSpy = vi.fn(async () => {})
    useReview.setState({ open: openSpy } as never)
    render(<ReviewOverlay onBack={() => {}} />)
    fireEvent.keyDown(window, { key: 'ArrowLeft' })
    expect(openSpy).toHaveBeenCalledWith('p_x', 'a.pdf')
  })

  it('typing in an editable value swallows the arrow keys (no nav)', () => {
    seedAt('a.pdf', [makeDoc('a.pdf'), makeDoc('b.pdf')])
    const openSpy = vi.fn(async () => {})
    useReview.setState({ open: openSpy } as never)
    render(<ReviewOverlay onBack={() => {}} />)
    const val = document.querySelector('[contenteditable="true"]') as HTMLElement
    expect(val).toBeTruthy()
    fireEvent.keyDown(val, { key: 'ArrowRight' })
    expect(openSpy).not.toHaveBeenCalled()
  })

  it('first trash click arms; second click runs delete + jumps to next', async () => {
    seedAt('a.pdf', [makeDoc('a.pdf'), makeDoc('b.pdf')])
    const openSpy = vi.fn(async () => {})
    const removeSpy = vi.fn(async () => {})
    useReview.setState({ open: openSpy } as never)
    useDocs.setState({ remove: removeSpy } as never)
    render(<ReviewOverlay onBack={() => {}} />)
    const trash = screen.getByRole('button', { name: /delete this file/i })
    fireEvent.click(trash)
    expect(screen.getByText(/confirm/i)).toBeInTheDocument()
    expect(removeSpy).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: /again to confirm/i }))
    await waitFor(() => expect(removeSpy).toHaveBeenCalledWith('p_x', 'a.pdf'))
    expect(openSpy).toHaveBeenCalledWith('p_x', 'b.pdf')
  })

  it('deleting the last remaining doc falls back to onBack()', async () => {
    seedAt('only.pdf', [makeDoc('only.pdf')])
    const removeSpy = vi.fn(async () => {})
    useDocs.setState({ remove: removeSpy } as never)
    const onBack = vi.fn()
    render(<ReviewOverlay onBack={onBack} />)
    const trash = screen.getByRole('button', { name: /delete this file/i })
    fireEvent.click(trash)
    fireEvent.click(screen.getByRole('button', { name: /again to confirm/i }))
    await waitFor(() => expect(removeSpy).toHaveBeenCalledWith('p_x', 'only.pdf'))
    expect(onBack).toHaveBeenCalled()
  })

  it('Backspace arms; second Backspace confirms delete', async () => {
    seedAt('a.pdf', [makeDoc('a.pdf'), makeDoc('b.pdf')])
    const openSpy = vi.fn(async () => {})
    const removeSpy = vi.fn(async () => {})
    useReview.setState({ open: openSpy } as never)
    useDocs.setState({ remove: removeSpy } as never)
    render(<ReviewOverlay onBack={() => {}} />)
    fireEvent.keyDown(window, { key: 'Backspace' })
    expect(screen.getByText(/confirm/i)).toBeInTheDocument()
    expect(removeSpy).not.toHaveBeenCalled()
    fireEvent.keyDown(window, { key: 'Backspace' })
    await waitFor(() => expect(removeSpy).toHaveBeenCalledWith('p_x', 'a.pdf'))
  })

  it('Esc cancels armed delete', () => {
    seedAt('a.pdf', [makeDoc('a.pdf')])
    const removeSpy = vi.fn(async () => {})
    useDocs.setState({ remove: removeSpy } as never)
    render(<ReviewOverlay onBack={() => {}} />)
    fireEvent.keyDown(window, { key: 'Backspace' })
    expect(screen.getByText(/confirm/i)).toBeInTheDocument()
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.queryByText(/confirm/i)).not.toBeInTheDocument()
    expect(removeSpy).not.toHaveBeenCalled()
  })

  it('typing in an editable value swallows Backspace (no arm)', () => {
    seedAt('a.pdf', [makeDoc('a.pdf')])
    render(<ReviewOverlay onBack={() => {}} />)
    const val = document.querySelector('[contenteditable="true"]') as HTMLElement
    expect(val).toBeTruthy()
    fireEvent.keyDown(val, { key: 'Backspace' })
    expect(screen.queryByText(/confirm/i)).not.toBeInTheDocument()
  })
})
