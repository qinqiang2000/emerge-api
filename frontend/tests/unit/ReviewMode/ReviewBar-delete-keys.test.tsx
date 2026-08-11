// Title chip, two-step delete trigger, and ←/→ keyboard nav for review mode.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ReviewOverlay from '../../../src/components/ReviewMode/ReviewOverlay'
import { navigateToReview } from '../../../src/lib/slugUrl'
import { useDocs } from '../../../src/stores/docs'
import { useExperiments } from '../../../src/stores/experiments'
import { useModels } from '../../../src/stores/models'
import { useReview } from '../../../src/stores/review'
import { useSchema } from '../../../src/stores/schema'
import { useTextlayer } from '../../../src/stores/textlayer'
import { useTranslate } from '../../../src/stores/translate'
import { useReviewTune } from '../../../src/stores/reviewTune'
import type { DocSummary } from '../../../src/types/review'

// Doc nav goes through the URL, not `store.open` — `?review=<filename>` has to
// track the doc actually shown, and App's URL→store effect drives the open.
// These tests used to spy on `open` and had silently stopped covering ←/→ at
// all (the spy was simply never called); assert on the real hop instead.
vi.mock('../../../src/lib/slugUrl', async (orig) => {
  const real = await orig<typeof import('../../../src/lib/slugUrl')>()
  return { ...real, navigateToReview: vi.fn() }
})
const navSpy = vi.mocked(navigateToReview)

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
    // Shaped like a textlayer payload, NOT `[]`. A shapeless `ready` entry
    // crashes PageOverlays on `payload.spans.length`, React unmounts the tree,
    // and the ←/→ key handler that these tests exercise never gets registered —
    // three of them failed for that reason alone, not for anything about nav.
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({ spans: [], page_w: 612, page_h: 792 }),
    }))
    // Zustand stores persist across tests in a file, so a prior render's
    // entry bleeds into the next test's first synchronous render. Reset.
    useTextlayer.setState({ byKey: {} })
    useTranslate.setState({ byKey: {} })
    useReviewTune.setState({ signal: null, dismissedKey: null })
    navSpy.mockClear()
  })

  it('renders "<filename> <status>" — the "reviewing" label was dropped to free bar width', () => {
    seedAt('2024-Q4-soylent.pdf', [makeDoc('2024-Q4-soylent.pdf', false)])
    render(<ReviewOverlay onBack={() => {}} />)
    const title = document.querySelector('.rev-bar .title') as HTMLElement
    expect(title).toBeTruthy()
    // The bar's horizontal room belongs to the experiment tab strip; the
    // standing "reviewing" label said nothing the mode chrome didn't already.
    expect(title.textContent).not.toContain('reviewing')
    // chip carries the bare filename — no `docs/` prefix
    expect(title.querySelector('.doc')?.textContent).toBe('2024-Q4-soylent.pdf')
    // no prediction + not reviewed → 'new' (the no-prediction state; 'pending'
    // is now reserved for docs that have a prediction awaiting review)
    expect(title.querySelector('.status')?.textContent).toBe('new')
  })

  it('status pill flips to "reviewed" when has_reviewed is true', () => {
    seedAt('done.pdf', [makeDoc('done.pdf', true)])
    render(<ReviewOverlay onBack={() => {}} />)
    const status = document.querySelector('.rev-bar .title .status')
    expect(status?.textContent).toBe('reviewed')
  })

  it('right-arrow key advances to the next doc', () => {
    seedAt('a.pdf', [makeDoc('a.pdf'), makeDoc('b.pdf'), makeDoc('c.pdf')])
    render(<ReviewOverlay onBack={() => {}} />)
    fireEvent.keyDown(window, { key: 'ArrowRight' })
    expect(navSpy).toHaveBeenCalledWith('p_x', 'b.pdf')
  })

  it('left-arrow key steps back', () => {
    seedAt('b.pdf', [makeDoc('a.pdf'), makeDoc('b.pdf')])
    render(<ReviewOverlay onBack={() => {}} />)
    fireEvent.keyDown(window, { key: 'ArrowLeft' })
    expect(navSpy).toHaveBeenCalledWith('p_x', 'a.pdf')
  })

  it('typing in an editable value swallows the arrow keys (no nav)', () => {
    seedAt('a.pdf', [makeDoc('a.pdf'), makeDoc('b.pdf')])
    render(<ReviewOverlay onBack={() => {}} />)
    const val = document.querySelector('[contenteditable="true"]') as HTMLElement
    expect(val).toBeTruthy()
    fireEvent.keyDown(val, { key: 'ArrowRight' })
    expect(navSpy).not.toHaveBeenCalled()
  })

  it('first trash click arms; second click runs delete + jumps to next', async () => {
    seedAt('a.pdf', [makeDoc('a.pdf'), makeDoc('b.pdf')])
    const removeSpy = vi.fn(async () => {})
    useDocs.setState({ remove: removeSpy } as never)
    render(<ReviewOverlay onBack={() => {}} />)
    const trash = screen.getByRole('button', { name: /delete this file/i })
    fireEvent.click(trash)
    expect(screen.getByText(/confirm/i)).toBeInTheDocument()
    expect(removeSpy).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: /again to confirm/i }))
    await waitFor(() => expect(removeSpy).toHaveBeenCalledWith('p_x', 'a.pdf'))
    await waitFor(() => expect(navSpy).toHaveBeenCalledWith('p_x', 'b.pdf'))
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
    const removeSpy = vi.fn(async () => {})
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
