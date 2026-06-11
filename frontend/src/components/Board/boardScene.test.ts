// boardScene — pure scene math. The excalidraw canvas itself can't render in
// jsdom; these tests pin down the layer the canvas consumes: column layout,
// point→board coordinate conversion (150/72 raster dpi), deterministic ids,
// the spike traps (#1 ids / #2 focus ring / #4 low-alpha fill), arrow pairing
// and the unlocated-badge degradation.
import { describe, expect, it } from 'vitest'

import {
  COL_GAP,
  ELLIPSE_PAD,
  LAYOUT_SCALE,
  OWN_ID_RE,
  PX_PER_PT,
  RING_ID,
  ROW_GAP,
  anchorForBounds,
  annotateUserElements,
  arrowId,
  badgeId,
  buildCheckOverlays,
  buildFocusRing,
  buildPageSkeletons,
  checkIdxOfElementId,
  evId,
  evidenceBounds,
  imgId,
  layoutPages,
  pageKey,
  pullPagesFront,
  pxPerPtFor,
  readBoardColors,
  unionBounds,
  type BoardColors,
  type CheckStatus,
  type EvidenceOnBoard,
} from './boardScene'

const COLORS: BoardColors = {
  pass: '#7c8c4d',
  fail: '#b54a48',
  unclear: '#b8860b',
  chrome: '#6b6258',
  canvas: '#faf8f4',
}

const TWO_DOCS = [
  // pdf doc, 2 pages of 1240×1754 raster px (A4 @150dpi)
  { name: 'a.pdf', ext: 'pdf', pages: [
    { page: 1, w: 1240, h: 1754 },
    { page: 2, w: 1240, h: 1754 },
  ]},
  // raster doc, single jpg page
  { name: 'b.jpg', ext: 'jpg', pages: [{ page: 1, w: 1000, h: 800 }] },
]

describe('unit conversion', () => {
  it('PX_PER_PT is the 150dpi raster factor (textlayer.py _RENDER_DPI)', () => {
    expect(PX_PER_PT).toBeCloseTo(150 / 72)
  })

  it('pxPerPtFor: pdf → 150/72; raster docs (page units == px) → 1', () => {
    expect(pxPerPtFor('pdf')).toBeCloseTo(150 / 72)
    expect(pxPerPtFor('PDF')).toBeCloseTo(150 / 72)
    expect(pxPerPtFor('.pdf')).toBeCloseTo(150 / 72)
    expect(pxPerPtFor('jpg')).toBe(1)
    expect(pxPerPtFor('png')).toBe(1)
  })
})

describe('layoutPages', () => {
  it('one column per doc, pages stacked with ROW_GAP, x advanced by widest page + COL_GAP', () => {
    const laid = layoutPages(TWO_DOCS)
    const a1 = laid.get(pageKey('a.pdf', 1))!
    const a2 = laid.get(pageKey('a.pdf', 2))!
    const b1 = laid.get(pageKey('b.jpg', 1))!

    expect(a1.x).toBe(0)
    expect(a1.y).toBe(0)
    expect(a1.w).toBeCloseTo(1240 * LAYOUT_SCALE)
    expect(a1.h).toBeCloseTo(1754 * LAYOUT_SCALE)
    // second page stacks below the first
    expect(a2.x).toBe(0)
    expect(a2.y).toBeCloseTo(1754 * LAYOUT_SCALE + ROW_GAP)
    // next doc's column starts after the widest page of column 1
    expect(b1.x).toBeCloseTo(1240 * LAYOUT_SCALE + COL_GAP)
    expect(b1.y).toBe(0)
  })

  it('k folds the per-doc unit factor into the layout scale', () => {
    const laid = layoutPages(TWO_DOCS)
    expect(laid.get(pageKey('a.pdf', 1))!.k).toBeCloseTo((150 / 72) * LAYOUT_SCALE)
    expect(laid.get(pageKey('b.jpg', 1))!.k).toBeCloseTo(1 * LAYOUT_SCALE)
  })
})

describe('evidenceBounds (rect × 150/72 × scale + page offset)', () => {
  it('maps a PDF-point rect onto the laid-out page', () => {
    const laid = layoutPages(TWO_DOCS)
    const page = laid.get(pageKey('a.pdf', 2))!
    const k = (150 / 72) * LAYOUT_SCALE
    const b = evidenceBounds([[72, 36, 144, 72]], page)!
    expect(b.x).toBeCloseTo(page.x + 72 * k - ELLIPSE_PAD)
    expect(b.y).toBeCloseTo(page.y + 36 * k - ELLIPSE_PAD)
    expect(b.w).toBeCloseTo((144 - 72) * k + ELLIPSE_PAD * 2)
    expect(b.h).toBeCloseTo((72 - 36) * k + ELLIPSE_PAD * 2)
  })

  it('unions multi-line rects into one box', () => {
    const laid = layoutPages(TWO_DOCS)
    const page = laid.get(pageKey('b.jpg', 1))! // raster: k = 1 × scale
    const b = evidenceBounds([[10, 10, 110, 20], [10, 24, 60, 34]], page)!
    const k = page.k
    expect(b.x).toBeCloseTo(page.x + 10 * k - ELLIPSE_PAD)
    expect(b.y).toBeCloseTo(page.y + 10 * k - ELLIPSE_PAD)
    expect(b.w).toBeCloseTo(100 * k + ELLIPSE_PAD * 2)
    expect(b.h).toBeCloseTo(24 * k + ELLIPSE_PAD * 2)
  })

  it('returns null for empty / malformed rect lists', () => {
    const laid = layoutPages(TWO_DOCS)
    const page = laid.get(pageKey('a.pdf', 1))!
    expect(evidenceBounds([], page)).toBeNull()
    expect(evidenceBounds([[1, 2]], page)).toBeNull()
  })
})

describe('buildPageSkeletons', () => {
  it('locked image elements with fileId == element id, plus captions', () => {
    const laid = layoutPages(TWO_DOCS)
    const sk = buildPageSkeletons([...laid.values()], COLORS)
    const img = sk.find(s => s.id === imgId('a.pdf', 2))!
    expect(img.type).toBe('image')
    expect(img.fileId).toBe('img-a.pdf-p2')
    expect(img.locked).toBe(true)
    const lbl = sk.find(s => s.id === 'lbl-a.pdf-p2')!
    expect(lbl.type).toBe('text')
    expect(lbl.strokeColor).toBe(COLORS.chrome)
  })
})

function mkEvidence(over: Partial<EvidenceOnBoard>): EvidenceOnBoard {
  return {
    checkIdx: 0, evIdx: 0, doc: 'a.pdf', page: 1,
    rects: [[10, 10, 60, 20]], status: 'exact',
    ...over,
  }
}

describe('pullPagesFront', () => {
  const doc = { name: 'm.pdf', ext: 'pdf', pages: [1, 2, 3, 4, 5].map(n => ({ page: n, w: 100, h: 100 })) }

  it('cited pages bubble to the front, rest keep order', () => {
    const out = pullPagesFront(doc, [4, 2])
    expect(out.pages.map(p => p.page)).toEqual([2, 4, 1, 3, 5])
  })

  it('no cited / unknown pages -> unchanged', () => {
    expect(pullPagesFront(doc, []).pages.map(p => p.page)).toEqual([1, 2, 3, 4, 5])
    expect(pullPagesFront(doc, [99]).pages.map(p => p.page)).toEqual([1, 2, 3, 4, 5])
  })
})

describe('buildCheckOverlays', () => {
  const checks: { status: CheckStatus }[] = [
    { status: 'pass' }, { status: 'fail' }, { status: 'unclear' },
  ]

  it('located evidence → dashed unfilled ellipse with deterministic id', () => {
    const laid = layoutPages(TWO_DOCS)
    const sk = buildCheckOverlays(checks, [mkEvidence({ checkIdx: 1, evIdx: 2 })], laid, COLORS)
    expect(sk).toHaveLength(1)
    const el = sk[0]
    expect(el.id).toBe(evId(1, 2))
    expect(el.id).toBe('ev-1-2')
    expect(el.type).toBe('ellipse')
    // dashed outline, NO fill — fill covered the text (dogfood 2026-06-11);
    // overlays render for the active check only so the interior needn't be a
    // click target (former trap #4 concern).
    expect(el.strokeStyle).toBe('dashed')
    expect(el.backgroundColor).toBe('transparent')
    expect(el.strokeColor).toBe(COLORS.fail)
  })

  it('status colors: pass=moss fail=rose unclear=ochre (token hexes)', () => {
    const laid = layoutPages(TWO_DOCS)
    const sk = buildCheckOverlays(checks, [
      mkEvidence({ checkIdx: 0, evIdx: 0 }),
      mkEvidence({ checkIdx: 2, evIdx: 0 }),
    ], laid, COLORS)
    expect(sk.find(s => s.id === 'ev-0-0')!.strokeColor).toBe(COLORS.pass)
    expect(sk.find(s => s.id === 'ev-2-0')!.strokeColor).toBe(COLORS.unclear)
  })

  it('check spanning two docs → dashed arrow bound to both ellipses + ✓/✗ label', () => {
    const laid = layoutPages(TWO_DOCS)
    const sk = buildCheckOverlays(checks, [
      mkEvidence({ checkIdx: 1, evIdx: 0, doc: 'a.pdf' }),
      mkEvidence({ checkIdx: 1, evIdx: 1, doc: 'b.jpg' }),
    ], laid, COLORS)
    const arrow = sk.find(s => s.id === arrowId(1))!
    expect(arrow).toBeDefined()
    expect(arrow.type).toBe('arrow')
    expect(arrow.strokeStyle).toBe('dashed')
    // edge-to-edge shaft (no skeleton bindings — they don't retrim
    // programmatic scenes; geometry is computed in buildCheckOverlays)
    expect(arrow.start).toBeUndefined()
    expect(arrow.end).toBeUndefined()
    const pts = arrow.points as number[][]
    const dx = (pts[1]?.[0] ?? 0) - pts[0][0]
    // shaft is strictly shorter than center-to-center: trimmed at both rims
    const aPage = laid.get(pageKey('a.pdf', 1))!
    const bPage = laid.get(pageKey('b.jpg', 1))!
    expect(Math.abs(dx)).toBeLessThan(Math.abs(bPage.x - aPage.x) + Math.max(bPage.w, aPage.w))
    expect(Math.abs(dx)).toBeGreaterThan(0)
    expect((arrow.label as { text: string }).text).toBe('✗')
  })

  it('many-match check → one arrow per consecutive cross-doc pair, no labels', () => {
    const laid = layoutPages(TWO_DOCS)
    // alternating a,b,a,b with distinct rects = 2 pairs (stride-2: no double link)
    const sk = buildCheckOverlays(checks, [
      mkEvidence({ checkIdx: 0, evIdx: 0, doc: 'a.pdf', rects: [[10, 10, 60, 20]] }),
      mkEvidence({ checkIdx: 0, evIdx: 1, doc: 'b.jpg', rects: [[10, 10, 60, 20]] }),
      mkEvidence({ checkIdx: 0, evIdx: 2, doc: 'a.pdf', rects: [[10, 100, 60, 110]] }),
      mkEvidence({ checkIdx: 0, evIdx: 3, doc: 'b.jpg', rects: [[10, 100, 60, 110]] }),
    ], laid, COLORS)
    const arrows = sk.filter(s2 => String(s2.id).startsWith('arrow-'))
    expect(arrows.map(a => a.id)).toEqual([arrowId(0), `${arrowId(0)}-1`])
    for (const a of arrows) expect(a.label).toBeUndefined()
    // both ids still parse back to the check
    expect(checkIdxOfElementId(`${arrowId(0)}-1`)).toBe(0)
  })

  it('pass check arrow gets the ✓ label', () => {
    const laid = layoutPages(TWO_DOCS)
    const sk = buildCheckOverlays(checks, [
      mkEvidence({ checkIdx: 0, evIdx: 0, doc: 'a.pdf' }),
      mkEvidence({ checkIdx: 0, evIdx: 1, doc: 'b.jpg' }),
    ], laid, COLORS)
    const arrow = sk.find(s => s.id === 'arrow-0')!
    expect((arrow.label as { text: string }).text).toBe('✓')
  })

  it('two located evidences in the SAME doc → no arrow', () => {
    const laid = layoutPages(TWO_DOCS)
    const sk = buildCheckOverlays(checks, [
      mkEvidence({ checkIdx: 0, evIdx: 0, page: 1 }),
      mkEvidence({ checkIdx: 0, evIdx: 1, page: 2 }),
    ], laid, COLORS)
    expect(sk.filter(s => s.type === 'arrow')).toHaveLength(0)
    expect(sk.filter(s => s.type === 'ellipse')).toHaveLength(2)
  })

  it('unlocated evidence → per-doc corner badge with 1-based check numbers, no ellipse', () => {
    const laid = layoutPages(TWO_DOCS)
    const sk = buildCheckOverlays(checks, [
      mkEvidence({ checkIdx: 0, evIdx: 0, status: 'none', rects: [] }),
      mkEvidence({ checkIdx: 2, evIdx: 0, status: 'none', rects: [] }),
      // same check twice on one doc → deduped in the badge
      mkEvidence({ checkIdx: 2, evIdx: 1, status: 'none', rects: [] }),
    ], laid, COLORS)
    expect(sk.filter(s => s.type === 'ellipse')).toHaveLength(0)
    const badge = sk.find(s => s.id === badgeId('a.pdf'))!
    expect(badge.type).toBe('text')
    expect(badge.text).toBe('#1 #3')
    expect(badge.strokeColor).toBe(COLORS.unclear)
  })

  it('located rects whose page is not laid out degrade to the badge', () => {
    const laid = layoutPages(TWO_DOCS)
    const sk = buildCheckOverlays(checks, [
      mkEvidence({ checkIdx: 1, evIdx: 0, page: 9 }), // a.pdf has 2 pages
    ], laid, COLORS)
    expect(sk.filter(s => s.type === 'ellipse')).toHaveLength(0)
    expect(sk.find(s => s.id === 'badge-a.pdf')).toBeDefined()
  })

  it('evidence for a doc that is not on the board at all is silently skipped', () => {
    const laid = layoutPages(TWO_DOCS)
    const sk = buildCheckOverlays(checks, [
      mkEvidence({ doc: 'ghost.pdf', status: 'none', rects: [] }),
    ], laid, COLORS)
    expect(sk).toHaveLength(0)
  })
})

describe('buildFocusRing (trap #2 — focus without selection)', () => {
  it('thicker-stroke, transparent, locked ellipse around the target', () => {
    const ring = buildFocusRing({ x: 100, y: 50, w: 80, h: 30 }, '#b8860b')
    expect(ring.id).toBe(RING_ID)
    expect(ring.type).toBe('ellipse')
    expect(ring.strokeWidth).toBe(4) // thicker than the evidence ellipses' 2
    expect(ring.backgroundColor).toBe('transparent')
    expect(ring.locked).toBe(true)
    // encloses the target
    expect(ring.x as number).toBeLessThan(100)
    expect(ring.y as number).toBeLessThan(50)
    expect(ring.width as number).toBeGreaterThan(80)
    expect(ring.height as number).toBeGreaterThan(30)
  })
})

describe('id namespace contract', () => {
  it('OWN_ID_RE claims every board-drawn namespace and nothing else', () => {
    for (const id of ['img-a.pdf-p1', 'lbl-a.pdf-p1', 'ev-0-1', 'arrow-3', 'badge-a.pdf', 'ring-focus']) {
      expect(OWN_ID_RE.test(id)).toBe(true)
    }
    for (const id of ['abc123', 'freedraw-xyz', 'ring-focus-2', 'eventually']) {
      expect(OWN_ID_RE.test(id)).toBe(false)
    }
  })

  it('checkIdxOfElementId parses ev-*/arrow-* and rejects everything else', () => {
    expect(checkIdxOfElementId('ev-4-1')).toBe(4)
    expect(checkIdxOfElementId('arrow-12')).toBe(12)
    expect(checkIdxOfElementId('img-a.pdf-p1')).toBeNull()
    expect(checkIdxOfElementId('ring-focus')).toBeNull()
    expect(checkIdxOfElementId('user-scribble')).toBeNull()
  })
})

describe('unionBounds', () => {
  it('unions boxes; null on empty', () => {
    expect(unionBounds([])).toBeNull()
    expect(unionBounds([
      { x: 0, y: 0, w: 10, h: 10 },
      { x: 5, y: 20, w: 10, h: 5 },
    ])).toEqual({ x: 0, y: 0, w: 15, h: 25 })
  })
})

describe('anchorForBounds (board bounds → doc/page/source rect)', () => {
  it('inverts evidenceBounds on a PDF page (k = 150/72 × scale)', () => {
    const laid = layoutPages(TWO_DOCS)
    const page = laid.get(pageKey('a.pdf', 1))!
    const k = (150 / 72) * LAYOUT_SCALE
    // board bounds drawn exactly over source rect [72, 36, 144, 72] (points)
    const bounds = { x: page.x + 72 * k, y: page.y + 36 * k, w: 72 * k, h: 36 * k }
    const a = anchorForBounds(bounds, laid)!
    expect(a.doc).toBe('a.pdf')
    expect(a.page).toBe(1)
    expect(a.rect[0]).toBeCloseTo(72)
    expect(a.rect[1]).toBeCloseTo(36)
    expect(a.rect[2]).toBeCloseTo(144)
    expect(a.rect[3]).toBeCloseTo(72)
  })

  it('multi-page / multi-doc: the page containing the CENTER wins', () => {
    const laid = layoutPages(TWO_DOCS)
    const a2 = laid.get(pageKey('a.pdf', 2))!
    const b1 = laid.get(pageKey('b.jpg', 1))!
    // doodle centered on a.pdf p2
    const onA2 = anchorForBounds({ x: a2.x + 10, y: a2.y + 10, w: 40, h: 20 }, laid)!
    expect(onA2.doc).toBe('a.pdf')
    expect(onA2.page).toBe(2)
    // doodle centered on the raster doc — k = 1 × scale, source units = px
    const onB1 = anchorForBounds({ x: b1.x + 100 * b1.k, y: b1.y + 50 * b1.k, w: 20 * b1.k, h: 10 * b1.k }, laid)!
    expect(onB1.doc).toBe('b.jpg')
    expect(onB1.page).toBe(1)
    expect(onB1.rect[0]).toBeCloseTo(100)
    expect(onB1.rect[1]).toBeCloseTo(50)
    expect(onB1.rect[2]).toBeCloseTo(120)
    expect(onB1.rect[3]).toBeCloseTo(60)
  })

  it('center in empty board space (the COL_GAP / above the pages) → null', () => {
    const laid = layoutPages(TWO_DOCS)
    const a1 = laid.get(pageKey('a.pdf', 1))!
    const b1 = laid.get(pageKey('b.jpg', 1))!
    // squarely inside the doc-to-doc gap
    const gapX = a1.x + a1.w + (b1.x - (a1.x + a1.w)) / 2
    expect(anchorForBounds({ x: gapX - 5, y: 100, w: 10, h: 10 }, laid)).toBeNull()
    // above the board
    expect(anchorForBounds({ x: a1.x + 10, y: a1.y - 60, w: 10, h: 10 }, laid)).toBeNull()
  })

  it('bounds spilling past the page edge are clamped to the page frame', () => {
    const laid = layoutPages(TWO_DOCS)
    const b1 = laid.get(pageKey('b.jpg', 1))! // 1000×800 px source
    // starts left of / above the page, ends past its right edge, but the
    // center still falls on the page
    const a = anchorForBounds(
      { x: b1.x - 20, y: b1.y - 20, w: b1.w + 60, h: b1.h / 2 },
      laid,
    )!
    expect(a.doc).toBe('b.jpg')
    expect(a.rect[0]).toBe(0)
    expect(a.rect[1]).toBe(0)
    expect(a.rect[2]).toBeCloseTo(1000) // clamped to source width
    expect(a.rect[3]).toBeLessThanOrEqual(800)
  })
})

describe('annotateUserElements (D1: user notes → anchor sidecar)', () => {
  it('maps element types to kinds: text → text (with text), freedraw → draw, shapes → shape', () => {
    const laid = layoutPages(TWO_DOCS)
    const a1 = laid.get(pageKey('a.pdf', 1))!
    const on = (dx: number) => ({ x: a1.x + dx, y: a1.y + 100, width: 40, height: 20 })
    const out = annotateUserElements([
      { id: 't1', type: 'text', text: '缺章，周一补', ...on(10) },
      { id: 'd1', type: 'freedraw', ...on(60) },
      { id: 's1', type: 'ellipse', ...on(110) },
      { id: 's2', type: 'arrow', ...on(160) },
    ], laid)
    expect(out.map(a => a.kind)).toEqual(['text', 'draw', 'shape', 'shape'])
    expect(out[0].text).toBe('缺章，周一补')
    // non-text kinds never carry a text field
    expect('text' in out[1]).toBe(false)
    expect('text' in out[2]).toBe(false)
    expect(out.every(a => a.doc === 'a.pdf' && a.page === 1)).toBe(true)
  })

  it('converts a PDF-page doodle to SOURCE units (inverse of k = 150/72 × scale)', () => {
    const laid = layoutPages(TWO_DOCS)
    const page = laid.get(pageKey('a.pdf', 2))!
    const k = (150 / 72) * LAYOUT_SCALE
    const [a] = annotateUserElements([{
      id: 'e1', type: 'rectangle',
      x: page.x + 72 * k, y: page.y + 36 * k, width: 72 * k, height: 36 * k,
    }], laid)
    expect(a).toMatchObject({ id: 'e1', kind: 'shape', doc: 'a.pdf', page: 2 })
    expect(a.rect![0]).toBeCloseTo(72)
    expect(a.rect![1]).toBeCloseTo(36)
    expect(a.rect![2]).toBeCloseTo(144)
    expect(a.rect![3]).toBeCloseTo(72)
  })

  it('a zero-size (point) element still anchors via its center', () => {
    const laid = layoutPages(TWO_DOCS)
    const b1 = laid.get(pageKey('b.jpg', 1))!
    const [a] = annotateUserElements([{
      id: 'p1', type: 'freedraw',
      x: b1.x + 100 * b1.k, y: b1.y + 50 * b1.k, width: 0, height: 0,
    }], laid)
    expect(a).toMatchObject({ kind: 'draw', doc: 'b.jpg', page: 1 })
    expect(a.rect![0]).toBeCloseTo(100)
    expect(a.rect![1]).toBeCloseTo(50)
  })

  it('a doodle in empty board space keeps a null anchor (the note still persists)', () => {
    const laid = layoutPages(TWO_DOCS)
    const a1 = laid.get(pageKey('a.pdf', 1))!
    const [a] = annotateUserElements([{
      id: 'e1', type: 'text', text: '整体先放行', x: a1.x + 10, y: a1.y - 80, width: 10, height: 10,
    }], laid)
    expect(a).toEqual({ id: 'e1', kind: 'text', doc: null, page: null, rect: null, text: '整体先放行' })
  })

  it('empty input → empty output', () => {
    expect(annotateUserElements([], layoutPages(TWO_DOCS))).toEqual([])
  })
})

describe('readBoardColors', () => {
  it('evidence marks are fixed vivid inks, independent of theme tokens', () => {
    // Canvas annotations must stand out against arbitrary document pixels —
    // muted chrome tokens read as 不够醒目 in dogfood (2026-06-11). Status
    // colors are therefore constants; only chrome/canvas stay token-driven.
    document.documentElement.style.setProperty('--moss', '#5C6B3A')
    try {
      const c = readBoardColors()
      // one magenta marker for pass AND fail (verdict lives on the rail);
      // amber = "couldn't read", a different signal
      expect(c.pass).toBe('#d6219c')
      expect(c.fail).toBe('#d6219c')
      expect(c.unclear).toBe('#d97706')
    } finally {
      document.documentElement.style.removeProperty('--moss')
    }
  })
})
