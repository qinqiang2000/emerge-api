// BenchOverlay — modal shell that assembles TopBar + Headline + AxisRail×2
// + Matrix + SelectionBar (+ later BenchDiff placeholder). Mirrors the
// `EvalMatrixModal` URL-driven lifecycle: App.tsx mounts the component when
// `?bench=1` is in the search string and a slug is selected; the overlay
// itself owns its local selection / hover / diff-placeholder state.
//
// Tests in this file cover the modal lifecycle (open, close button, ESC,
// project switch auto-close), the row-click → onOpenRow path that App.tsx
// uses to deep-link to the EvalMatrixModal via `?eval=<summary_ts>`, and the
// 2-row compare → placeholder slot that T7 (BenchDiff) will replace.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'

import BenchOverlay from '../BenchOverlay'
import { useBench } from '../../../stores/bench'
import { useProjects } from '../../../stores/projects'
import type { BenchResponse, BenchRow } from '../../../types/bench'
import * as api from '../../../lib/api'

const SLUG = 'us-invoice'

function mkRow(over: Partial<BenchRow> = {}): BenchRow {
  return {
    id: 'ex_test',
    kind: 'experiment',
    prompt_id: 'pr_a',
    model_id: 'm_x',
    status: 'ran',
    is_active: false,
    score: 0.8,
    delta: null,
    ran_at: '2026-05-25T12:00:00Z',
    summary_ts: '20260525T120000Z',
    cells: {},
    ...over,
  }
}

function mkBench(over: Partial<BenchResponse> = {}): BenchResponse {
  return {
    prompts: [
      { id: 'pr_a', label: 'prompt-a', is_active: true, refs: 2 },
      { id: 'pr_b', label: 'prompt-b', is_active: false, refs: 1 },
    ],
    models: [
      { id: 'm_x', label: 'model-x', provider_model_id: 'mx-1', is_active: true, refs: 2 },
      { id: 'm_y', label: 'model-y', provider_model_id: 'my-1', is_active: false, refs: 1 },
    ],
    fields: ['vendor', 'total'],
    sample_filenames: ['a.pdf', 'b.pdf'],
    headline: { best_score: 0.85, best_prompt_id: 'pr_a', best_model_id: 'm_x' },
    rows: [
      mkRow({ id: 'r1', is_active: true, score: 0.85 }),
      mkRow({ id: 'r2', prompt_id: 'pr_b', score: 0.7, summary_ts: '20260524T120000Z' }),
    ],
    ...over,
  }
}

/** Seed `useBench` with a payload so the overlay can render synchronously
 *  without going through `getBench`. The store's `load()` short-circuits when
 *  the slug is already in `byProject`. */
function seedBench(slug: string, payload: BenchResponse) {
  useBench.setState({ byProject: { [slug]: payload }, loading: {} })
}

describe('BenchOverlay', () => {
  beforeEach(() => {
    useBench.setState({ byProject: {}, loading: {} })
    useProjects.setState({ projects: [], selectedSlug: null, loading: false })
    vi.restoreAllMocks()
    // Guard the fetch path — if anything calls getBench in a test we'd
    // rather see a controlled rejection than a 404 against the dev proxy.
    vi.spyOn(api, 'getBench').mockResolvedValue(mkBench())
  })

  it('renders TopBar + Matrix when bench data is cached for the slug', async () => {
    seedBench(SLUG, mkBench())
    const { container } = render(
      <BenchOverlay slug={SLUG} onClose={() => {}} onOpenRow={() => {}} />,
    )

    await waitFor(() => {
      // TopBar mounted (close button is part of the top strip and uses the
      // bench-specific aria label, so it's unambiguous in this shell).
      expect(screen.getByLabelText(/close bench/i)).toBeInTheDocument()
      // Matrix table renders one .b-row per data row.
      expect(container.querySelectorAll('tr.b-row').length).toBeGreaterThan(0)
    })
  })

  it('clicking the close button fires onClose', async () => {
    seedBench(SLUG, mkBench())
    const onClose = vi.fn()
    render(<BenchOverlay slug={SLUG} onClose={onClose} onOpenRow={() => {}} />)

    await waitFor(() => expect(screen.getByLabelText(/close bench/i)).toBeInTheDocument())
    fireEvent.click(screen.getByLabelText(/close bench/i))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('pressing Escape fires onClose', async () => {
    seedBench(SLUG, mkBench())
    const onClose = vi.fn()
    render(<BenchOverlay slug={SLUG} onClose={onClose} onOpenRow={() => {}} />)

    await waitFor(() => expect(screen.getByLabelText(/close bench/i)).toBeInTheDocument())
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('clicking a row invokes onOpenRow with the BenchRow', async () => {
    const row = mkRow({ id: 'r1', is_active: true, score: 0.85 })
    seedBench(SLUG, mkBench({ rows: [row] }))
    const onOpenRow = vi.fn()
    const { container } = render(
      <BenchOverlay slug={SLUG} onClose={() => {}} onOpenRow={onOpenRow} />,
    )

    await waitFor(() =>
      expect(container.querySelector('tr.b-row')).not.toBeNull(),
    )
    const tr = container.querySelector('tr.b-row') as HTMLTableRowElement
    fireEvent.click(tr)
    expect(onOpenRow).toHaveBeenCalledTimes(1)
    expect(onOpenRow).toHaveBeenCalledWith(expect.objectContaining({ id: 'r1' }))
  })

  it('selecting 2 rows then clicking compare opens the BenchDiff modal', async () => {
    const r1 = mkRow({ id: 'r1' })
    const r2 = mkRow({ id: 'r2', prompt_id: 'pr_b' })
    seedBench(SLUG, mkBench({ rows: [r1, r2] }))

    // Stub the prompt-body fetch BenchOverlay fires when the diff opens
    // with two rows whose prompt_ids differ. We don't assert on the body
    // here — that's BenchDiff's responsibility — we just need the fetch to
    // not blow up jsdom by being unresolvable.
    const fetchSpy = vi.spyOn(window, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ schema: [], global_notes: '' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    const { container } = render(
      <BenchOverlay slug={SLUG} onClose={() => {}} onOpenRow={() => {}} />,
    )

    await waitFor(() =>
      expect(container.querySelectorAll('tr.b-row').length).toBe(2),
    )
    const pickCells = container.querySelectorAll('td.b-row-pick')
    fireEvent.click(pickCells[0]!)
    fireEvent.click(pickCells[1]!)

    // SelectionBar shows up with "compare →" enabled.
    const compareBtn = screen.getByRole('button', { name: /^compare/i })
    expect(compareBtn).not.toBeDisabled()
    fireEvent.click(compareBtn)

    // BenchDiff renders a `role="dialog"` with `aria-label="bench-diff"` —
    // the overlay itself uses `aria-label="bench"`, so we disambiguate
    // by matching on the diff modal's distinctive label.
    expect(
      screen.getByRole('dialog', { name: /bench-diff/i }),
    ).toBeInTheDocument()

    fetchSpy.mockRestore()
  })

  it('project switch (useProjects.selectedSlug changes) fires onClose', async () => {
    seedBench(SLUG, mkBench())
    const onClose = vi.fn()
    // Start on `selectedSlug = SLUG` so the next-mount change is observable.
    useProjects.setState({ selectedSlug: SLUG })
    render(<BenchOverlay slug={SLUG} onClose={onClose} onOpenRow={() => {}} />)

    await waitFor(() => expect(screen.getByLabelText(/close bench/i)).toBeInTheDocument())
    act(() => {
      useProjects.setState({ selectedSlug: 'other-project' })
    })
    expect(onClose).toHaveBeenCalled()
  })

  it('loading state (no cache + load in-flight) renders a skeleton placeholder', async () => {
    // Force the cache miss so load() actually runs; resolve later.
    let resolveFetch: ((v: BenchResponse) => void) | null = null
    const pending = new Promise<BenchResponse>(res => { resolveFetch = res })
    vi.spyOn(api, 'getBench').mockReturnValue(pending)

    render(<BenchOverlay slug={SLUG} onClose={() => {}} onOpenRow={() => {}} />)

    expect(screen.getByTestId('bench-loading')).toBeInTheDocument()
    // Drain the promise so the test doesn't leak an unresolved load.
    await act(async () => {
      resolveFetch!(mkBench())
      await pending
    })
  })

  it('hidden=true keeps the tree mounted but hides the dialog and stands down Esc', async () => {
    seedBench(SLUG, mkBench({
      rows: [mkRow({ id: 'r1', is_active: true, score: 0.85 })],
    }))
    const onClose = vi.fn()
    const { container, rerender } = render(
      <BenchOverlay slug={SLUG} onClose={onClose} onOpenRow={() => {}} />,
    )

    // Initial mount renders normally — backdrop visible, Esc closes.
    await waitFor(() =>
      expect(container.querySelector('tr.b-row')).not.toBeNull(),
    )
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)

    // Layer something on top → hidden=true.
    rerender(
      <BenchOverlay slug={SLUG} onClose={onClose} onOpenRow={() => {}} hidden />,
    )
    const dialog = container.querySelector('[aria-label="bench"]') as HTMLElement
    expect(dialog).not.toBeNull()
    expect(dialog).toHaveAttribute('aria-hidden', 'true')
    expect(dialog.style.display).toBe('none')
    // Tree still mounted: matrix row still in DOM (state preserved).
    expect(container.querySelector('tr.b-row')).not.toBeNull()
    // Esc no longer closes us — the layered overlay owns the keyboard.
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1) // unchanged

    // Reveal again → backdrop click resumes closing.
    rerender(
      <BenchOverlay slug={SLUG} onClose={onClose} onOpenRow={() => {}} />,
    )
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(2)
  })
})
