/**
 * SPIKE — audit board on excalidraw (2026-06-11-audit-board-seed.md Spike A).
 *
 * Dev-only page, mounted pre-auth via `?boardspike=1`. Verifies, with static
 * page images (frontend/public/_boardspike/, rendered from audit_demo):
 *   1. excalidraw 0.18 mounts under React 19 + Vite,
 *   2. multi-doc page images laid out on one board (locked, pan/zoom free),
 *   3. bbox→ellipse overlay alignment math (same (x/pageW) mapping as BBoxRect),
 *   4. rule list ↔ board two-way click linkage (select + scrollToContent),
 *   5. cross-doc evidence arrows with labels.
 *
 * NOT product code — the real board ships per the audit-board plan.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Excalidraw, convertToExcalidrawElements } from '@excalidraw/excalidraw'
import '@excalidraw/excalidraw/index.css'

type Rect = [number, number, number, number] // normalized x0,y0,x1,y1 (0..1 of page)

interface SpikeEvidence {
  page: string // page image basename
  rect: Rect
}

interface SpikeRule {
  id: string
  text: string
  status: 'pass' | 'fail'
  evidence: SpikeEvidence[]
}

const SCALE = 0.55
const COL_GAP = 120
const ROW_GAP = 24

const DOCS: { role: string; pages: string[] }[] = [
  { role: '报价单', pages: ['报价单_p1.png'] },
  { role: '收货单', pages: ['收货单_p1.png', '收货单_p2.png', '收货单_p3.png'] },
  { role: '订单', pages: ['订单_p1.png'] },
]

const RULES: SpikeRule[] = [
  {
    id: 'r1',
    text: '报价单甲方为「环胜电子商务（上海）有限公司」',
    status: 'pass',
    evidence: [{ page: '报价单_p1.png', rect: [0.06, 0.13, 0.46, 0.18] }],
  },
  {
    id: 'r3',
    text: '报价单「费用总计」== 收货单「折扣后收货含税总金额」',
    status: 'pass',
    evidence: [
      { page: '报价单_p1.png', rect: [0.55, 0.76, 0.95, 0.82] },
      { page: '收货单_p1.png', rect: [0.5, 0.6, 0.95, 0.66] },
    ],
  },
  {
    id: 'r5',
    text: '报价单项目周期 ∈ 订单服务完成日期区间',
    status: 'fail',
    evidence: [
      { page: '报价单_p1.png', rect: [0.06, 0.21, 0.5, 0.26] },
      { page: '订单_p1.png', rect: [0.08, 0.5, 0.6, 0.56] },
    ],
  },
]

interface LoadedPage {
  name: string
  dataURL: string
  w: number
  h: number
  x: number
  y: number
}

async function loadPages(): Promise<Map<string, LoadedPage>> {
  const out = new Map<string, LoadedPage>()
  let x = 0
  for (const doc of DOCS) {
    let y = 0
    let colW = 0
    for (const name of doc.pages) {
      const blob = await (await fetch(`/_boardspike/${name}`)).blob()
      const dataURL = await new Promise<string>((res) => {
        const r = new FileReader()
        r.onload = () => res(r.result as string)
        r.readAsDataURL(blob)
      })
      const dims = await new Promise<{ w: number; h: number }>((res) => {
        const img = new Image()
        img.onload = () => res({ w: img.naturalWidth, h: img.naturalHeight })
        img.src = dataURL
      })
      const w = dims.w * SCALE
      const h = dims.h * SCALE
      out.set(name, { name, dataURL, w, h, x, y })
      y += h + ROW_GAP
      colW = Math.max(colW, w)
    }
    x += colW + COL_GAP
  }
  return out
}

const ellipseId = (ruleId: string, i: number) => `ev-${ruleId}-${i}`

function buildSkeletons(pages: Map<string, LoadedPage>) {
  const skeletons: Record<string, unknown>[] = []
  for (const p of pages.values()) {
    skeletons.push({
      type: 'image',
      id: `img-${p.name}`,
      fileId: p.name,
      x: p.x,
      y: p.y,
      width: p.w,
      height: p.h,
      locked: true,
    })
    skeletons.push({
      type: 'text',
      id: `lbl-${p.name}`,
      x: p.x,
      y: p.y - 40,
      text: p.name.replace('.png', ''),
      fontSize: 20,
      strokeColor: '#6b6258',
      locked: true,
    })
  }
  for (const rule of RULES) {
    const color = rule.status === 'pass' ? '#7c8c4d' : '#b54a48'
    const pads = 8
    const centers: { cx: number; cy: number; id: string }[] = []
    rule.evidence.forEach((ev, i) => {
      const p = pages.get(ev.page)
      if (!p) return
      const [rx0, ry0, rx1, ry1] = ev.rect
      const ex = p.x + rx0 * p.w - pads
      const ey = p.y + ry0 * p.h - pads
      const ew = (rx1 - rx0) * p.w + pads * 2
      const eh = (ry1 - ry0) * p.h + pads * 2
      skeletons.push({
        type: 'ellipse',
        id: ellipseId(rule.id, i),
        x: ex,
        y: ey,
        width: ew,
        height: eh,
        strokeColor: color,
        strokeWidth: 2,
        // low-alpha fill: visible highlight zone + clickable interior
        backgroundColor: rule.status === 'pass' ? '#7c8c4d' : '#b54a48',
        fillStyle: 'solid',
        opacity: 40,
      })
      centers.push({ cx: ex + ew / 2, cy: ey + eh / 2, id: ellipseId(rule.id, i) })
    })
    if (centers.length === 2) {
      const [a, b] = centers
      skeletons.push({
        type: 'arrow',
        id: `arrow-${rule.id}`,
        x: a.cx,
        y: a.cy,
        width: b.cx - a.cx,
        height: b.cy - a.cy,
        points: [
          [0, 0],
          [b.cx - a.cx, b.cy - a.cy],
        ],
        start: { id: a.id },
        end: { id: b.id },
        strokeColor: color,
        strokeStyle: 'dashed',
        label: { text: rule.status === 'pass' ? '✓' : '✗', fontSize: 16 },
      })
    }
  }
  return skeletons
}

export default function BoardSpike() {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const apiRef = useRef<any>(null)
  const [activeRule, setActiveRule] = useState<string | null>(null)
  const [ready, setReady] = useState(false)
  const pagesRef = useRef<Map<string, LoadedPage> | null>(null)

  const onApi = useCallback((api: unknown) => {
    apiRef.current = api
    // test hook for the spike's Playwright verification only
    ;(window as unknown as Record<string, unknown>).__boardSpikeApi = api
  }, [])

  useEffect(() => {
    let cancelled = false
    const t = setInterval(async () => {
      const api = apiRef.current
      if (!api || pagesRef.current) return
      clearInterval(t)
      const pages = await loadPages()
      if (cancelled) return
      pagesRef.current = pages
      api.addFiles(
        [...pages.values()].map((p) => ({
          id: p.name,
          dataURL: p.dataURL,
          mimeType: 'image/png',
          created: Date.now(),
        })),
      )
      // regenerateIds:false — our rule↔ellipse linkage is keyed by element id
      api.updateScene({
        elements: convertToExcalidrawElements(buildSkeletons(pages) as never, {
          regenerateIds: false,
        }),
      })
      setTimeout(() => {
        api.scrollToContent(undefined, { fitToViewport: true })
        setReady(true)
      }, 100)
    }, 50)
    return () => {
      cancelled = true
      clearInterval(t)
    }
  }, [])

  const focusRule = (rule: SpikeRule) => {
    setActiveRule(rule.id)
    const api = apiRef.current
    if (!api) return
    const ids = rule.evidence.map((_, i) => ellipseId(rule.id, i))
    if (`arrow-${rule.id}`) ids.push(`arrow-${rule.id}`)
    const els = api.getSceneElements().filter((e: { id: string }) => ids.includes(e.id))
    if (!els.length) return
    api.scrollToContent(els, { fitToViewport: true, animate: true, viewportZoomFactor: 0.6 })
    api.updateScene({
      appState: { selectedElementIds: Object.fromEntries(ids.map((i) => [i, true])) },
    })
  }

  // board → list reverse linkage: selecting an evidence ellipse highlights its rule
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const onChange = (_els: unknown, appState: any) => {
    const sel = Object.keys(appState?.selectedElementIds ?? {})
    const hit = sel.find((id) => id.startsWith('ev-') || id.startsWith('arrow-'))
    if (hit) {
      const rid = hit.replace(/^(ev|arrow)-/, '').replace(/-\d+$/, '')
      if (rid !== activeRule) setActiveRule(rid)
    }
  }

  return (
    <div style={{ display: 'flex', height: '100vh', fontFamily: 'system-ui' }}>
      <div style={{ width: 300, borderRight: '1px solid #ddd', padding: 16, overflow: 'auto' }}>
        <h3 style={{ margin: '0 0 4px' }}>Board spike</h3>
        <p style={{ fontSize: 12, color: '#888' }}>{ready ? '点规则 → 板上圈出两边来源' : '加载页图…'}</p>
        {RULES.map((r) => (
          <div
            key={r.id}
            onClick={() => focusRule(r)}
            style={{
              padding: '10px 12px',
              marginBottom: 8,
              borderRadius: 8,
              cursor: 'pointer',
              border: '1px solid',
              borderColor: activeRule === r.id ? '#b8860b' : '#e5e0d8',
              background: activeRule === r.id ? '#faf3e3' : '#fff',
              fontSize: 13,
              lineHeight: 1.5,
            }}
          >
            <span style={{ marginRight: 6 }}>{r.status === 'pass' ? '✓' : '✗'}</span>
            {r.text}
          </div>
        ))}
      </div>
      <div style={{ flex: 1 }}>
        <Excalidraw
          excalidrawAPI={onApi}
          onChange={onChange}
          initialData={{ appState: { viewBackgroundColor: '#faf8f4' } }}
        />
      </div>
    </div>
  )
}
