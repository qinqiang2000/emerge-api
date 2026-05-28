// AxisRail — the horizontal chip bar that lists every prompt (kind="prompt")
// or every model (kind="model") used across the bench rows. Two filter modes
// share the same `{kind, id}` shape:
//   - Hover  (transient): mouseenter / mouseleave emit onHover.
//   - Pinned (persistent): chip click toggles via onPin. Click same chip
//     clears, click another chip swaps. Parent applies `pinned ?? hovered`
//     when computing matrix dim.
import { describe, expect, it, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

import AxisRail from '../AxisRail'
import type { BenchPromptAxisItem, BenchModelAxisItem } from '../../../types/bench'

const PROMPTS: BenchPromptAxisItem[] = [
  { id: 'pr_baseline', label: 'baseline', is_active: true, refs: 4 },
  { id: 'pr_supplier', label: 'supplier-hint', is_active: false, refs: 2 },
]

const MODELS: BenchModelAxisItem[] = [
  { id: 'm_gemini', label: 'gemini-flash', provider_model_id: 'gemini-2.5-flash', is_active: true, refs: 4 },
  { id: 'm_sonnet', label: 'claude-sonnet', provider_model_id: 'claude-sonnet-4-5', is_active: false, refs: 1 },
]

const noopHover = () => {}
const noopPin = () => {}

describe('AxisRail (kind=prompt)', () => {
  it('renders one chip per prompt with its label', () => {
    render(<AxisRail kind="prompt" items={PROMPTS} hovered={null} pinned={null} onHover={noopHover} onPin={noopPin} />)
    expect(screen.getByText('baseline')).toBeInTheDocument()
    expect(screen.getByText('supplier-hint')).toBeInTheDocument()
  })

  it('marks the active chip with a star indicator', () => {
    render(<AxisRail kind="prompt" items={PROMPTS} hovered={null} pinned={null} onHover={noopHover} onPin={noopPin} />)
    const stars = screen.getAllByTestId('axisrail-star')
    expect(stars).toHaveLength(1)
    const activeChip = stars[0].closest('button')
    expect(activeChip).toHaveTextContent('baseline')
  })

  it('renders the refs count next to each chip', () => {
    render(<AxisRail kind="prompt" items={PROMPTS} hovered={null} pinned={null} onHover={noopHover} onPin={noopPin} />)
    const refs = screen.getAllByTestId('axisrail-refs').map((el) => el.textContent ?? '')
    expect(refs.some((t) => t.includes('4'))).toBe(true)
    expect(refs.some((t) => t.includes('2'))).toBe(true)
  })

  it('hovering a chip dispatches onHover({kind, id}); leaving emits null', () => {
    const onHover = vi.fn()
    render(<AxisRail kind="prompt" items={PROMPTS} hovered={null} pinned={null} onHover={onHover} onPin={noopPin} />)
    const chip = screen.getByText('supplier-hint').closest('button') as HTMLButtonElement
    fireEvent.mouseEnter(chip)
    expect(onHover).toHaveBeenCalledWith({ kind: 'prompt', id: 'pr_supplier' })
    fireEvent.mouseLeave(chip)
    expect(onHover).toHaveBeenLastCalledWith(null)
  })

  it('paints the matching hovered chip with a `.hover` class', () => {
    render(
      <AxisRail
        kind="prompt"
        items={PROMPTS}
        hovered={{ kind: 'prompt', id: 'pr_supplier' }}
        pinned={null}
        onHover={noopHover}
        onPin={noopPin}
      />,
    )
    const chip = screen.getByText('supplier-hint').closest('button') as HTMLButtonElement
    expect(chip.className).toMatch(/\bhover\b/)
  })

  it('clicking an unpinned chip dispatches onPin({kind, id})', () => {
    const onPin = vi.fn()
    render(<AxisRail kind="prompt" items={PROMPTS} hovered={null} pinned={null} onHover={noopHover} onPin={onPin} />)
    const chip = screen.getByText('supplier-hint').closest('button') as HTMLButtonElement
    fireEvent.click(chip)
    expect(onPin).toHaveBeenCalledWith({ kind: 'prompt', id: 'pr_supplier' })
  })

  it('clicking the already-pinned chip dispatches onPin(null) (toggle off)', () => {
    const onPin = vi.fn()
    render(
      <AxisRail
        kind="prompt"
        items={PROMPTS}
        hovered={null}
        pinned={{ kind: 'prompt', id: 'pr_supplier' }}
        onHover={noopHover}
        onPin={onPin}
      />,
    )
    const chip = screen.getByText('supplier-hint').closest('button') as HTMLButtonElement
    fireEvent.click(chip)
    expect(onPin).toHaveBeenCalledWith(null)
  })

  it('paints `.pinned` class + aria-pressed=true on the pinned chip only', () => {
    render(
      <AxisRail
        kind="prompt"
        items={PROMPTS}
        hovered={null}
        pinned={{ kind: 'prompt', id: 'pr_supplier' }}
        onHover={noopHover}
        onPin={noopPin}
      />,
    )
    const supplierChip = screen.getByText('supplier-hint').closest('button') as HTMLButtonElement
    const baselineChip = screen.getByText('baseline').closest('button') as HTMLButtonElement
    expect(supplierChip.className).toMatch(/\bpinned\b/)
    expect(supplierChip).toHaveAttribute('aria-pressed', 'true')
    expect(baselineChip.className).not.toMatch(/\bpinned\b/)
    expect(baselineChip).toHaveAttribute('aria-pressed', 'false')
  })

  it('does NOT paint `.pinned` when pin is on a different rail kind', () => {
    render(
      <AxisRail
        kind="prompt"
        items={PROMPTS}
        hovered={null}
        // pin on the *model* axis — prompt rail must ignore it
        pinned={{ kind: 'model', id: 'pr_supplier' }}
        onHover={noopHover}
        onPin={noopPin}
      />,
    )
    const supplierChip = screen.getByText('supplier-hint').closest('button') as HTMLButtonElement
    expect(supplierChip.className).not.toMatch(/\bpinned\b/)
  })

  it('renders the `+ new` chip as DISABLED with a tooltip explaining the agent path', () => {
    render(<AxisRail kind="prompt" items={PROMPTS} hovered={null} pinned={null} onHover={noopHover} onPin={noopPin} />)
    const newChip = screen.getByText(/\+\s*new/i).closest('button') as HTMLButtonElement
    expect(newChip).toBeDisabled()
    expect(newChip).toHaveAttribute('aria-disabled', 'true')
    expect(newChip).toHaveAttribute('title')
    expect(newChip.getAttribute('title')!.length).toBeGreaterThan(0)
  })
})

describe('AxisRail (kind=model)', () => {
  it('renders model chips and the kind=model rail header', () => {
    render(<AxisRail kind="model" items={MODELS} hovered={null} pinned={null} onHover={noopHover} onPin={noopPin} />)
    expect(screen.getByText('gemini-flash')).toBeInTheDocument()
    expect(screen.getByText('claude-sonnet')).toBeInTheDocument()
    expect(screen.getByText(/^models$/i)).toBeInTheDocument()
  })

  it('hovering a model chip dispatches kind=model', () => {
    const onHover = vi.fn()
    render(<AxisRail kind="model" items={MODELS} hovered={null} pinned={null} onHover={onHover} onPin={noopPin} />)
    fireEvent.mouseEnter(screen.getByText('claude-sonnet').closest('button')!)
    expect(onHover).toHaveBeenCalledWith({ kind: 'model', id: 'm_sonnet' })
  })

  it('clicking a model chip dispatches onPin with kind=model', () => {
    const onPin = vi.fn()
    render(<AxisRail kind="model" items={MODELS} hovered={null} pinned={null} onHover={noopHover} onPin={onPin} />)
    fireEvent.click(screen.getByText('claude-sonnet').closest('button')!)
    expect(onPin).toHaveBeenCalledWith({ kind: 'model', id: 'm_sonnet' })
  })
})
