// Doc switch (← / → through the review queue) must never leave the two panes
// telling different stories.
//
// The bug this guards: the page <img> was keyed by page number only, so
// stepping to the next doc reused the same DOM node and swapped `src`. The
// browser keeps painting the OLD bytes until the new ones decode — seconds,
// because `/pages/1` renders server-side on first ask — while the right pane
// had already swapped to the NEW doc's fields. The reviewer sees one document's
// values beside another document's page, with nothing on screen saying so.
import { fireEvent, render, screen } from '@testing-library/react'
import { act } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import PdfViewer from '../../../src/components/ReviewMode/PdfViewer'
import ReviewOverlay from '../../../src/components/ReviewMode/ReviewOverlay'
import { prefetchPage, resetPagePrefetch } from '../../../src/lib/rasterPrefetch'
import { useDocs } from '../../../src/stores/docs'
import { useExperiments } from '../../../src/stores/experiments'
import { useModels } from '../../../src/stores/models'
import { useReview } from '../../../src/stores/review'
import { useReviewTune } from '../../../src/stores/reviewTune'
import { useSchema } from '../../../src/stores/schema'
import { useTextlayer } from '../../../src/stores/textlayer'
import { useTranslate } from '../../../src/stores/translate'
import type { DocSummary } from '../../../src/types/review'

vi.mock('../../../src/lib/rasterPrefetch', async (orig) => {
  const real = await orig<typeof import('../../../src/lib/rasterPrefetch')>()
  return { ...real, prefetchPage: vi.fn(real.prefetchPage) }
})

vi.mock('../../../src/components/ReviewMode/FieldEditor', () => ({
  default: () => <div data-testid="field-editor" />,
}))
vi.mock('../../../src/components/ReviewMode/ReviewChatColumn', () => ({
  default: () => <div data-testid="review-chat" />,
  readRevChatWidth: () => 360,
  writeRevChatWidth: () => {},
}))

const PID = 'p_x'

function makeDoc(filename: string): DocSummary {
  return {
    filename,
    ext: 'pdf',
    page_count: 1,
    sha256: filename,
    uploaded_at: '2026-08-11',
    original_name: filename,
    has_prediction: false,
    has_reviewed: false,
  }
}

const DOCS = [makeDoc('a.pdf'), makeDoc('b.pdf'), makeDoc('c.pdf')]

function seedAt(active: string) {
  useSchema.setState({ byProject: { [PID]: [] as never } })
  useDocs.setState({ byProject: { [PID]: DOCS } })
  useExperiments.setState({ list: { [PID]: [] }, loading: {} })
  useModels.setState({ list: { [PID]: [] }, activeByProject: {}, loading: {} })
  useReviewTune.setState({ signal: null, dismissedKey: null })
  useTextlayer.setState({ byKey: {} })
  useTranslate.setState({ byKey: {} })
  useReview.setState({
    activeProjectId: PID, activeFilename: active,
    entities: [{}], evidence: null, notes: {},
    activeTabKey: 'active', predictionsByExp: {},
    loading: false, firstPageState: 'loading',
    saving: false, err: null, page: 1, pageCount: 1,
  })
}

beforeEach(() => {
  // Shaped like a textlayer payload rather than `[]`: PageOverlays mounts
  // under the skeleton (deliberately — its fetch runs in parallel with the
  // raster), so a shapeless `ready` entry would blow up on `payload.spans`.
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({ spans: [], page_w: 612, page_h: 792 }),
    text: async () => '',
  }))
  vi.mocked(prefetchPage).mockClear()
  resetPagePrefetch()
  seedAt('a.pdf')
})

describe('left pane doc-switch loading', () => {
  it('drops the previous doc\'s raster and re-enters loading on switch', () => {
    const { container } = render(<PdfViewer />)

    // Doc A's page lands.
    fireEvent.load(container.querySelector('.dv-pagewrap img')!)
    expect(container.querySelector('.dv-pageskel')).toBeNull()
    expect(useReview.getState().firstPageState).toBe('ready')

    // → next doc. Nothing has loaded for b.pdf, so the pane must say so
    // rather than keep a.pdf's pixels on screen.
    act(() => { useReview.getState().open(PID, 'b.pdf') })
    expect(container.querySelector('.dv-pageskel')).not.toBeNull()
    expect(useReview.getState().firstPageState).toBe('loading')
    expect(container.querySelector('.dv-pagewrap img')!.getAttribute('src'))
      .toContain('b.pdf')
  })

  it('a failed raster stops claiming to be on its way', () => {
    const { container } = render(<PdfViewer />)
    fireEvent.error(container.querySelector('.dv-pagewrap img')!)
    expect(container.querySelector('.dv-pageskel .pane-loading.is-error')).not.toBeNull()
    expect(useReview.getState().firstPageState).toBe('error')
  })

  it('ignores a late load report from the doc the reviewer already left', () => {
    useReview.getState().setFirstPageState('a.pdf', 'ready')
    expect(useReview.getState().firstPageState).toBe('ready')
    useReview.setState({ activeFilename: 'b.pdf', firstPageState: 'loading' })
    // a.pdf's raster finally decodes, after the switch.
    useReview.getState().setFirstPageState('a.pdf', 'ready')
    expect(useReview.getState().firstPageState).toBe('loading')
  })
})

describe('doc-level progress + look-ahead', () => {
  it('runs the bar progress line while either pane is still fetching', () => {
    const { container, rerender } = render(<ReviewOverlay onBack={() => {}} />)
    // Fields are in, first page isn't → still loading as a document.
    expect(container.querySelector('.rev-bar-progress')).not.toBeNull()

    act(() => { useReview.setState({ firstPageState: 'ready' }) })
    rerender(<ReviewOverlay onBack={() => {}} />)
    expect(container.querySelector('.rev-bar-progress')).toBeNull()
  })

  it('warms the neighbours\' page-1 rasters once the current doc is on screen', () => {
    useReview.setState({ activeFilename: 'b.pdf' })
    const { rerender } = render(<ReviewOverlay onBack={() => {}} />)
    // Current doc still painting — the warmer must not compete with it.
    expect(prefetchPage).not.toHaveBeenCalled()

    act(() => { useReview.setState({ firstPageState: 'ready' }) })
    rerender(<ReviewOverlay onBack={() => {}} />)
    expect(prefetchPage).toHaveBeenCalledWith(PID, 'c.pdf', 1)
    expect(prefetchPage).toHaveBeenCalledWith(PID, 'a.pdf', 1)
  })
})

describe('both panes speak the same loading language', () => {
  it('gives the right pane the same chip the left skeleton uses', () => {
    useReview.setState({ loading: true })
    const { container } = render(<ReviewOverlay onBack={() => {}} />)
    expect(container.querySelector('.rev-pane-loading .pane-loading')).not.toBeNull()
    expect(screen.queryByTestId('field-editor')).toBeNull()
  })
})
